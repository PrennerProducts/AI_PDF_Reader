import re
from decimal import Decimal, InvalidOperation
from typing import Any

from template_common import extract_amount_tokens, extract_dimensions, extract_first_description, normalize_line, normalize_text, page_ref_from_offset, trim_block_lines
from template_headers import (
    collect_multiline_label_value,
    extract_order_confirmation_number,
    find_nearby_label_value,
    looks_like_document_number,
    looks_like_project_ref,
    normalized_non_empty_lines,
)

def detect(normalized_lower: str) -> bool:
    return (
        "rieder-zillertal.at" in normalized_lower
        or "ku.pos.:" in normalized_lower
        or ("rieder" in normalized_lower and "angebot:" in normalized_lower and "kommission" in normalized_lower)
    )


def count_positions(text: str) -> int:
    return len(re.findall(r"^Position:\s*\d+", text, flags=re.MULTILINE))


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    document_number = headers.get("document_number")
    project_ref = headers.get("project_ref")

    if not looks_like_document_number(document_number):
        document_number = extract_order_confirmation_number(normalized_text)

    if not looks_like_project_ref(project_ref) or (project_ref and project_ref.endswith("+")):
        lines = normalized_non_empty_lines(normalized_text, normalize_line)
        multiline_project_ref = collect_multiline_label_value(lines, "Kommission")
        if not multiline_project_ref:
            multiline_project_ref = find_nearby_label_value(
                lines,
                "Kommission:",
                looks_like_project_ref,
                search_after=6,
                search_before=2,
            )
        if multiline_project_ref:
            project_ref = multiline_project_ref

    return {
        **headers,
        "document_number": document_number,
        "project_ref": project_ref,
    }


def _is_embedded_alternative_line(line: str) -> bool:
    normalized = normalize_line(line).lower()
    return normalized.startswith(("alternativ:", "alternative:", "alternativ ", "alternative "))


def _main_price_lines(block_lines: list[str]) -> list[str]:
    price_lines: list[str] = []
    for line in block_lines:
        if _is_embedded_alternative_line(line):
            break
        price_lines.append(line)
    return price_lines or block_lines


def _extract_prices(
    block_lines: list[str],
    *,
    is_alternative: bool = False,
    description_short: str | None = None,
) -> tuple[str | None, str | None]:
    price_lines = block_lines if is_alternative else _main_price_lines(block_lines)

    for idx, line in enumerate(price_lines):
        if "ep:" in line.lower() or "gp:" in line.lower() or "alternative:" in line.lower():
            start = max(0, idx - 1)
            end = min(len(price_lines), idx + 2)
            snippet = " ".join(price_lines[start:end])
            tokens = extract_amount_tokens(snippet)
            if len(tokens) >= 2:
                return tokens[0], tokens[-1]

    all_tokens = extract_amount_tokens("\n".join(price_lines))
    if len(all_tokens) >= 2:
        return all_tokens[-2], all_tokens[-1]
    if len(all_tokens) == 1:
        return all_tokens[0], all_tokens[0]
    return None, None


def _is_alternative_position(block_lines: list[str]) -> bool:
    leading_lines = [normalize_line(line).lower() for line in block_lines[:3] if normalize_line(line)]
    if any("alternativ für pos" in line for line in leading_lines):
        return True
    if leading_lines and leading_lines[0].startswith("alternativ"):
        return True
    if any("ku.pos.: variante" in line for line in leading_lines):
        return True
    return False


def _parse_eu_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    cleaned = str(value).strip().replace("EUR", "").replace("\u20ac", "").replace(" ", "")
    if not cleaned:
        return None
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _format_eu_decimal(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.01"))
    raw = f"{normalized:.2f}"
    whole, cents = raw.split(".")
    chunks: list[str] = []
    while whole:
        chunks.append(whole[-3:])
        whole = whole[:-3]
    return f"{'.'.join(reversed(chunks))},{cents}"


def _is_delivery_charge_line(line: str) -> bool:
    normalized = normalize_line(line).lower()
    return (
        "baustellenanlieferung" in normalized
        or "frachtkostenbeitrag" in normalized
        or "frachkostenbeitrag" in normalized
        or "frachtkost" in normalized
    )


def _next_numeric_position_no(items: list[dict[str, Any]]) -> str:
    max_position = 0
    for item in items:
        raw = str(item.get("position_no") or "").strip()
        if raw.isdigit():
            max_position = max(max_position, int(raw))
    return str(max_position + 1 if max_position else len(items) + 1)


def extract_delivery_charge_item(text: str, items: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    normalized_text = normalize_text(text)
    lines = [normalize_line(line) for line in normalized_text.splitlines()]
    delivery_lines = [line for line in lines if _is_delivery_charge_line(line)]
    if not delivery_lines:
        return None

    first_amount_sum = Decimal("0.00")
    amount_values: list[Decimal] = []
    amount_raw_by_value: dict[Decimal, str] = {}
    for line in delivery_lines:
        tokens = extract_amount_tokens(line)
        parsed_tokens = [(token, _parse_eu_decimal(token)) for token in tokens]
        parsed_values = [(token, value) for token, value in parsed_tokens if value is not None]
        if not parsed_values:
            continue
        first_amount_sum += parsed_values[0][1]
        for token, value in parsed_values:
            amount_values.append(value)
            amount_raw_by_value[value] = token

    detected_amount = None
    if first_amount_sum > 0:
        for candidate in amount_values:
            if abs(candidate - first_amount_sum) <= Decimal("0.02"):
                detected_amount = candidate
                break
        if detected_amount is None:
            detected_amount = first_amount_sum

    amount = Decimal("200.00")
    amount_raw = _format_eu_decimal(amount)
    first_delivery_line = delivery_lines[0]
    offset = normalized_text.find(first_delivery_line)
    page_ref = page_ref_from_offset(normalized_text, offset if offset >= 0 else len(normalized_text))
    position_no = _next_numeric_position_no(items or [])

    return {
        "position_no": position_no,
        "lv_pos": None,
        "is_alternative": False,
        "quantity_raw": "1",
        "unit": "Pauschale",
        "width_raw": None,
        "height_raw": None,
        "description_short": "Baustellenanlieferung / Frachtkosten",
        "description_long": "\n".join(delivery_lines),
        "unit_price_raw": amount_raw,
        "line_total_raw": amount_raw,
        "page_ref": page_ref,
        "pricing_source": "rieder_delivery_block",
        "manual_price_editable": True,
        "image_required": False,
        "delivery_charge_detected": True,
        "delivery_charge_default_amount": str(amount),
        "delivery_charge_printed_total": str(detected_amount) if detected_amount is not None else None,
        "delivery_charge_fallback": detected_amount is None,
        "delivery_charge_lines": delivery_lines,
    }


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
        is_alternative = _is_alternative_position(block_lines)
        unit_price_raw, line_total_raw = _extract_prices(
            block_lines,
            is_alternative=is_alternative,
            description_short=description_short,
        )

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
