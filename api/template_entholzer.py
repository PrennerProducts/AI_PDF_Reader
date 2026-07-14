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
EMPTY_PRICE_HEADER_RE = re.compile(r"\s*\bEP\s*:\s*GP\s*:\s*$", flags=re.IGNORECASE)

# Drawing dimensions bleed in from the sketch column in front of real
# description lines (e.g. "1750 Alu - Schale …", "875 875 FLG 74 mm"). These
# leading dimensions are >=3-digit integers; legitimate leading numbers are 1-2
# digit counts/quantities ("2 flügeliges Fenster", "3 Dichtungsebenen",
# "2 x Entwässerung", "1 Stk. …") and are kept.
_LEADING_DRAWING_DIM_RE = re.compile(r"^(?:\d{3,}\s+)+")


def _strip_leading_drawing_dimensions(line: str) -> str:
    """Strip a leading run of >=3-digit integer tokens (drawing dimensions)."""
    return _LEADING_DRAWING_DIM_RE.sub("", line)


def _page_bounds_for_offset(text: str, offset: int) -> tuple[int, int]:
    page_start = text.rfind("\f", 0, max(0, offset)) + 1
    page_end = text.find("\f", max(0, offset))
    if page_end < 0:
        page_end = len(text)
    return page_start, page_end


def _page_line_top_ratio(text: str, offset: int) -> float | None:
    """Vertical position of ``offset`` within its page, 0.0 (top) .. 1.0 (bottom).

    Derived from the line index inside the page block. Used to give the image
    matcher a vertical window per position so that two positions sharing a page
    (each with its own sketch) get their own image instead of relying on the
    weak aspect-ratio tie-breaker, which can swap near-square sketches.
    """
    page_start, page_end = _page_bounds_for_offset(text, offset)
    if page_end <= page_start:
        return None
    page_text = text[page_start:page_end]
    relative_offset = max(0, min(offset, page_end) - page_start)
    line_count = max(1, page_text.count("\n") + 1)
    line_index = page_text[:relative_offset].count("\n")
    return min(0.98, max(0.02, line_index / line_count))


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


def _clean_description_lines(block_lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in block_lines:
        normalized = normalize_line(line)
        if not normalized:
            continue
        if normalized.lower() == "(symbolfoto)":
            continue
        normalized = _strip_leading_drawing_dimensions(normalized)
        if not normalized:
            continue
        normalized = EMPTY_PRICE_HEADER_RE.sub("", normalized).strip()
        price_remainder = PRICE_PAIR_RE.sub("", normalized)
        price_remainder = re.sub(r"\b(?:EP|GP)\s*:", "", price_remainder, flags=re.IGNORECASE)
        price_remainder = re.sub(r"(?:EUR|\u20ac)", "", price_remainder, flags=re.IGNORECASE).strip(" :,-")
        if not price_remainder:
            continue
        if normalized:
            cleaned.append(normalized)
    return cleaned


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    items: list[dict[str, Any]] = []
    matches = list(re.finditer(r"(?ms)^Pos\.\:\s*(\d+)(.*?)(?=^Pos\.\:\s*\d+|\Z)", normalized_text))
    for idx, match in enumerate(matches):
        page_ref = page_ref_from_offset(normalized_text, match.start())
        position_no = match.group(1)
        block = match.group(2).strip()
        if not block:
            continue

        item_top_ratio = _page_line_top_ratio(normalized_text, match.start())
        next_position_page_ref = None
        next_position_top_ratio = None
        if idx + 1 < len(matches):
            next_match = matches[idx + 1]
            next_position_page_ref = page_ref_from_offset(normalized_text, next_match.start())
            next_position_top_ratio = _page_line_top_ratio(normalized_text, next_match.start())

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
        description_lines = _clean_description_lines(block_lines)
        if not description_lines:
            continue

        block_text = "\n".join(description_lines)
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
            description_lines,
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
                "item_top_ratio": item_top_ratio,
                "next_position_page_ref": next_position_page_ref,
                "next_position_top_ratio": next_position_top_ratio,
            }
        )

    return items
