import re
from typing import Any

from template_common import normalize_line, normalize_text, page_ref_from_offset, trim_block_lines
from template_headers import first_match

AMOUNT_PATTERN = r"[0-9]{1,3}(?:[. ][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2}"
POSITION_ROW_RE = re.compile(
    rf"(?m)^\s*(?P<position>(?:[0-9]{{3}}(?:\.[0-9]+)?|[A-Za-z]{{1,3}}[0-9]{{2}}(?:\.[0-9]+)?))\s+"
    rf"(?P<qty>[0-9]+,[0-9]{{2}})\s+(?P<unit>Stk\.)\s+"
    rf"(?P<description>.+?)\s+"
    rf"(?P<unit_price>{AMOUNT_PATTERN})\s+"
    rf"(?P<line_total>\(?(?:{AMOUNT_PATTERN})\)?)\s*$"
)
LV_POS_RE = re.compile(r"LV-Pos:\s*([^\n]+)", flags=re.IGNORECASE)
PLAN_RE = re.compile(r"Plan:\s*([^\n]+)", flags=re.IGNORECASE)
DIMENSION_RE = re.compile(r"(?<![0-9])([0-9]{3,4})\s*x\s*([0-9]{3,4})(?![0-9])")

MONTHS = {
    "januar": 1,
    "februar": 2,
    "maerz": 3,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}


def detect(normalized_lower: str) -> bool:
    if "muigg.at" not in normalized_lower:
        return False
    return "angebot nr." in normalized_lower or "auftragsbestätigung" in normalized_lower


def count_positions(text: str) -> int:
    return len(POSITION_ROW_RE.findall(text))


def _normalize_document_number(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    digits = re.sub(r"\D", "", raw_value)
    return digits or None


def _normalize_date(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    cleaned = normalize_line(raw_value)
    numeric_match = re.fullmatch(r"([0-9]{2})\.([0-9]{2})\.([0-9]{4})", cleaned)
    if numeric_match:
        return cleaned

    textual_match = re.fullmatch(r"([0-9]{1,2})\.\s*([A-Za-zÄÖÜäöüß]+)\s*([0-9]{4})", cleaned)
    if not textual_match:
        return None

    month = MONTHS.get(textual_match.group(2).lower())
    if month is None:
        return None
    day = int(textual_match.group(1))
    year = int(textual_match.group(3))
    return f"{day:02d}.{month:02d}.{year:04d}"


def _clean_amount(raw_value: str) -> str:
    return raw_value.strip().strip("()").strip()


def _extract_dimensions(text: str) -> tuple[str | None, str | None]:
    match = DIMENSION_RE.search(text)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _extract_lv_pos(block_text: str) -> str | None:
    for pattern in (LV_POS_RE, PLAN_RE):
        match = pattern.search(block_text)
        if match:
            return normalize_line(match.group(1))
    return None


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    document_number = headers.get("document_number") or _normalize_document_number(
        first_match(
            [
                r"ANGEBOT\s+Nr\.\s*([0-9 .]+)",
                r"AUFTRAGSBESTÄTIGUNG\s+([0-9 .]+)",
            ],
            normalized_text,
            flags=re.IGNORECASE,
        )
    )
    document_date = headers.get("document_date") or _normalize_date(
        first_match(
            [
                r"Datum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
                r"Datum:\s*([0-9]{1,2}\.\s*[A-Za-zÄÖÜäöüß]+\s*[0-9]{4})",
            ],
            normalized_text,
            flags=re.IGNORECASE,
        )
    )
    project_ref = headers.get("project_ref") or first_match([r"(?m)^\s*(BV[^\n]+)\s*$"], normalized_text)

    return {
        **headers,
        "document_number": document_number,
        "document_date": document_date,
        "project_ref": normalize_line(project_ref) if project_ref else None,
    }


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    matches = list(POSITION_ROW_RE.finditer(normalized_text))
    items: list[dict[str, Any]] = []

    for idx, match in enumerate(matches):
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized_text)
        block_lines = trim_block_lines(
            normalized_text[match.start() : block_end].splitlines(),
            (
                "zwischensumme:",
                "gesamtbetrag netto",
                "zzgl.",
                "gesamtbetrag",
                "zahlbar innerhalb",
                "unsere angebotenen preise",
            ),
        )
        if not block_lines:
            continue

        block_text = "\n".join(block_lines)
        description_short = normalize_line(match.group("description"))
        width_raw, height_raw = _extract_dimensions(description_short)
        is_alternative = "(" in match.group("line_total") and ")" in match.group("line_total")

        items.append(
            {
                "position_no": match.group("position").upper(),
                "lv_pos": _extract_lv_pos(block_text),
                "is_alternative": is_alternative,
                "quantity_raw": match.group("qty"),
                "unit": match.group("unit"),
                "width_raw": width_raw,
                "height_raw": height_raw,
                "description_short": description_short,
                "description_long": "\n".join(normalize_line(line) for line in block_lines if normalize_line(line))[:8000],
                "unit_price_raw": _clean_amount(match.group("unit_price")),
                "line_total_raw": _clean_amount(match.group("line_total")),
                "page_ref": page_ref_from_offset(normalized_text, match.start()),
            }
        )

    return items
