import mimetypes
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageOps
from pypdf import PdfReader, Transformation
from pypdf._utils import matrix_multiply
from pypdf.generic import ContentStream

try:
    import fitz
except Exception:  # pragma: no cover - optional runtime dependency
    fitz = None

MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jpe": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".jp2": "image/jp2",
    ".jpx": "image/jpx",
    ".jb2": "image/jbig2",
    ".jbig2": "image/jbig2",
}
IDENTITY_CTM = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
EPS = 1e-6
VECTOR_RENDER_SCALE = 2.0
VECTOR_COMPONENT_MIN_AREA = 80
VECTOR_COMPONENT_MAX_FILL = 0.15
LEFT_SKETCH_STRIP_RIGHT_RATIO = 0.34
LEFT_SKETCH_STRIP_TOP_RATIO = 0.12
LEFT_SKETCH_STRIP_BOTTOM_RATIO = 0.92
VECTOR_STRIP_MIN_NONWHITE_RATIO = 0.34
VECTOR_STRIP_MAX_DARK_RATIO = 0.22


def extract_pdf_text(pdf_path: Path) -> str:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")

    text = "\n\f\n".join(pages).strip()
    if not text:
        raise ValueError("No text could be extracted from the PDF.")
    return text


def _clear_directory(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_file():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            _clear_directory(child)
            child.rmdir()


def _normalize_image_name(raw_name: str | None) -> str:
    if not raw_name:
        return ""
    base = Path(str(raw_name)).name
    stem = Path(base).stem
    return stem.lstrip("/")


def _compose_ctm(base: tuple[float, float, float, float, float, float], op: tuple[float, float, float, float, float, float]) -> tuple[float, float, float, float, float, float]:
    return Transformation.compress(matrix_multiply(Transformation(base).matrix, Transformation(op).matrix))


def _extract_page_image_placements(page, reader: PdfReader) -> list[dict[str, Any]]:
    content = page.get_contents()
    if content is None:
        return []
    try:
        stream = ContentStream(content, reader)
    except Exception:
        return []

    placements: list[dict[str, Any]] = []
    ctm_stack: list[tuple[float, float, float, float, float, float]] = []
    current_ctm = IDENTITY_CTM

    for operands, operator in stream.operations:
        op = operator.decode("latin1") if isinstance(operator, bytes) else str(operator)
        if op == "q":
            ctm_stack.append(current_ctm)
            continue
        if op == "Q":
            current_ctm = ctm_stack.pop() if ctm_stack else IDENTITY_CTM
            continue
        if op == "cm" and len(operands) >= 6:
            try:
                matrix = tuple(float(val) for val in operands[:6])
                current_ctm = _compose_ctm(current_ctm, matrix)
            except Exception:
                continue
            continue
        if op == "Do" and operands:
            name = _normalize_image_name(str(operands[0]))
            if not name:
                continue
            placements.append({"name": name, "ctm": current_ctm})

    return placements


def _render_ops_from_ctm(ctm: tuple[float, float, float, float, float, float]) -> tuple[int, bool, bool]:
    a, b, c, d, _, _ = ctm
    rotate = 0
    flip_x = False
    flip_y = False

    if abs(b) < EPS and abs(c) < EPS:
        flip_x = a < 0
        flip_y = d < 0
        return rotate, flip_x, flip_y

    if abs(a) < EPS and abs(d) < EPS:
        if b > 0 and c < 0:
            rotate = 90
        elif b < 0 and c > 0:
            rotate = 270
    return rotate, flip_x, flip_y


def _build_image_payload(image, *, ctm: tuple[float, float, float, float, float, float]) -> dict[str, Any]:
    rotate, flip_x, flip_y = _render_ops_from_ctm(ctm)
    base_name = Path(image.name or "").name
    suffix = Path(base_name).suffix.lower() or ".bin"
    mime_type = MIME_BY_SUFFIX.get(suffix) or mimetypes.guess_type(base_name)[0] or "application/octet-stream"

    pil_image = getattr(image, "image", None)
    needs_transform = bool(rotate or flip_x or flip_y)
    transformed = False

    if needs_transform and pil_image is not None:
        rendered = pil_image.copy()
        if flip_x:
            rendered = ImageOps.mirror(rendered)
        if flip_y:
            rendered = ImageOps.flip(rendered)
        if rotate in {90, 180, 270}:
            rendered = rendered.rotate(rotate, expand=True)

        buffer = BytesIO()
        rendered.save(buffer, format="PNG")
        data = buffer.getvalue()
        suffix = ".png"
        mime_type = "image/png"
        width, height = rendered.size
        transformed = True
    else:
        data = image.data
        width = None
        height = None
        if pil_image is not None and getattr(pil_image, "size", None):
            width, height = pil_image.size

    return {
        "data": data,
        "suffix": suffix,
        "mime_type": mime_type,
        "width": width,
        "height": height,
        "render_rotation": rotate,
        "render_flip_x": flip_x,
        "render_flip_y": flip_y,
        "render_transform_applied": transformed,
    }


def _clamp_ratio(value: float) -> float:
    return max(0.0, min(1.0, value))


def _ctm_layout_metadata(
    ctm: tuple[float, float, float, float, float, float],
    *,
    page_width: float,
    page_height: float,
) -> dict[str, Any]:
    if page_width <= 0 or page_height <= 0:
        return {}

    a, b, c, d, e, f = ctm
    corners = (
        (e, f),
        (a + e, b + f),
        (c + e, d + f),
        (a + c + e, b + d + f),
    )
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    left = min(xs)
    right = max(xs)
    bottom = min(ys)
    top = max(ys)
    center_x = (left + right) / 2.0
    center_y = (bottom + top) / 2.0

    return {
        "layout_source": "pdf_placement",
        "left_ratio": round(_clamp_ratio(left / page_width), 6),
        "right_ratio": round(_clamp_ratio(right / page_width), 6),
        "width_ratio": round(_clamp_ratio((right - left) / page_width), 6),
        "top_ratio": round(_clamp_ratio(1.0 - (top / page_height)), 6),
        "bottom_ratio": round(_clamp_ratio(1.0 - (bottom / page_height)), 6),
        "height_ratio": round(_clamp_ratio((top - bottom) / page_height), 6),
        "center_x_ratio": round(_clamp_ratio(center_x / page_width), 6),
        "center_y_ratio": round(_clamp_ratio(1.0 - (center_y / page_height)), 6),
    }


def _crop_layout_metadata(
    left: int,
    top: int,
    right: int,
    bottom: int,
    *,
    canvas_width: int,
    canvas_height: int,
    source: str,
) -> dict[str, Any]:
    if canvas_width <= 0 or canvas_height <= 0:
        return {}

    width = max(1, right - left)
    height = max(1, bottom - top)
    center_x = left + (width / 2.0)
    center_y = top + (height / 2.0)
    return {
        "layout_source": source,
        "left_ratio": round(_clamp_ratio(left / canvas_width), 6),
        "right_ratio": round(_clamp_ratio(right / canvas_width), 6),
        "width_ratio": round(_clamp_ratio(width / canvas_width), 6),
        "top_ratio": round(_clamp_ratio(top / canvas_height), 6),
        "bottom_ratio": round(_clamp_ratio(bottom / canvas_height), 6),
        "height_ratio": round(_clamp_ratio(height / canvas_height), 6),
        "center_x_ratio": round(_clamp_ratio(center_x / canvas_width), 6),
        "center_y_ratio": round(_clamp_ratio(center_y / canvas_height), 6),
    }


def _component_bboxes(mask: Image.Image) -> list[tuple[int, int, int, int]]:
    width, height = mask.size
    if width <= 0 or height <= 0:
        return []

    scale = 4
    small_w = max(1, width // scale)
    small_h = max(1, height // scale)
    small = mask.resize((small_w, small_h), Image.NEAREST).convert("L")
    pixels = small.load()
    visited = bytearray(small_w * small_h)

    max_fill = int((small_w * small_h) * VECTOR_COMPONENT_MAX_FILL)
    boxes: list[tuple[int, int, int, int, int]] = []

    for y in range(small_h):
        for x in range(small_w):
            idx = y * small_w + x
            if visited[idx] or pixels[x, y] <= 0:
                continue

            stack = [(x, y)]
            visited[idx] = 1
            min_x = max_x = x
            min_y = max_y = y
            area = 0

            while stack:
                cx, cy = stack.pop()
                area += 1
                if cx < min_x:
                    min_x = cx
                if cx > max_x:
                    max_x = cx
                if cy < min_y:
                    min_y = cy
                if cy > max_y:
                    max_y = cy

                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if nx < 0 or ny < 0 or nx >= small_w or ny >= small_h:
                        continue
                    n_idx = ny * small_w + nx
                    if visited[n_idx] or pixels[nx, ny] <= 0:
                        continue
                    visited[n_idx] = 1
                    stack.append((nx, ny))

            if area < VECTOR_COMPONENT_MIN_AREA:
                continue
            if max_fill > 0 and area > max_fill:
                continue
            left = max(0, min_x * scale)
            top = max(0, min_y * scale)
            right = min(width, (max_x + 1) * scale)
            bottom = min(height, (max_y + 1) * scale)
            if right - left < 16 or bottom - top < 16:
                continue
            boxes.append((left, top, right, bottom, area))

    boxes.sort(key=lambda item: item[4], reverse=True)
    return [(left, top, right, bottom) for left, top, right, bottom, _ in boxes]


def _overlap_len(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def _should_merge_bboxes(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    a_left, a_top, a_right, a_bottom = a
    b_left, b_top, b_right, b_bottom = b
    a_w = max(1, a_right - a_left)
    a_h = max(1, a_bottom - a_top)
    b_w = max(1, b_right - b_left)
    b_h = max(1, b_bottom - b_top)

    overlap_x = _overlap_len(a_left, a_right, b_left, b_right)
    overlap_y = _overlap_len(a_top, a_bottom, b_top, b_bottom)
    if overlap_x > 0 and overlap_y > 0:
        return True

    gap_x = max(0, max(a_left, b_left) - min(a_right, b_right))
    gap_y = max(0, max(a_top, b_top) - min(a_bottom, b_bottom))
    min_w = min(a_w, b_w)
    min_h = min(a_h, b_h)

    if overlap_y >= int(0.45 * min_h) and gap_x <= max(24, int(0.55 * min_w)):
        return True
    if overlap_x >= int(0.45 * min_w) and gap_y <= max(24, int(0.45 * min_h)):
        return True
    return False


def _merge_adjacent_bboxes(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            a = merged[i]
            for j in range(i + 1, len(merged)):
                b = merged[j]
                if not _should_merge_bboxes(a, b):
                    continue
                merged[i] = (
                    min(a[0], b[0]),
                    min(a[1], b[1]),
                    max(a[2], b[2]),
                    max(a[3], b[3]),
                )
                merged.pop(j)
                changed = True
                break
            if changed:
                break
    merged.sort(key=lambda box: (box[1], box[0]))
    return merged


def _row_bands_from_mask(mask: Image.Image, *, min_height: int) -> list[tuple[int, int]]:
    px = mask.load()
    width, height = mask.size
    if width <= 0 or height <= 0:
        return []

    threshold = max(12, int(width * 0.04))
    bands: list[tuple[int, int]] = []
    active: list[int] | None = None
    gap_run = 0
    max_gap = 14

    for y in range(height):
        count = 0
        for x in range(width):
            if px[x, y] > 0:
                count += 1
        if count >= threshold:
            gap_run = 0
            if active is None:
                active = [y, y]
            else:
                active[1] = y
            continue
        if active is None:
            continue
        gap_run += 1
        if gap_run <= max_gap:
            active[1] = y
            continue
        if active[1] - active[0] >= min_height:
            bands.append((active[0], active[1] - gap_run))
        active = None
        gap_run = 0

    if active is not None and active[1] - active[0] >= min_height:
        bands.append((active[0], active[1]))
    return bands


def _percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * ratio))))
    return ordered[idx]


def _extract_left_strip_sketch_boxes(rendered: Image.Image) -> list[tuple[int, int, int, int]]:
    strip_top = int(rendered.height * LEFT_SKETCH_STRIP_TOP_RATIO)
    strip_bottom = int(rendered.height * LEFT_SKETCH_STRIP_BOTTOM_RATIO)
    strip_right = max(120, int(rendered.width * LEFT_SKETCH_STRIP_RIGHT_RATIO))
    left_strip = rendered.crop((0, strip_top, strip_right, strip_bottom))

    red, green, blue = left_strip.split()
    whiteness = ImageChops.darker(ImageChops.darker(red, green), blue)
    mask = whiteness.point(lambda px: 255 if px <= 244 else 0).filter(ImageFilter.MedianFilter(size=3))
    bands = _row_bands_from_mask(mask, min_height=56)

    boxes: list[tuple[int, int, int, int]] = []
    px = mask.load()
    width, _ = mask.size
    for top, bottom in bands:
        xs: list[int] = []
        for y in range(top, bottom + 1):
            for x in range(width):
                if px[x, y] > 0:
                    xs.append(x)
        if not xs:
            continue

        left = _percentile(xs, 0.03)
        right = _percentile(xs, 0.97)
        if right - left < 140:
            continue

        pad_x = 14
        pad_y = 16
        crop_left = max(0, left - pad_x)
        crop_right = min(strip_right, max(120, int(rendered.width * 0.30)), right + pad_x)
        crop_top = max(0, top - pad_y) + strip_top
        crop_bottom = min(rendered.height, bottom + pad_y + strip_top)
        if crop_right - crop_left < 150 or crop_bottom - crop_top < 140:
            continue
        boxes.append((crop_left, crop_top, crop_right, crop_bottom))

    return boxes


def _trim_and_pad_crop(crop: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int]]:
    red, green, blue = crop.split()
    whiteness = ImageChops.darker(ImageChops.darker(red, green), blue)
    mask = whiteness.point(lambda px: 255 if px <= 248 else 0).filter(ImageFilter.MedianFilter(size=3))
    bbox = mask.getbbox()
    if bbox is None:
        bbox = (0, 0, crop.width, crop.height)
    trimmed = crop.crop(bbox)
    pad = max(10, int(max(trimmed.width, trimmed.height) * 0.05))
    canvas = Image.new("RGB", (trimmed.width + (pad * 2), trimmed.height + (pad * 2)), "white")
    canvas.paste(trimmed, (pad, pad))
    return canvas, bbox


def _crop_content_metrics(crop: Image.Image) -> dict[str, float]:
    pixels = crop.load()
    width, height = crop.size
    total = max(1, width * height)
    nonwhite = 0
    colorful = 0
    dark = 0
    for y in range(height):
        for x in range(width):
            red, green, blue = pixels[x, y]
            max_channel = max(red, green, blue)
            min_channel = min(red, green, blue)
            if min_channel < 248:
                nonwhite += 1
            if max_channel < 248 and (max_channel - min_channel) >= 24:
                colorful += 1
            if max_channel < 180:
                dark += 1
    return {
        "content_nonwhite_ratio": round(nonwhite / total, 6),
        "content_colorful_ratio": round(colorful / total, 6),
        "content_dark_ratio": round(dark / total, 6),
    }


def _extract_blue_vector_crop_rows(
    pdf_path: Path,
    output_dir: Path,
    existing_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if fitz is None:
        return []

    next_index_by_page: dict[int, int] = {}
    hashes_by_page: dict[int, set[str]] = {}
    for row in existing_rows:
        page_ref = int(row.get("page_ref") or 0)
        if page_ref <= 0:
            continue
        current_idx = int(row.get("image_index") or 0)
        next_index_by_page[page_ref] = max(next_index_by_page.get(page_ref, 0), current_idx)
        digest = str(row.get("sha256") or "")
        if digest:
            hashes_by_page.setdefault(page_ref, set()).add(digest)

    rows: list[dict[str, Any]] = []
    document = fitz.open(str(pdf_path))
    try:
        for page_idx in range(document.page_count):
            page_ref = page_idx + 1
            page = document.load_page(page_idx)
            matrix = fitz.Matrix(VECTOR_RENDER_SCALE, VECTOR_RENDER_SCALE)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            rendered = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            bboxes = _extract_left_strip_sketch_boxes(rendered)

            if not bboxes:
                continue

            for left, top, right, bottom in bboxes:
                crop = rendered.crop((left, top, right, bottom))
                crop, trim_bbox = _trim_and_pad_crop(crop)
                if crop.width < 48 or crop.height < 64:
                    continue
                crop_metrics = _crop_content_metrics(crop)
                if crop_metrics["content_nonwhite_ratio"] < VECTOR_STRIP_MIN_NONWHITE_RATIO:
                    continue
                if (
                    crop_metrics["content_dark_ratio"] > VECTOR_STRIP_MAX_DARK_RATIO
                    and crop_metrics["content_colorful_ratio"] < 0.01
                ):
                    continue

                buffer = BytesIO()
                crop.save(buffer, format="PNG")
                data = buffer.getvalue()
                digest = sha256(data).hexdigest()
                if digest in hashes_by_page.get(page_ref, set()):
                    continue

                trim_left, trim_top, trim_right, trim_bottom = trim_bbox
                content_left = left + trim_left
                content_top = top + trim_top
                content_right = left + trim_right
                content_bottom = top + trim_bottom

                next_index = next_index_by_page.get(page_ref, 0) + 1
                next_index_by_page[page_ref] = next_index
                hashes_by_page.setdefault(page_ref, set()).add(digest)

                filename = f"page_{page_ref:03d}_img_{next_index:03d}.png"
                target_path = output_dir / filename
                target_path.write_bytes(data)
                rows.append(
                    {
                        "page_ref": page_ref,
                        "image_index": next_index,
                        "mime_type": "image/png",
                        "storage_path": str(target_path),
                        "sha256": digest,
                        "width": crop.width,
                        "height": crop.height,
                        "bytes_size": len(data),
                        "metadata_json": _crop_layout_metadata(
                            content_left,
                            content_top,
                            content_right,
                            content_bottom,
                            canvas_width=rendered.width,
                            canvas_height=rendered.height,
                            source="vector_strip_band",
                        )
                        | crop_metrics,
                    }
                )
    finally:
        document.close()

    return rows


def extract_pdf_images(pdf_path: Path, output_dir: Path) -> list[dict[str, Any]]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_directory(output_dir)

    reader = PdfReader(str(pdf_path))
    rows: list[dict[str, Any]] = []

    for page_idx, page in enumerate(reader.pages, start=1):
        page_width = float(getattr(page.mediabox, "width", 0) or 0)
        page_height = float(getattr(page.mediabox, "height", 0) or 0)
        image_objects = list(getattr(page, "images", None) or [])
        image_by_name: dict[str, Any] = {}
        for image in image_objects:
            key = _normalize_image_name(image.name)
            if key and key not in image_by_name:
                image_by_name[key] = image

        placements = _extract_page_image_placements(page, reader)
        image_index = 0

        for placement in placements:
            image = image_by_name.get(placement["name"])
            if image is None:
                continue
            payload = _build_image_payload(image, ctm=placement["ctm"])
            data = payload["data"]
            image_index += 1
            filename = f"page_{page_idx:03d}_img_{image_index:03d}{payload['suffix']}"
            target_path = output_dir / filename
            target_path.write_bytes(data)
            rows.append(
                {
                    "page_ref": page_idx,
                    "image_index": image_index,
                    "mime_type": payload["mime_type"],
                    "storage_path": str(target_path),
                    "sha256": sha256(data).hexdigest(),
                    "width": payload["width"],
                    "height": payload["height"],
                    "bytes_size": len(data),
                    "metadata_json": _ctm_layout_metadata(
                        placement["ctm"],
                        page_width=page_width,
                        page_height=page_height,
                    ),
                }
            )

        # Fallback for PDFs where image placements could not be resolved.
        if image_index == 0:
            for fallback_idx, image in enumerate(image_objects, start=1):
                payload = _build_image_payload(image, ctm=IDENTITY_CTM)
                data = payload["data"]
                filename = f"page_{page_idx:03d}_img_{fallback_idx:03d}{payload['suffix']}"
                target_path = output_dir / filename
                target_path.write_bytes(data)
                rows.append(
                    {
                        "page_ref": page_idx,
                        "image_index": fallback_idx,
                        "mime_type": payload["mime_type"],
                        "storage_path": str(target_path),
                        "sha256": sha256(data).hexdigest(),
                        "width": payload["width"],
                        "height": payload["height"],
                        "bytes_size": len(data),
                        "metadata_json": {"layout_source": "fallback_page_images"},
                    }
                )

    # Some PDFs draw product sketches as vectors; render and crop dominant blue drawing blocks.
    rows.extend(_extract_blue_vector_crop_rows(pdf_path, output_dir, rows))

    return rows
