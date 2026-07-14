import re
from decimal import Decimal, InvalidOperation
from typing import Any

from template_common import extract_first_description, normalize_line, normalize_text, page_ref_from_offset, trim_block_lines
from template_headers import (
    first_match,
    looks_like_document_number,
    looks_like_project_ref,
    looks_like_rekord_project_part,
    normalized_non_empty_lines,
)

POSITION_RE = re.compile(r"(?m)^Pos\.\s*([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:[.,][0-9]+)?)\s+St[üu]ck(?:\b|(?=[A-ZÄÖÜ]))")
RAM_RE = re.compile(r"RAM:\s*([0-9.,]+)\s*mm\s*x\s*([0-9.,]+)\s*mm", flags=re.IGNORECASE)
COMPACT_RAM_RE = re.compile(
    r"RAM:\s*(?:Element)?\s*([0-9]{3,5}(?:,[0-9]+)?)"
    r"(?:\s*mm)?[^0-9\n]{0,80}?x\s*([0-9]{3,5}(?:,[0-9]+)?)"
    r"(?:\s*mm|[^0-9\n]{0,60}?mm)",
    flags=re.IGNORECASE,
)
STOCKLICHTE_RAM_RE = re.compile(
    r"([0-9]{3,5}(?:,[0-9]+)?)\s+Stocklichte\s*RAM:\s*([0-9]{3,5}(?:,[0-9]+)?)",
    flags=re.IGNORECASE,
)
ARCH_POS_RE = re.compile(r"Arch\.-Pos\.:\s*(.+)", flags=re.IGNORECASE)
TOTAL_LINE_RE = re.compile(
    r"Gesamt\s+[0-9]+(?:[.,][0-9]+)?\s*(?:St[üu]ck|PA|lfm|m²)?\s*:?\s+\(?"
    r"([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\)?",
    flags=re.IGNORECASE,
)
AMOUNT_RE = r"[0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2}"
# WICHTIG: die AMOUNT-Alternative MUSS geklammert sein. Ohne die Gruppe teilt das
# innere "|" das gesamte Muster: der erste Zweig ist dann NICHT an $ verankert und
# matcht die 3-stellige Menge mitten in der Zeile ("\u2026Dekor 9,500 m 450,87" wird zu
# "\u2026Dekor0 m" \u2014 Menge zerstoert). Mit (?:\u2026) wird nur der Preis am Zeilenende (auch
# in Klammern, z.B. "(214,82)") entfernt und die Menge "9,500 m" bleibt erhalten.
TRAILING_PRICE_RE = re.compile(
    rf"\s+\(?(?:EUR|\u20ac)?\s*(?:{AMOUNT_RE})\s*(?:EUR|\u20ac)?\)?$",
    flags=re.IGNORECASE,
)
QUANTITY_ONLY_RE = re.compile(r"^[0-9]+(?:[.,][0-9]+)?\s*(?:St[üu]ck|Stk\.?|PA|lfm|m²|m)?$", flags=re.IGNORECASE)
LEADING_DESCRIPTOR_RE = re.compile(
    r"(?i)\b(?:\d+tlg\.|kunststoff|element|fenster|balkontüre|hebeschiebetür|nebentüre|türe|serie:|beschlag:|ram:|xx-|summ-)"
)
STRUCTURE_MARKER_RE = re.compile(
    r"(?<!\n)(Alternative:|Arch\.-Pos\.:|Pos\.\s*[0-9]+(?:\.[0-9]+)?\s+[0-9]+(?:[.,][0-9]+)?\s+St[üu]ck|Summe der Positionen)",
    flags=re.IGNORECASE,
)
# Zusaetzlich zieht PyMuPDF Skizzenmasse (links) in die Textspalte. Zwei sicher
# signierte Faelle werden entfernt, ohne Mengen/Specs zu treffen:
#  B) Fuehrende Skizzenmasse, z.B. "4400 Rahmenbreite: …", "1171,2 2068,8 …".
#     Nur Zahlen mit >=3 Vorkomma-Stellen; "0.5 W/m2k …" bleibt geschuetzt.
#  C) Nachgestellte Skizzenmasse, z.B. "…Sch. A 2550 2750". Signatur: ein Lauf
#     von >=2 nackten 3-4-stelligen Zahlen (ohne Einheit) am Zeilenende. Ueber
#     alle Positionen des Korpus trifft das ausschliesslich Bleed-Zeilen, nie
#     legitime Werte. Ein EINZELNES nachgestelltes Zahlwort wird bewusst NICHT
#     entfernt (zu risikoreich). Mittiges Bleed ("… 88 2500 2750 Serie:") bleibt.
LEADING_DIMENSION_BLEED_RE = re.compile(r"^(?:[0-9]{3,}(?:[.,][0-9]+)?\s+)+")
TRAILING_DIMENSION_PAIR_RE = re.compile(r"(?:\s+[0-9]{3,4}){2,}$")


