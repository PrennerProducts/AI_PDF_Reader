import re
from typing import Any

from template_common import extract_amount_tokens, extract_dimensions, extract_first_description, extract_lv_pos, normalize_line, normalize_text, trim_block_lines
from template_headers import first_match

PRICE_PAIR_RE = re.compile(
    r"([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2})\s+(?:EUR|\u20ac)?\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2})"
)
PRICE_WITH_DISCOUNT_RE = re.compile(
    r"([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2})\s+[0-9]{1,2},[0-9]{2}\s*%\s+([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2})"
)
ROW_START_RE = re.compile(r"^\d{3}\s+[0-9]+,[0-9]{2,4}\s+\w+")
HEADER_RE = re.compile(r"^(\d{3})\s+([0-9]+,[0-9]{2,4})\s+([A-Za-z]+)\s+(.+)$")


def detect(normalized_lower: str) -> bool:
    return (
        "newo-sachbearbeiter" in normalized_lower
        or ("angebotsnummer:" in normalized_lower and "newo" in normalized_lower)
        or ("auftrag nr." in normalized_lower and "newo" in normalized_lower and "belegdatum:" in normalized_lower)
    )


def count_positions(text: str) -> int:
    return len(re.findall(r"^\s*\d{3}\s+\d+,\d{2,4}\s+\w+", text, flags=re.MULTILINE))


def _strip_overlay_noise(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = normalize_line(value)
    cleaned = re.sub(r"\s+(?:Pla|Bit|lös)(?:\s+(?:Pla|Bit|lös))*\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned or None


def _clean_header_description(value: str) -> str:
    cleaned = normalize_line(value)
    cleaned = re.sub(r"\s+[0-9]{1,2}\s*%\s*$", "", cleaned).strip()
    newo_idx = cleaned.find("NeWo ")
    if newo_idx > 0:
        cleaned = cleaned[newo_idx:].strip()
    return cleaned


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    document_number = headers.get("document_number") or first_match(
        [
            r"Angebotsnummer:\s*([A-Za-z0-9.-]+)",
            r"AUFTRAG\s+Nr\.\s*([A-Za-z0-9.-]+)",
        ],
        normalized_text,
        flags=re.IGNORECASE,
    )
    document_date = headers.get("document_date") or first_match(
        [
            r"Belegdatum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
        ],
        normalized_text,
        flags=re.IGNORECASE,
    )
    project_ref = headers.get("project_ref") or first_match(
        [
            r"Kommission:\s*([^\n]+)",
        ],
        normalized_text,
        flags=re.IGNORECASE,
    )

    return {
        **headers,
        "document_number": _strip_overlay_noise(document_number),
        "document_date": _strip_overlay_noise(document_date),
        "project_ref": _strip_overlay_noise(project_ref),
    }


def _extract_page_items(lines: list[str], page_ref: int | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    start_indices: list[int] = []

    for idx, line in enumerate(lines):
        if ROW_START_RE.match(normalize_line(line)):
            start_indices.append(idx)

    for offset, start in enumerate(start_indices):
        end = start_indices[offset + 1] if offset + 1 < len(start_indices) else len(lines)
        raw_block = lines[start:end]
        block_lines = trim_block_lines(
            raw_block,
            (
                "zwischensumme",
                "gesamtsumme",
                "angebotssumme",
                "lieferkondition:",
                "zahlungskondition:",
                "mit sonnigen gru",
            ),
        )
        if not block_lines:
            continue

        header = block_lines[0]
        header_match = HEADER_RE.match(header)
        if not header_match:
            continue

        position_no = header_match.group(1)
        quantity_raw = header_match.group(2)
        unit = header_match.group(3)
        header_tail = header_match.group(4).strip()
        full_block = "\n".join(block_lines)
        width_raw, height_raw = extract_dimensions(full_block)
        lv_pos = extract_lv_pos(header_tail) or extract_lv_pos(full_block)
        is_alternative = "alternativ" in full_block.lower()

        unit_price_raw = None
        line_total_raw = None
        price_pair = PRICE_WITH_DISCOUNT_RE.search(header) or PRICE_PAIR_RE.search(header)
        if price_pair:
            unit_price_raw = price_pair.group(1)
            line_total_raw = price_pair.group(2)
            header_tail = price_pair.re.sub("", header_tail).strip(" :")
        else:
            for line in block_lines[1:16]:
                price_match = PRICE_WITH_DISCOUNT_RE.search(line) or PRICE_PAIR_RE.search(line)
                if price_match:
                    unit_price_raw = price_match.group(1)
                    line_total_raw = price_match.group(2)
                    break

        description_short = _clean_header_description(header_tail)
        if re.match(r"^[0-9]{2}\.[0-9]{2}\.[0-9]{2}\.[A-Z]$", description_short):
            description_short = ""
        if (
            not description_short
            or description_short.endswith(":")
            or len(description_short) < 5
            or not description_short.startswith("NeWo")
        ):
            description_short = extract_first_description(
                block_lines[1:24],
                skip_prefixes=(
                    "elementbreite:",
                    "modell:",
                    "lamellentyp:",
                    "lamellenfarbe:",
                    "teilung:",
                    "teilbreite",
                    "teilh",
                    "angebotnummer:",
                    "angebotsnummer:",
                ),
                preferred_words=("raffstore", "insektenschutz", "schiebeplissee", "putzkasten"),
            )

        items.append(
            {
                "position_no": position_no,
                "lv_pos": lv_pos,
                "is_alternative": is_alternative,
                "quantity_raw": quantity_raw,
                "unit": unit,
                "width_raw": width_raw,
                "height_raw": height_raw,
                "description_short": description_short,
                "description_long": full_block[:8000],
                "unit_price_raw": unit_price_raw,
                "line_total_raw": line_total_raw,
                "page_ref": page_ref,
            }
        )

    return items


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    items: list[dict[str, Any]] = []
    for page_idx, page_text in enumerate(normalized_text.split("\f"), start=1):
        page_lines = [line for line in page_text.splitlines() if line.strip()]
        items.extend(_extract_page_items(page_lines, page_ref=page_idx))
    return items
