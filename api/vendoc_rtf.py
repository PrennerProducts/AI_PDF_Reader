from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image


TWIPS_PER_PIXEL = 15
HIMETRIC_PER_INCH = 2540
DEFAULT_DPI = 96
DEFAULT_MAX_IMAGE_WIDTH_TWIPS = 6600


def _rtf_unicode(value: int) -> str:
    if value > 32767:
        value -= 65536
    return f"\\u{value}?"


def escape_rtf_text(text: str) -> str:
    parts: list[str] = []
    for char in text:
        if char == "\\":
            parts.append("\\\\")
        elif char == "{":
            parts.append("\\{")
        elif char == "}":
            parts.append("\\}")
        elif char == "\n":
            parts.append("\\line ")
        elif char == "\r":
            continue
        else:
            codepoint = ord(char)
            if 32 <= codepoint <= 126:
                parts.append(char)
            else:
                parts.append(_rtf_unicode(codepoint))
    return "".join(parts)


def _normalize_png(image_bytes: bytes) -> tuple[bytes, int, int]:
    with Image.open(BytesIO(image_bytes)) as image:
        width, height = image.size
        output = BytesIO()
        if image.format == "PNG":
            image.save(output, format="PNG")
        else:
            image.convert("RGBA").save(output, format="PNG")
    return output.getvalue(), width, height


def _image_dimensions_for_rtf(width: int, height: int, *, max_width_twips: int) -> dict[str, int]:
    picw = max(1, round(width * HIMETRIC_PER_INCH / DEFAULT_DPI))
    pich = max(1, round(height * HIMETRIC_PER_INCH / DEFAULT_DPI))
    goal_width = max(1, width * TWIPS_PER_PIXEL)
    goal_height = max(1, height * TWIPS_PER_PIXEL)
    if goal_width > max_width_twips:
        scale = max_width_twips / goal_width
        goal_width = max_width_twips
        goal_height = max(1, round(goal_height * scale))
    return {
        "picw": picw,
        "pich": pich,
        "picwgoal": round(goal_width),
        "pichgoal": round(goal_height),
    }


def _rtf_picture_block(
    image_bytes: bytes,
    *,
    image_name: str | None = None,
    max_width_twips: int = DEFAULT_MAX_IMAGE_WIDTH_TWIPS,
) -> str:
    png_bytes, width, height = _normalize_png(image_bytes)
    dimensions = _image_dimensions_for_rtf(width, height, max_width_twips=max_width_twips)
    name_block = ""
    if image_name:
        safe_name = escape_rtf_text(image_name)
        name_block = f"{{\\*\\picprop{{\\sp{{\\sn wzName}}{{\\sv {safe_name}}}}}}}"
    return (
        "{\\pict"
        f"{name_block}\\pngblip"
        f"\\picw{dimensions['picw']}\\pich{dimensions['pich']}"
        f"\\picwgoal{dimensions['picwgoal']}\\pichgoal{dimensions['pichgoal']}"
        "\\picscalex100\\picscaley100 "
        f"{png_bytes.hex()}"
        "}"
    )


def build_vendoc_long_text_rtf(
    description_long: Any,
    *,
    image_bytes: bytes | None = None,
    image_name: str | None = None,
    max_image_width_twips: int = DEFAULT_MAX_IMAGE_WIDTH_TWIPS,
) -> str:
    text = "" if description_long is None else str(description_long).strip()
    body_parts: list[str] = []
    if text:
        body_parts.append(escape_rtf_text(text))
    if image_bytes:
        if body_parts:
            body_parts.append("\\par ")
        body_parts.append(
            _rtf_picture_block(
                image_bytes,
                image_name=image_name,
                max_width_twips=max_image_width_twips,
            )
        )
    body = "".join(body_parts)
    return (
        "{\\rtf1\\ansi\\deff0"
        "{\\fonttbl{\\f0 Calibri;}}"
        "\\viewkind4\\uc1\\pard\\f0\\fs18 "
        f"{body}"
        "\\par}"
    )
