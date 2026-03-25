import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from image_preview import browser_preview_for_image


def test_browser_preview_keeps_native_png() -> None:
    image_path = Path("/tmp/native_preview_test.png")
    Image.new("RGB", (8, 8), "#ff0000").save(image_path, format="PNG")

    preview_path, media_type, transcoded = browser_preview_for_image(
        image_path,
        mime_type="image/png",
        cache_key="native_preview_test",
    )

    assert preview_path == image_path
    assert media_type == "image/png"
    assert transcoded is False


def test_browser_preview_transcodes_unsupported_mime() -> None:
    image_path = Path("/tmp/unsupported_preview_source.png")
    Image.new("RGB", (10, 6), "#00ff88").save(image_path, format="PNG")

    preview_path, media_type, transcoded = browser_preview_for_image(
        image_path,
        mime_type="image/jp2",
        cache_key="unsupported_preview_test",
    )

    assert preview_path != image_path
    assert preview_path.suffix.lower() == ".png"
    assert preview_path.exists()
    assert media_type == "image/png"
    assert transcoded is True
