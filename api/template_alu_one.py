import re
from typing import Any

from template_common import extract_first_description, normalize_line, normalize_text, page_ref_from_offset, trim_block_lines
from template_headers import (
    find_nearby_label_value,
    looks_like_document_date,
    looks_like_document_number,
    looks_like_project_ref,
    normalized_non_empty_lines,
)

AMOUNT_PATTERN = r"[0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2}"
ITEM_HEADER_RE = re.compile(
    rf"^\s*(?P<position>\d{{3}}[A-Za-z]?)\s+"
    rf"(?P<qty>[0-9]+(?:[.,][0-9]+)?)\s+"
    rf"(?P<unit>Stk|Stück|LFM|lfm)\s+"
    rf"(?P<label>.+?)"
    rf"(?:\s+(?:EUR|\u20ac)\s*(?P<unit_price>{AMOUNT_PATTERN}))?"
    rf"(?:\s+(?:EUR|\u20ac)\s*(?P<line_total>{AMOUNT_PATTERN}))?\s*$",
    flags=re.MULTILINE,
)
DIMENSION_RE = re.compile(r"\b([0-9]{3,4})\s*mm\s*x\s*([0-9]{3,4})\s*mm\b", flags=re.IGNORECASE)
LV_RE = re.compile(r"\b([0-9]{2}\.[0-9]{2}\.[0-9]{2}\s*[A-Za-z])\b")


def detect(normalized_lower: str) -> bool:
    return (
        "alu-one metallbaupartner gmbh" in normalized_lower
        and "angebot" in normalized_lower
        and "nummer:" in normalized_lower
        and "kommission:" in normalized_lower
    )


def count_positions(text: str) -> int:
    return len(ITEM_HEADER_RE.findall(text))


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    lines = normalized_non_empty_lines(normalized_text, normalize_line)
    document_number = headers.get("document_number")
    document_date = headers.get("document_date")
    project_ref = headers.get("project_ref")

    if not looks_like_document_number(document_number):
        document_number = find_nearby_label_value(lines, "Nummer:", looks_like_document_number)

    if not looks_like_document_date(document_date):
        document_date = find_nearby_label_value(lines, "Druckdatum:", looks_like_document_date)

    if not looks_like_project_ref(project_ref):
        project_ref = find_nearby_label_value(lines, "Kommission:", looks_like_project_ref)

    return {
        **headers,
        "document_number": document_number,
        "document_date": document_date,
        "project_ref": project_ref,
    }


def _extract_dimensions(text: str) -> tuple[str | None, str | None]:
    match = DIMENSION_RE.search(text)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _extract_lv_pos(*parts: str) -> str | None:
    for part in parts:
        match = LV_RE.search(part)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


def _quantity_is_one(quantity_raw: str | None) -> bool:
    if not quantity_raw:
        return False
    return quantity_raw.replace(".", "").replace(",", ".").strip() == "1.00"


def _recent_non_empty_lines(text: str) -> list[str]:
    return [normalize_line(line) for line in text.splitlines() if normalize_line(line)]


def _description_needs_fallback(label: str) -> bool:
    clean = normalize_line(label)
    if not clean:
        return True
    if re.fullmatch(r"[0-9]{2}\.[0-9]{2}\.[0-9]{2}\s*[A-Za-z]", clean):
        return True
    return len(clean) < 8


def _extract_description_short(header_label: str, body_lines: list[str]) -> str | None:
    clean_header = normalize_line(header_label)
    if clean_header and not _description_needs_fallback(clean_header):
        return clean_header

    fallback = extract_first_description(
        body_lines,
        skip_prefixes=(
            "alternativ:",
            "pos ",
            "system:",
            "wärmedurchgangskoeffizient",
            "oberflächen:",
            "profile:",
            "rahmen:",
            "sprosse:",
            "türflügel:",
            "türbeschreibung:",
            "bodenabschluss:",
            "zusatzteile pro element:",
            "zusatzbeschläge pro element:",
            "füllung:",
            "angebot ",
        ),
        preferred_words=(
            "türelement",
            "türelemente",
            "einflg. tür",
            "zweiflg. tür",
            "aufpreis",
            "aufzahlung",
            "vorbemerkungen",
            "info ",
        ),
    )
    return fallback or clean_header or None


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    matches = list(ITEM_HEADER_RE.finditer(normalized_text))
    items: list[dict[str, Any]] = []

    for idx, match in enumerate(matches):
        position_no = match.group("position")
        quantity_raw = match.group("qty")
        unit = match.group("unit")
        header_label = normalize_line(match.group("label"))
        unit_price_raw = match.group("unit_price")
        line_total_raw = match.group("line_total") or (unit_price_raw if _quantity_is_one(quantity_raw) else None)

        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized_text)
        body_lines = trim_block_lines(
            normalized_text[match.end() : block_end].splitlines(),
            (
                "alternativ:",
                "nettowert",
                "bruttobetrag",
                "nach erhalt der rechnung",
                "mit freundlichen grüßen",
            ),
        )
        description_short = _extract_description_short(header_label, body_lines)
        width_raw, height_raw = _extract_dimensions(header_label)
        if width_raw is None or height_raw is None:
            width_raw, height_raw = _extract_dimensions("\n".join(body_lines[:8]))

        recent_lines = _recent_non_empty_lines(normalized_text[max(0, match.start() - 300) : match.start()])
        is_alternative = any(line.lower().startswith("alternativ:") for line in recent_lines[-3:])
        header_line = normalize_line(match.group(0))
        full_block_lines = [header_line, *body_lines]

        items.append(
            {
                "position_no": position_no,
                "lv_pos": _extract_lv_pos(header_label, "\n".join(body_lines[:6])),
                "is_alternative": is_alternative,
                "quantity_raw": quantity_raw,
                "unit": unit,
                "width_raw": width_raw,
                "height_raw": height_raw,
                "description_short": description_short,
                "description_long": "\n".join(full_block_lines)[:8000],
                "unit_price_raw": unit_price_raw,
                "line_total_raw": line_total_raw,
                "page_ref": page_ref_from_offset(normalized_text, match.start()),
            }
        )

    return items
