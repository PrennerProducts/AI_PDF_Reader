import re
from typing import Any

from template_common import extract_amount_tokens, normalize_line, normalize_text, trim_block_lines

LINE_ITEM_HEADER_RE = re.compile(
    r"^\s*(?P<label>.+?)\s+(?P<qty>[0-9]+(?:[.,][0-9]+)?)\s+(?P<unit>[A-Za-zÄÖÜäöü()]+)\s+"
    r"(?P<unit_price>[0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\s*(?:EUR|\u20ac)?\s+"
    r"(?P<line_total>[0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\s*(?:EUR|\u20ac)?\s*$"
)


def detect(normalized_lower: str) -> bool:
    return (
        "sr. schauraum gmbh" in normalized_lower
        and "projekt ki-pdf-reader" in normalized_lower
        and "beschreibung" in normalized_lower
        and "menge" in normalized_lower
        and "betrag" in normalized_lower
    )


def count_positions(text: str) -> int:
    return len(re.findall(r"^\s*(?:MODUL\s+\d+|OPTIONAL:)", text, flags=re.MULTILINE | re.IGNORECASE))


def _is_short_continuation(line: str) -> bool:
    clean = normalize_line(line)
    if not clean or len(clean) > 40:
        return False
    if clean.startswith("-") or ":" in clean or extract_amount_tokens(clean):
        return False
    letters = re.sub(r"[^A-Za-zÄÖÜ]", "", clean)
    return bool(letters) and letters == letters.upper()


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    items: list[dict[str, Any]] = []
    position_counter = 0

    for page_idx, page_text in enumerate(normalized_text.split("\f"), start=1):
        raw_lines = page_text.splitlines()
        start_indices = [
            idx
            for idx, raw_line in enumerate(raw_lines)
            if LINE_ITEM_HEADER_RE.match(normalize_line(raw_line))
        ]

        for offset, start in enumerate(start_indices):
            end = start_indices[offset + 1] if offset + 1 < len(start_indices) else len(raw_lines)
            block_lines = trim_block_lines(
                raw_lines[start:end],
                (
                    "zwischensumme",
                    "gesamt eur",
                    "datenschutz",
                    "projektabgrenzung",
                    "zahlungsbedingungen",
                    "sollte im zuge der umsetzung",
                ),
            )
            if not block_lines:
                continue

            header_line = block_lines[0]
            header_match = LINE_ITEM_HEADER_RE.match(header_line)
            if not header_match:
                continue

            position_counter += 1
            label = header_match.group("label").strip()
            short_parts = [label]
            body_start_index = 1
            while body_start_index < len(block_lines) and _is_short_continuation(block_lines[body_start_index]):
                short_parts.append(normalize_line(block_lines[body_start_index]))
                body_start_index += 1

            items.append(
                {
                    "position_no": str(position_counter),
                    "lv_pos": None,
                    "is_alternative": label.lower().startswith("optional:"),
                    "quantity_raw": header_match.group("qty"),
                    "unit": header_match.group("unit"),
                    "width_raw": None,
                    "height_raw": None,
                    "description_short": " ".join(short_parts),
                    "description_long": "\n".join(block_lines)[:8000],
                    "unit_price_raw": header_match.group("unit_price"),
                    "line_total_raw": header_match.group("line_total"),
                    "page_ref": page_idx,
                }
            )

    return items