def detect(normalized_lower: str) -> bool:
    return (
        "rekord vomp gmbh" in normalized_lower
        and ("angebot :" in normalized_lower or "angebot:" in normalized_lower)
        and "belegdatum" in normalized_lower
        and "bauvorhaben" in normalized_lower
    )


def count_positions(text: str) -> int:
    return len(POSITION_RE.findall(text))


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    lines = normalized_non_empty_lines(normalized_text, normalize_line)
    document_number = headers.get("document_number")
    project_ref = headers.get("project_ref")

    if not looks_like_document_number(document_number):
        document_number = first_match(
            [
                r"Angebot\s*:\s*([A-Z]{2,6}[0-9]{4,}(?:[A-Z]{1,3}(?![a-z]))?)",
                r"(?mi)^\s*Angebot\s*:\s*([A-Za-z0-9.-]+)\s*$",
                r"Angebot\s*:\s*([A-Za-z0-9.-]+)",
            ],
            normalized_text,
        )

    if not looks_like_project_ref(project_ref):
        for idx, line in enumerate(lines):
            if "bauvorhaben:" not in line.lower():
                continue
            inline_value = line.split(":", 1)[1].strip() if ":" in line else ""
            if looks_like_project_ref(inline_value):
                project_ref = inline_value
                break
            collected: list[str] = []
            for step in range(1, 5):
                probe_idx = idx + step
                if probe_idx >= len(lines):
                    break
                probe = lines[probe_idx]
                if not looks_like_rekord_project_part(probe):
                    break
                collected.append(probe)
            if collected:
                project_ref = " ".join(collected)
                break

    return {
        **headers,
        "document_number": document_number,
        "project_ref": project_ref,
    }


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


def _extract_ram_dimensions(block_text: str) -> tuple[str | None, str | None]:
    match = RAM_RE.search(block_text)
    if match:
        return match.group(1), match.group(2)

    # PyMuPDF sometimes interleaves Rekord sketch labels with the RAM line, e.g.
    # "RAM:Element1000außenmmRALx 2300laut mmKollektion".
    match = COMPACT_RAM_RE.search(block_text)
    if match:
        return match.group(1), match.group(2)

    # Door positions can merge "Stocklichte Höhe" into the RAM line. The rendered
    # height still appears immediately before the merged "StocklichteRAM" token.
    match = STOCKLICHTE_RAM_RE.search(block_text)
    if match:
        return match.group(2), match.group(1)

    return None, None


def _prepare_compact_text(text: str) -> str:
    normalized = normalize_text(text)
    prepared = STRUCTURE_MARKER_RE.sub(r"\n\1", normalized)
    prepared = re.sub(r"(Gesamt\s+[0-9]+(?:[.,][0-9]+)?\s*(?:St[üu]ck|PA|lfm|m²)?)(?=[0-9(])", r"\1 ", prepared)
    prepared = re.sub(r"([0-9]{2}\.[0-9]{2}\.[0-9]{4})Seite", r"\1\nSeite", prepared)
    return prepared


def _page_bounds_for_offset(text: str, offset: int) -> tuple[int, int]:
    page_start = text.rfind("\f", 0, max(0, offset)) + 1
    page_end = text.find("\f", max(0, offset))
    if page_end < 0:
        page_end = len(text)
    return page_start, page_end


def _page_line_top_ratio(text: str, offset: int) -> float | None:
    page_start, page_end = _page_bounds_for_offset(text, offset)
    if page_end <= page_start:
        return None
    page_text = text[page_start:page_end]
    relative_offset = max(0, min(offset, page_end) - page_start)
    line_count = max(1, page_text.count("\n") + 1)
    line_index = page_text[:relative_offset].count("\n")
    return min(0.98, max(0.02, line_index / line_count))


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
        preferred_words=("hebeschiebetür", "kunststoff", "fenster", "balkontüre", "nebentüre", "element", "lieferung", "umfang"),
    )
    if description:
        description = _strip_leading_diagram_markers(description)
    if description:
        return description
    return arch_pos


def _strip_leading_diagram_markers(line: str) -> str:
    normalized = normalize_line(line)
    match = LEADING_DESCRIPTOR_RE.search(normalized)
    if match and match.start() > 0:
        prefix = normalized[: match.start()]
        if re.fullmatch(r"[\d\s.,/]+", prefix):
            return normalized[match.start() :].strip()
    return normalized


