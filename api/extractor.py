import re
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageChops, ImageFilter

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
VECTOR_RENDER_SCALE = 2.0
VECTOR_COMPONENT_MIN_AREA = 80
VECTOR_COMPONENT_MAX_FILL = 0.15
LEFT_SKETCH_STRIP_RIGHT_RATIO = 0.34
LEFT_SKETCH_STRIP_TOP_RATIO = 0.12
LEFT_SKETCH_STRIP_BOTTOM_RATIO = 0.92
VECTOR_STRIP_MIN_NONWHITE_RATIO = 0.34
VECTOR_STRIP_MAX_DARK_RATIO = 0.22
POSITION_LINE_ART_LEFT_PT = 26.0
POSITION_LINE_ART_RIGHT_PT = 220.0
POSITION_LINE_ART_TOP_PAD_PT = 8.0
POSITION_LINE_ART_BOTTOM_PAD_PT = 6.0
POSITION_LINE_ART_LAST_BLOCK_PT = 170.0
POSITION_LINE_ART_MIN_WIDTH = 80
POSITION_LINE_ART_MIN_HEIGHT = 60
FITZ_IMAGE_SOURCE = "fitz_image_block"


def extract_pdf_text(pdf_path: Path) -> str:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    document = fitz.open(str(pdf_path))
    try:
        text = "\n\f\n".join(page.get_text("text", sort=True) or "" for page in document).strip()
    finally:
        document.close()
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


def _clamp_ratio(value: float) -> float:
    return max(0.0, min(1.0, value))


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


def _normal_image_suffix(ext: Any) -> str:
    value = str(ext or "").strip().lower().lstrip(".")
    if value in {"jpg", "jpeg"}:
        return ".jpg"
    if value in {"jpx", "jp2"}:
        return f".{value}"
    if value in {"png", "gif", "bmp", "tif", "tiff", "jb2", "jbig2"}:
        return f".{value}"
    return ".png"


