from pathlib import Path
from typing import Any

from PIL import Image

try:
    import fitz
except Exception:  # pragma: no cover - optional runtime dependency
    fitz = None


BROWSER_INLINE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
}
BROWSER_INLINE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
PREVIEW_CACHE_DIR = Path("/tmp/pdr_image_preview_cache")


def _has_alpha(image: Image.Image) -> bool:
    return "A" in image.getbands()


def _normalize_png_image(image: Image.Image) -> Image.Image:
    if image.mode in {"1", "L", "LA", "P", "RGB", "RGBA"}:
        if image.mode == "P":
            return image.convert("RGBA" if "transparency" in image.info else "RGB")
        return image.copy()
    return image.convert("RGBA" if _has_alpha(image) else "RGB")


def browser_preview_for_image(
    image_path: Path,
    *,
    mime_type: str | None = None,
    cache_key: str | None = None,
) -> tuple[Path, str, bool]:
    normalized_mime = str(mime_type or "").strip().lower()
    normalized_suffix = image_path.suffix.lower()
    if normalized_mime in BROWSER_INLINE_MIME_TYPES:
        return image_path, normalized_mime or "application/octet-stream", False
    if not normalized_mime and normalized_suffix in BROWSER_INLINE_SUFFIXES:
        return image_path, normalized_mime or "application/octet-stream", False

    PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    preview_key = cache_key or image_path.stem
    preview_path = PREVIEW_CACHE_DIR / f"{preview_key}.png"
    if preview_path.exists() and preview_path.is_file():
        return preview_path, "image/png", True

    try:
        with Image.open(image_path) as img:
            converted = _normalize_png_image(img)
            converted.save(preview_path, format="PNG")
        return preview_path, "image/png", True
    except Exception:
        if fitz is None:
            return image_path, normalized_mime or "application/octet-stream", False
        try:
            doc = fitz.open(str(image_path))
            page = doc[0]
            pix = page.get_pixmap(alpha=True)
            pix.save(preview_path)
            return preview_path, "image/png", True
        except Exception:
            return image_path, normalized_mime or "application/octet-stream", False
