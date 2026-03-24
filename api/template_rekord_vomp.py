import re
from decimal import Decimal, InvalidOperation
from typing import Any

from template_common import extract_first_description, normalize_line, normalize_text, page_ref_from_offset, trim_block_lines

POSITION_RE = re.compile(r"(?m)^Pos\.\s*([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:[.,][0-9]+)?)\s+St[üu]ck\b")
RAM_RE = re.compile(r"RAM:\s*([0-9.,]+)\s*mm\s*x\s*([0-9.,]+)\s*mm", flags=re.IGNORECASE)
ARCH_POS_RE = re.compile(r"Arch\.-Pos\.:\s*(.+)", flags=re.IGNORECASE)
TOTAL_LINE_RE = re.compile(
    r"Gesamt\s+[0-9]+(?:[.,][0-9]+)?\s*(?:St[üu]ck|PA|lfm|m²)?\s*:?\s+\(?"
    r"([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\)?",
    flags=re.IGNORECASE,
)
LEADING_DIAGRAM_MARKERS_RE = re.compile(r"^(?:[0-9]+(?:\.[0-9]+)?\s+){1,3}(?=[A-Za-zÄÖÜäöüß])")


def detect(normalized_lower: str) -> bool:
    return (
        "rekord vomp gmbh" in normalized_lower
        and "angebot :" in normalized_lower
        and "belegdatum" in normalized_lower
        and "bauvorhaben" in normalized_lower
    )


def count_positions(text: str) -> int:
    return len(POSITION_RE.findall(text))


def _parse_eu_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = value.replace(".", "").replace(",", ".").replace("(", "").replace(")", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _format_eu_decimal(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    sign = "-" if quantized < 0 else ""
    absolute = abs(quantized)
    whole, frac = f"{absolute:.2f}".split(".")
    whole_grouped = f"{int(whole):,}".replace(",", ".")
    return f"{sign}{whole_grouped},{frac}"


def _extract_total_from_block(block_text: str) -> str | None:
    matches = TOTAL_LINE_RE.findall(block_text)
    if matches:
        return matches[-1]
    return None


def _extract_arch_pos(text_before: str) -> tuple[str | None, bool]:
    lines = [normalize_line(line) for line in text_before.splitlines() if normalize_line(line)]
    arch_pos = None
    is_alternative = False
    for line in reversed(lines[-6:]):
        lower = line.lower()
        if lower.startswith("alternative:"):
            is_alternative = True
            continue
        match = ARCH_POS_RE.search(line)
        if match and arch_pos is None:
            arch_pos = match.group(1).strip()
            if "alternativ" in arch_pos.lower():
                is_alternative = True
    return arch_pos, is_alternative


def _extract_description_short(block_lines: list[str], arch_pos: str | None) -> str | None:
    description = extract_first_description(
        block_lines,
        skip_prefixes=(
            "serie:",
            "beschlag:",
            "ram:",
            "element ",
            "entwässerung:",
            "rahmenbreite:",
            "montagebohrung:",
            "2xspacer",
            "übertrag",
            "gesamt",
            "skizze",
            "bezeichnung",
            "position",
            "alternative:",
            "arch.-pos.:",
        ),
        preferred_words=("kunststoff", "fenster", "balkontüre", "element", "lieferung", "umfang"),
    )
    if description:
        description = LEADING_DIAGRAM_MARKERS_RE.sub("", description).strip()
    if description:
        return description
    return arch_pos


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    matches = list(POSITION_RE.finditer(normalized_text))
    items: list[dict[str, Any]] = []

    for idx, match in enumerate(matches):
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized_text)
        block_text = normalized_text[match.start() : block_end]
        prefix_text = normalized_text[max(0, match.start() - 800) : match.start()]
        arch_pos, is_alternative = _extract_arch_pos(prefix_text)
        block_lines = trim_block_lines(
            block_text.splitlines(),
            (
                "summe der positionen",
                "summe netto",
                "summe brutto",
                "zahlbetrag",
                "hinweise zu unseren preisen",
                "bankverbindung",
                "technische hinweise",
                "20 jahre hersteller-garantie",
            ),
        )
        if not block_lines:
            continue

        position_no = match.group(1)
        quantity_raw = match.group(2)
        block_joined = "\n".join(block_lines)
        width_raw = None
        height_raw = None
        ram_match = RAM_RE.search(block_joined)
        if ram_match:
            width_raw = ram_match.group(1)
            height_raw = ram_match.group(2)

        line_total_raw = _extract_total_from_block(block_joined)
        quantity_value = _parse_eu_decimal(quantity_raw)
        line_total_value = _parse_eu_decimal(line_total_raw)
        unit_price_raw = None
        if quantity_value not in {None, Decimal("0")} and line_total_value is not None:
            unit_price_raw = _format_eu_decimal(line_total_value / quantity_value)

        description_short = _extract_description_short(block_lines[1:], arch_pos)
        description_long = block_joined[:8000]
        if arch_pos and arch_pos not in description_long:
            description_long = f"Arch.-Pos.: {arch_pos}\n{description_long}"[:8000]

        items.append(
            {
                "position_no": position_no,
                "lv_pos": arch_pos,
                "is_alternative": is_alternative,
                "quantity_raw": quantity_raw,
                "unit": "Stück",
                "width_raw": width_raw,
                "height_raw": height_raw,
                "description_short": description_short,
                "description_long": description_long,
                "unit_price_raw": unit_price_raw,
                "line_total_raw": line_total_raw,
                "page_ref": page_ref_from_offset(normalized_text, match.start()),
            }
        )

    return items
