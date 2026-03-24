import re
from typing import Any

from template_common import extract_amount_tokens, extract_dimensions, extract_first_description, normalize_line, normalize_text, page_ref_from_offset, trim_block_lines
from template_headers import (
    collect_multiline_label_value,
    extract_order_confirmation_number,
    looks_like_document_number,
    looks_like_project_ref,
    normalized_non_empty_lines,
)

LV_RE = re.compile(r"LV-Pos:\s*([0-9A-Za-z .\-/]+)", flags=re.IGNORECASE)
PRICE_PAIR_RE = re.compile(
    r"([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\s*(?:EUR|\u20ac)?\s+"
    r"([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\s*(?:EUR|\u20ac)?"
)


def detect(normalized_lower: str) -> bool:
    return "entholzer" in normalized_lower or "angebot n" in normalized_lower


def count_positions(text: str) -> int:
    return len(re.findall(r"^Pos\.:", text, flags=re.MULTILINE))


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    document_number = headers.get("document_number")
    project_ref = headers.get("project_ref")

    if not looks_like_document_number(document_number):
        document_number = extract_order_confirmation_number(normalized_text)

    if not looks_like_project_ref(project_ref):
        project_ref = collect_multiline_label_value(normalized_non_empty_lines(normalized_text, normalize_line), "Kommission")

    return {
        **headers,
        "document_number": document_number,
        "project_ref": project_ref,
    }


def _extract_prices(block_lines: list[str]) -> tuple[str | None, str | None]:
    pair: tuple[str | None, str | None] = (None, None)
    for line in block_lines:
        match = PRICE_PAIR_RE.search(line)
        if match:
            pair = (match.group(1), match.group(2))
    if pair[0] and pair[1]:
        return pair

    all_tokens = extract_amount_tokens("\n".join(block_lines))
    if len(all_tokens) >= 2:
        return all_tokens[-2], all_tokens[-1]
    return None, None


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    items: list[dict[str, Any]] = []
    for match in re.finditer(r"(?ms)^Pos\.\:\s*(\d+)(.*?)(?=^Pos\.\:\s*\d+|\Z)", normalized_text):
        page_ref = page_ref_from_offset(normalized_text, match.start())
        position_no = match.group(1)
        block = match.group(2).strip()
        if not block:
            continue

        block_lines = trim_block_lines(
            block.splitlines(),
            (
                "summe ohne montagekosten",
                "zwischensumme",
                "nettosumme",
                "angebotssumme",
                "zahlungsbedingungen:",
            ),
        )
        if not block_lines:
            continue

        block_text = "\n".join(block_lines)
        qty_match = re.search(
            r"([0-9]+(?:[.,][0-9]+)?)\s*(Stk\.?|Stk|St[ue\u00fc]ck|LFM|lfm)\b",
            block_text,
            flags=re.IGNORECASE,
        )
        quantity_raw = qty_match.group(1) if qty_match else None
        unit = qty_match.group(2).replace(".", "") if qty_match else None
        width_raw, height_raw = extract_dimensions(block_text)

        lv_pos_match = LV_RE.search(block_text)
        lv_pos = lv_pos_match.group(1).strip() if lv_pos_match else None
        is_alternative = "alternativ" in block_text.lower()

        description_short = extract_first_description(
            block_lines,
            skip_prefixes=(
                "lv-pos:",
                "ep:",
                "gp:",
                "(innenansicht)",
                "angebot n",
            ),
            preferred_words=("aluclip", "festverglasung", "balkont", "dreh-kipp", "kopplungselement"),
        )
        unit_price_raw, line_total_raw = _extract_prices(block_lines)

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
                "description_long": block_text[:8000],
                "unit_price_raw": unit_price_raw,
                "line_total_raw": line_total_raw,
                "page_ref": page_ref,
            }
        )

    return items
