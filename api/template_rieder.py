import re
from typing import Any

from template_common import extract_amount_tokens, extract_dimensions, extract_first_description, normalize_text, trim_block_lines, page_ref_from_offset


def detect(normalized_lower: str) -> bool:
    return (
        "rieder-zillertal.at" in normalized_lower
        or "ku.pos.:" in normalized_lower
        or ("angebot:" in normalized_lower and "kommission" in normalized_lower)
    )


def count_positions(text: str) -> int:
    return len(re.findall(r"^Position:\s*\d+", text, flags=re.MULTILINE))


def _extract_prices(block_lines: list[str]) -> tuple[str | None, str | None]:
    for idx, line in enumerate(block_lines):
        if "ep:" in line.lower() or "gp:" in line.lower() or "alternative:" in line.lower():
            start = max(0, idx - 1)
            end = min(len(block_lines), idx + 2)
            snippet = " ".join(block_lines[start:end])
            tokens = extract_amount_tokens(snippet)
            if len(tokens) >= 2:
                return tokens[0], tokens[-1]

    all_tokens = extract_amount_tokens("\n".join(block_lines))
    if len(all_tokens) >= 2:
        return all_tokens[-2], all_tokens[-1]
    if len(all_tokens) == 1:
        return all_tokens[0], all_tokens[0]
    return None, None


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    items: list[dict[str, Any]] = []
    for match in re.finditer(r"(?ms)^Position:\s*(\d+)(.*?)(?=^Position:\s*\d+|\Z)", normalized_text):
        page_ref = page_ref_from_offset(normalized_text, match.start())
        position_no = match.group(1)
        block = match.group(2).strip()
        if not block:
            continue

        block_lines = trim_block_lines(
            block.splitlines(),
            (
                "summe ",
                "zwischensumme",
                "nettosumme",
                "angebotssumme",
                "gesamtsumme",
            ),
        )
        if not block_lines:
            continue

        block_text = "\n".join(block_lines)
        qty_match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(St[ue\u00fc]ck|Stk\.?|Stk)\b", block_text, flags=re.IGNORECASE)
        quantity_raw = qty_match.group(1) if qty_match else None
        unit = qty_match.group(2).replace(".", "") if qty_match else None

        width_raw, height_raw = extract_dimensions(block_text)
        description_short = extract_first_description(
            block_lines,
            skip_prefixes=("ku.pos", "ep:", "gp:", "flgnr", "summe", "zwischensumme"),
            preferred_words=("fenster", "tuer", "t\u00fcre", "fixfenster", "brandschutz", "schema", "dreh", "kipp"),
        )
        unit_price_raw, line_total_raw = _extract_prices(block_lines)
        is_alternative = "alternativ" in block_text.lower() or "alternative" in block_text.lower()

        items.append(
            {
                "position_no": position_no,
                "lv_pos": None,
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