def _clean_description_line(line: str) -> str | None:
    normalized = normalize_line(line)
    if not normalized:
        return None
    lower = normalized.lower()
    if POSITION_RE.match(normalized):
        return None
    if lower.startswith(("arch.-pos.:", "alternative:", "übertrag", "(zu pos")):
        return None
    if lower in {"position stück menge preis", "skizze bezeichnung - € -", "skizze bezeichnung - eur -"}:
        return None
    if "skizze" in lower and "bezeichnung" in lower:
        return None
    if lower.startswith("gesamt ") or TOTAL_LINE_RE.search(normalized):
        return None

    cleaned = _strip_leading_diagram_markers(normalized)
    cleaned = LEADING_DIMENSION_BLEED_RE.sub("", cleaned)
    cleaned = TRAILING_PRICE_RE.sub("", cleaned)
    cleaned = TRAILING_DIMENSION_PAIR_RE.sub("", cleaned).strip()
    if not re.search(r"[A-Za-zÄÖÜäöüß]", cleaned):
        return None
    if not cleaned or QUANTITY_ONLY_RE.fullmatch(cleaned):
        return None
    return cleaned


def _clean_description_lines(block_lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in block_lines:
        normalized = _clean_description_line(line)
        if not normalized:
            continue
        if cleaned and cleaned[-1].lower() == normalized.lower():
            continue
        cleaned.append(normalized)
    return cleaned


# Summary/service positions (Arch.-Pos. Umfang/Lieferung) render as a two-column
# "<CODE>   <description>" line: the article code sits left, the description
# right, separated by a wide column gap.
_SUMMARY_CODE_LINE_RE = re.compile(r"^\s*([A-Z0-9]{2,}(?:-[A-Z0-9]+)+)\s{3,}(\S.*?)\s*$")
# Measurement value on its own line, e.g. "138,020 lfm" (the position total the
# generic cleaning strips as a leading dimension). Kept verbatim for these
# positions.
_SUMMARY_MEASURE_RE = re.compile(r"^[0-9][0-9.,]*\s*(?:lfm|m²|m2|m)$", re.IGNORECASE)


def _summary_position_texts(block_lines: list[str]) -> tuple[str, str] | None:
    """Article-code Kurztext + Langtext for Rekord summary/service positions.

    The generic cleaning glues the code into the short text, drops the
    "(zu Pos.: ...)" reference and strips the number off the measurement value.
    Here the code becomes the Kurztext and the description, the reference and the
    value form the Langtext verbatim. Returns None when the block is not a
    two-column code position.
    """
    code = None
    description = None
    code_index = None
    for index, raw_line in enumerate(block_lines):
        match = _SUMMARY_CODE_LINE_RE.match(raw_line)
        if match:
            code = match.group(1)
            description = normalize_line(match.group(2))
            code_index = index
            break
    if code is None:
        return None

    detail_lines: list[str] = []
    for raw_line in block_lines[code_index + 1 :]:
        line = normalize_line(raw_line)
        if not line:
            continue
        if line.lower().startswith("(zu pos") and re.search(r"\d", line):
            detail_lines.append(line)
        elif _SUMMARY_MEASURE_RE.match(line):
            detail_lines.append(line)

    long_parts = [part for part in [description] if part]
    if detail_lines:
        long_parts.append("")  # blank line separates description from reference/value
        long_parts.extend(detail_lines)
    return code, "\n".join(long_parts)


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = _prepare_compact_text(text)
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
        page_ref = page_ref_from_offset(normalized_text, match.start())
        page_end_ref = page_ref_from_offset(normalized_text, max(match.start(), block_end - 1))
        item_top_ratio = _page_line_top_ratio(normalized_text, match.start())
        next_position_page_ref = None
        next_position_top_ratio = None
        if idx + 1 < len(matches):
            next_match = matches[idx + 1]
            next_position_page_ref = page_ref_from_offset(normalized_text, next_match.start())
            next_position_top_ratio = _page_line_top_ratio(normalized_text, next_match.start())
        block_joined = "\n".join(block_lines)
        width_raw, height_raw = _extract_ram_dimensions(block_joined)

        line_total_raw = _extract_total_from_block(block_joined)
        quantity_value = _parse_eu_decimal(quantity_raw)
        line_total_value = _parse_eu_decimal(line_total_raw)
        unit_price_raw = None
        if quantity_value not in {None, Decimal("0")} and line_total_value is not None:
            unit_price_raw = _format_eu_decimal(line_total_value / quantity_value)

        description_lines = _clean_description_lines(block_lines)
        description_short = _extract_description_short(description_lines, arch_pos)
        description_long = "\n".join(description_lines)[:8000]
        if arch_pos and not is_alternative:
            # Use the raw (un-normalised) lines: the two-column code/description
            # split relies on the wide gap that trim_block_lines collapses.
            summary_texts = _summary_position_texts(block_text.splitlines())
            if summary_texts is not None:
                summary_code, summary_long = summary_texts
                description_short = summary_code
                description_long = summary_long[:8000]

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
                "page_ref": page_ref,
                "page_end_ref": page_end_ref,
                "spans_page_break": page_end_ref > page_ref,
                "item_top_ratio": item_top_ratio,
                "next_position_page_ref": next_position_page_ref,
                "next_position_top_ratio": next_position_top_ratio,
            }
        )

    return items
