import mimetypes
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import ImageOps
from pypdf import PdfReader, Transformation
from pypdf._utils import matrix_multiply
from pypdf.generic import ContentStream

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


def extract_pdf_images(pdf_path: Path, output_dir: Path) -> list[dict[str, Any]]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_directory(output_dir)

    reader = PdfReader(str(pdf_path))
    rows: list[dict[str, Any]] = []

    for page_idx, page in enumerate(reader.pages, start=1):
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
                    }
                )

    return rows