def _fitz_image_block_rows(pdf_path: Path, output_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    document = fitz.open(str(pdf_path))
    try:
        for page_idx in range(document.page_count):
            page_ref = page_idx + 1
            page = document.load_page(page_idx)
            page_width = float(page.rect.width or 0)
            page_height = float(page.rect.height or 0)
            try:
                text_dict = page.get_text("dict")
            except Exception:
                continue

            image_index = 0
            for block_no, block in enumerate(text_dict.get("blocks", []), start=1):
                if not isinstance(block, dict) or block.get("type") != 1:
                    continue
                data = block.get("image")
                if not isinstance(data, (bytes, bytearray)) or not data:
                    continue

                bbox = block.get("bbox")
                if not isinstance(bbox, (tuple, list)) or len(bbox) < 4:
                    continue
                try:
                    left, top, right, bottom = [float(value) for value in bbox[:4]]
                except (TypeError, ValueError):
                    continue
                if right <= left or bottom <= top:
                    continue
                display_width = right - left
                display_height = bottom - top
                if max(display_width, display_height) < 40 or display_width * display_height < 900:
                    continue

                image_index += 1
                suffix = _normal_image_suffix(block.get("ext"))
                filename = f"page_{page_ref:03d}_img_{image_index:03d}{suffix}"
                target_path = output_dir / filename
                payload = bytes(data)
                target_path.write_bytes(payload)

                metadata = _crop_layout_metadata(
                    left,
                    top,
                    right,
                    bottom,
                    canvas_width=page_width,
                    canvas_height=page_height,
                    source=FITZ_IMAGE_SOURCE,
                )
                metadata["fitz_block_no"] = block_no

                rows.append(
                    {
                        "page_ref": page_ref,
                        "image_index": image_index,
                        "mime_type": MIME_BY_SUFFIX.get(suffix, "image/png"),
                        "storage_path": str(target_path),
                        "sha256": sha256(payload).hexdigest(),
                        "width": int(block.get("width") or max(1, display_width)),
                        "height": int(block.get("height") or max(1, display_height)),
                        "bytes_size": len(payload),
                        "metadata_json": metadata,
                    }
                )
    finally:
        document.close()

    return rows


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


def _bbox_area(box: tuple[int, int, int, int]) -> int:
    left, top, right, bottom = box
    return max(0, right - left) * max(0, bottom - top)


def _bbox_overlap_ratio(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    overlap_x = _overlap_len(a[0], a[2], b[0], b[2])
    overlap_y = _overlap_len(a[1], a[3], b[1], b[3])
    intersection = overlap_x * overlap_y
    smallest = min(_bbox_area(a), _bbox_area(b))
    if intersection <= 0 or smallest <= 0:
        return 0.0
    return intersection / smallest


def _has_significant_bbox_overlap(
    box: tuple[int, int, int, int],
    others: list[tuple[int, int, int, int]],
    *,
    min_ratio: float = 0.35,
) -> bool:
    return any(_bbox_overlap_ratio(box, other) >= min_ratio for other in others)


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


def _normalized_pdf_block_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _position_line_art_boxes(page: Any, rendered: Image.Image) -> list[tuple[int, int, int, int]]:
    if rendered.width <= 0 or rendered.height <= 0:
        return []

    rect = getattr(page, "rect", None)
    page_width = float(getattr(rect, "width", 0.0) or 0.0)
    page_height = float(getattr(rect, "height", 0.0) or 0.0)
    if page_width <= 0 or page_height <= 0:
        return []

    try:
        blocks = page.get_text("blocks")
    except Exception:
        return []

    starts: list[tuple[float, float]] = []
    for block in blocks:
        if not isinstance(block, (tuple, list)) or len(block) < 5:
            continue
        try:
            x0 = float(block[0])
            y0 = float(block[1])
            y1 = float(block[3])
        except (TypeError, ValueError):
            continue
        if x0 > 140:
            continue

        text = _normalized_pdf_block_text(block[4])
        if not re.search(r"(?:^|\s)Pos\.\s*\d+\b", text, flags=re.IGNORECASE):
            continue
        starts.append((y0, y1))

    starts.sort(key=lambda item: item[0])
    deduped_starts: list[tuple[float, float]] = []
    for y0, y1 in starts:
        if deduped_starts and abs(y0 - deduped_starts[-1][0]) < 6:
            prev_y0, prev_y1 = deduped_starts[-1]
            deduped_starts[-1] = (prev_y0, max(prev_y1, y1))
            continue
        deduped_starts.append((y0, y1))

    if not deduped_starts:
        return []

    scale_x = rendered.width / page_width
    scale_y = rendered.height / page_height
    crop_left = int(max(0, POSITION_LINE_ART_LEFT_PT * scale_x))
    crop_right = int(min(rendered.width, POSITION_LINE_ART_RIGHT_PT * scale_x))
    if crop_right - crop_left < POSITION_LINE_ART_MIN_WIDTH:
        return []

    boxes: list[tuple[int, int, int, int]] = []
    for idx, (y0, y1) in enumerate(deduped_starts):
        next_y0 = deduped_starts[idx + 1][0] if idx + 1 < len(deduped_starts) else None
        block_bottom = (
            next_y0 - POSITION_LINE_ART_BOTTOM_PAD_PT
            if next_y0 is not None
            else y1 + POSITION_LINE_ART_LAST_BLOCK_PT
        )
        block_bottom = min(page_height - 30.0, block_bottom)
        block_top = max(0.0, y0 - POSITION_LINE_ART_TOP_PAD_PT)
        if block_bottom <= block_top:
            continue

        crop_top = int(max(0, block_top * scale_y))
        crop_bottom = int(min(rendered.height, block_bottom * scale_y))
        if crop_bottom - crop_top < POSITION_LINE_ART_MIN_HEIGHT:
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


def _line_art_metrics(crop: Image.Image) -> dict[str, float | int]:
    mask = crop.convert("L").point(lambda px: 255 if px < 210 else 0)
    pixels = mask.load()
    width, height = mask.size
    total = max(1, width * height)
    dark = 0

    min_horizontal_run = max(10, int(width * 0.08))
    horizontal_pixels = 0
    horizontal_runs = 0
    max_horizontal_run = 0
    for y in range(height):
        run = 0
        for x in range(width):
            if pixels[x, y] > 0:
                dark += 1
                run += 1
                continue
            if run >= min_horizontal_run:
                horizontal_runs += 1
                horizontal_pixels += run
                max_horizontal_run = max(max_horizontal_run, run)
            run = 0
        if run >= min_horizontal_run:
            horizontal_runs += 1
            horizontal_pixels += run
            max_horizontal_run = max(max_horizontal_run, run)

    min_vertical_run = max(10, int(height * 0.10))
    vertical_pixels = 0
    vertical_runs = 0
    max_vertical_run = 0
    for x in range(width):
        run = 0
        for y in range(height):
            if pixels[x, y] > 0:
                run += 1
                continue
            if run >= min_vertical_run:
                vertical_runs += 1
                vertical_pixels += run
                max_vertical_run = max(max_vertical_run, run)
            run = 0
        if run >= min_vertical_run:
            vertical_runs += 1
            vertical_pixels += run
            max_vertical_run = max(max_vertical_run, run)

    return {
        "line_art_dark_ratio": round(dark / total, 6),
        "line_art_horizontal_ratio": round(horizontal_pixels / total, 6),
        "line_art_horizontal_runs": horizontal_runs,
        "line_art_max_horizontal_run_ratio": round(max_horizontal_run / max(1, width), 6),
        "line_art_vertical_ratio": round(vertical_pixels / total, 6),
        "line_art_vertical_runs": vertical_runs,
        "line_art_max_vertical_run_ratio": round(max_vertical_run / max(1, height), 6),
    }


def _looks_like_position_line_art(
    crop: Image.Image,
    crop_metrics: dict[str, float],
    line_metrics: dict[str, float | int],
) -> bool:
    if crop.width < POSITION_LINE_ART_MIN_WIDTH or crop.height < POSITION_LINE_ART_MIN_HEIGHT:
        return False
    if crop_metrics["content_nonwhite_ratio"] < 0.025:
        return False
    if float(line_metrics["line_art_dark_ratio"]) < 0.015:
        return False

    horizontal_runs = int(line_metrics["line_art_horizontal_runs"])
    vertical_runs = int(line_metrics["line_art_vertical_runs"])
    max_horizontal_ratio = float(line_metrics["line_art_max_horizontal_run_ratio"])
    max_vertical_ratio = float(line_metrics["line_art_max_vertical_run_ratio"])

    if vertical_runs >= 5 and max_vertical_ratio >= 0.24:
        return True
    if horizontal_runs >= 5 and max_horizontal_ratio >= 0.18 and vertical_runs >= 4:
        return True
    if horizontal_runs >= 8 and vertical_runs >= 6:
        return True
    return False


def _technical_line_art_bbox(crop: Image.Image) -> tuple[int, int, int, int] | None:
    gray = crop.convert("L")
    pixels = gray.load()
    width, height = gray.size
    if width <= 0 or height <= 0:
        return None

    horizontal_coords: list[tuple[int, int]] = []
    vertical_coords: list[tuple[int, int]] = []

    # Technical drawings and dimensions contain long ruled segments. Header labels
    # such as "Pos." or "1 Stck" do not, and full-width separators are filtered out.
    min_horizontal_run = max(16, int(width * 0.08))
    max_horizontal_run = max(min_horizontal_run + 1, int(width * 0.58))
    for y in range(height):
        run_start: int | None = None
        for x in range(width):
            is_content = pixels[x, y] < 245
            if is_content and run_start is None:
                run_start = x
                continue
            if is_content:
                continue
            if run_start is None:
                continue
            run = x - run_start
            if min_horizontal_run <= run <= max_horizontal_run:
                horizontal_coords.extend((xx, y) for xx in range(run_start, x))
            run_start = None
        if run_start is not None:
            run = width - run_start
            if min_horizontal_run <= run <= max_horizontal_run:
                horizontal_coords.extend((xx, y) for xx in range(run_start, width))

    min_vertical_run = max(16, int(height * 0.09))
    max_vertical_run = max(min_vertical_run + 1, int(height * 0.85))
    for x in range(width):
        run_start: int | None = None
        for y in range(height):
            is_content = pixels[x, y] < 245
            if is_content and run_start is None:
                run_start = y
                continue
            if is_content:
                continue
            if run_start is None:
                continue
            run = y - run_start
            if min_vertical_run <= run <= max_vertical_run:
                vertical_coords.extend((x, yy) for yy in range(run_start, y))
            run_start = None
        if run_start is not None:
            run = height - run_start
            if min_vertical_run <= run <= max_vertical_run:
                vertical_coords.extend((x, yy) for yy in range(run_start, height))

    if not vertical_coords:
        return None

    coords = horizontal_coords + vertical_coords
    xs = [point[0] for point in coords]
    ys = [point[1] for point in coords]
    vertical_ys = [point[1] for point in vertical_coords]

    left = min(xs)
    right = max(xs) + 1
    # Top is intentionally based on vertical drawing strokes so table/header
    # separators above the sketch cannot pull the crop upwards.
    top = min(vertical_ys)
    vertical_bottom = max(vertical_ys)
    vertical_span = max(1, vertical_bottom - top)
    lower_context = max(48, int(vertical_span * 0.45), int(width * 0.20))
    # Text below the sketch, for example a following "Alternative:" heading, can
    # contain underlines that look like technical horizontal rules. Keep only
    # horizontal/dimension strokes close to the vertical drawing span.
    bottom_candidates = [
        y
        for _x, y in coords
        if y <= vertical_bottom + lower_context
    ]
    bottom = (max(bottom_candidates) if bottom_candidates else vertical_bottom) + 1

    pad_left = max(16, int(width * 0.045))
    pad_right = max(28, int(width * 0.075))
    pad_top = max(2, int(height * 0.01))
    pad_bottom = max(18, int(height * 0.075))

    return (
        max(0, left - pad_left),
        max(0, top - pad_top),
        min(width, right + pad_right),
        min(height, bottom + pad_bottom),
    )


def _looks_like_embedded_product_image(row: dict[str, Any]) -> bool:
    try:
        width = int(row.get("width") or 0)
        height = int(row.get("height") or 0)
        bytes_size = int(row.get("bytes_size") or 0)
    except (TypeError, ValueError):
        return False
    if width <= 0 or height <= 0:
        return False

    area = width * height
    ratio = max(width, height) / max(1, min(width, height))
    if area < 45_000 and bytes_size < 20_000:
        return False
    if ratio >= 4.5 and min(width, height) <= 90 and bytes_size < 30_000:
        return False
    return True


def _extract_vector_crop_rows(
    pdf_path: Path,
    output_dir: Path,
    existing_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    next_index_by_page: dict[int, int] = {}
    hashes_by_page: dict[int, set[str]] = {}
    has_product_image_by_page: dict[int, bool] = {}
    for row in existing_rows:
        page_ref = int(row.get("page_ref") or 0)
        if page_ref <= 0:
            continue
        current_idx = int(row.get("image_index") or 0)
        next_index_by_page[page_ref] = max(next_index_by_page.get(page_ref, 0), current_idx)
        digest = str(row.get("sha256") or "")
        if digest:
            hashes_by_page.setdefault(page_ref, set()).add(digest)
        if _looks_like_embedded_product_image(row):
            has_product_image_by_page[page_ref] = True

    rows: list[dict[str, Any]] = []
    document = fitz.open(str(pdf_path))
    try:
        for page_idx in range(document.page_count):
            page_ref = page_idx + 1
            page = document.load_page(page_idx)
            matrix = fitz.Matrix(VECTOR_RENDER_SCALE, VECTOR_RENDER_SCALE)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            rendered = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            candidate_boxes = []
            position_boxes: list[tuple[int, int, int, int]] = []
            if not has_product_image_by_page.get(page_ref):
                position_boxes = _position_line_art_boxes(page, rendered)
                candidate_boxes.extend((bbox, "vector_position_line_art") for bbox in position_boxes)

                # Rekord pages can start a position at the bottom of one page
                # while the actual sketch is rendered near the top of the next
                # page. In that case no "Pos." anchor exists on the sketch page,
                # so the left-strip detector must supplement the position-based
                # boxes instead of being only a fallback.
                for bbox in _extract_left_strip_sketch_boxes(rendered):
                    if _has_significant_bbox_overlap(bbox, position_boxes):
                        continue
                    candidate_boxes.append((bbox, "vector_strip_band"))
            if not candidate_boxes:
                candidate_boxes.extend((bbox, "vector_strip_band") for bbox in _extract_left_strip_sketch_boxes(rendered))

            if not candidate_boxes:
                continue

            candidate_boxes.sort(key=lambda item: (item[0][1], item[0][0], item[1]))

            for (left, top, right, bottom), source in candidate_boxes:
                raw_crop = rendered.crop((left, top, right, bottom))
                refine_bbox = None
                if source == "vector_position_line_art":
                    refine_bbox = _technical_line_art_bbox(raw_crop)
                    if refine_bbox is not None:
                        raw_crop = raw_crop.crop(refine_bbox)

                crop, trim_bbox = _trim_and_pad_crop(raw_crop)
                if crop.width < 48 or crop.height < 64:
                    continue
                crop_metrics = _crop_content_metrics(crop)
                line_metrics = _line_art_metrics(crop)
                if source == "vector_position_line_art":
                    if not _looks_like_position_line_art(crop, crop_metrics, line_metrics):
                        continue
                else:
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
                refine_left, refine_top = (refine_bbox[0], refine_bbox[1]) if refine_bbox is not None else (0, 0)
                content_left = left + refine_left + trim_left
                content_top = top + refine_top + trim_top
                content_right = left + refine_left + trim_right
                content_bottom = top + refine_top + trim_bottom

                next_index = next_index_by_page.get(page_ref, 0) + 1
                next_index_by_page[page_ref] = next_index
                hashes_by_page.setdefault(page_ref, set()).add(digest)

                filename = f"page_{page_ref:03d}_img_{next_index:03d}.png"
                target_path = output_dir / filename
                target_path.write_bytes(data)
                metadata = _crop_layout_metadata(
                    content_left,
                    content_top,
                    content_right,
                    content_bottom,
                    canvas_width=rendered.width,
                    canvas_height=rendered.height,
                    source=source,
                )
                if refine_bbox is not None:
                    metadata["line_art_refined_crop"] = True
                    metadata["line_art_refine_bbox"] = list(refine_bbox)

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
                        "metadata_json": metadata | crop_metrics | line_metrics,
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

    rows = _fitz_image_block_rows(pdf_path, output_dir)

    # Some PDFs draw product sketches as vectors; render and crop detectable line-art blocks.
    rows.extend(_extract_vector_crop_rows(pdf_path, output_dir, rows))

    return rows
