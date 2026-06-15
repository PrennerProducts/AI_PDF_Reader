import re
from typing import Any

from template_common import extract_first_description, normalize_line, normalize_text, page_ref_from_offset, trim_block_lines
from template_headers import first_match

AMOUNT_PATTERN = r"[0-9]{1,3}(?:[. ][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2}"
ROW_RE = re.compile(
    rf"(?m)^\s*(?P<position>[0-9]{{2,3}})\s+"
    rf"(?P<qty>[0-9]+,[0-9]{{2}})\s+"
    rf"(?P<unit>[A-Z]{{2}})\s+"
    rf"(?P<article>\*?\S+)\s+"
    rf"(?P<unit_price>{AMOUNT_PATTERN})\s+"
    rf"(?P<packing_unit>[0-9]+)\s+"
    rf"(?P<line_total>{AMOUNT_PATTERN})\s+"
    rf"(?P<vat>[0-9]+)\s*$"
)
HEADER_PROJECT_RE = re.compile(r"(?m)^\s*Kom\.\s*([^\n]+)\s*$")
SECTION_RE = re.compile(r"(?m)^\s*Kommission:\s*([^\n]+)\s*$", flags=re.IGNORECASE)
DISCOUNT_LABEL_RE = re.compile(r"^(?P<label>.+?)\s+[0-9]+(?:[.,][0-9]+)?-\s*%\s*Rabatt\s*$", flags=re.IGNORECASE)
SECTION_TOTAL_LINE_RE = re.compile(r"^[0-9]{2}\b.+[0-9]{1,3}(?:[. ][0-9]{3})*,[0-9]{2}$")


def detect(normalized_lower: str) -> bool:
    return "schachermayer gmbh" in normalized_lower and (
        "angebots-nr." in normalized_lower or "auftragsnummer" in normalized_lower
    )


def count_positions(text: str) -> int:
    return len(ROW_RE.findall(text))


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    first_page = normalized_text.split("\f", 1)[0]
    document_number = headers.get("document_number") or first_match(
        [
            r"\b([0-9]{8,9})\b\s+[0-9]{2}\.[0-9]{2}\.[0-9]{4}\b",
            r"Angebots-Nr\.\s*([0-9]+)",
            r"Auftragsnummer\s+Datum\s+Seite\s+.*?\b([0-9]{8,9})\b",
        ],
        first_page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    project_ref = headers.get("project_ref") or first_match(
        [
            r"Kom\.\s*([^\n]+)",
            r"(?m)^\s*Kommission:\s*([^\n]+)\s*$",
        ],
        normalized_text,
        flags=re.IGNORECASE,
    )

    return {
        **headers,
        "document_number": normalize_line(document_number) if document_number else None,
        "project_ref": normalize_line(project_ref) if project_ref else None,
    }


def _is_noise_line(line: str) -> bool:
    lower = line.lower()
    if not lower:
        return True
    if lower in {"bezeichnung", "währung eur"}:
        return True
    if lower.startswith("schachermayer gmbh"):
        return True
    if lower.startswith(("4020 linz", "t. +43", "f. +43", "e. ", "www.schachermayer.at")):
        return True
    if lower.startswith(("sch linz", "auftraggeber", "angebot", "angebots-nr.", "auftragsnummer", "ihr zuständiger sachbearbeiter")):
        return True
    if lower.startswith(("tel.:", "fax.:")):
        return True
    if lower.startswith(("herr ", "frau ")):
        return True
    if lower.endswith("@schachermayer.at"):
        return True
    if any(token in lower for token in ("ara-ln:", "uid-nr.", "landesgericht", "dvr ", "eori:", "steuernummer deutschland", "weee-reg.")):
        return True
    if lower.startswith(("sr. schauraum", "archeneo park", "pass-thurn-str.", "6372 ", "6233 ", "österreich")):
        return True
    if lower.startswith(("warenempfänger", "bestellangaben-kunde", "kundennummer", "datum", "seite")):
        return True
    if "währung eur" in lower:
        return True
    if "bezeichnung" in lower and lower.startswith("_"):
        return True
    if "angebots-nr." in lower and "datum" in lower and "seite" in lower:
        return True
    if "preis/me" in lower and "nettobetrag" in lower:
        return True
    return False


def _clean_description_lines(block_lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in block_lines[1:]:
        normalized = normalize_line(line)
        if not normalized or _is_noise_line(normalized):
            continue
        if normalized.lower().startswith("kommission:"):
            continue
        if SECTION_TOTAL_LINE_RE.match(normalized):
            break
        if ROW_RE.match(normalized):
            continue
        if DISCOUNT_LABEL_RE.match(normalized):
            continue
        if cleaned and cleaned[-1].lower() == normalized.lower():
            continue
        cleaned.append(normalized)
    return cleaned


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    matches = list(ROW_RE.finditer(normalized_text))
    items: list[dict[str, Any]] = []
    current_section: str | None = None
    search_cursor = 0

    for idx, match in enumerate(matches):
        between = normalized_text[search_cursor : match.start()]
        header_project_matches = list(HEADER_PROJECT_RE.finditer(between))
        section_matches = list(SECTION_RE.finditer(between))
        if header_project_matches:
            current_section = normalize_line(header_project_matches[-1].group(1))
        if section_matches:
            current_section = normalize_line(section_matches[-1].group(1))

        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized_text)
        block_lines = trim_block_lines(
            normalized_text[match.start() : block_end].splitlines(),
            (
                "summe positionen",
                "mehrwertsteuer",
                "endbetrag",
                "zahlungsbedingungen",
            ),
        )
        search_cursor = match.end()
        if not block_lines:
            continue

        cleaned_lines: list[str] = []
        for line in block_lines:
            normalized = normalize_line(line)
            if not normalized or _is_noise_line(normalized):
                continue
            if normalized.lower().startswith("kommission:"):
                continue
            cleaned_lines.append(normalized)
        description_lines = _clean_description_lines(block_lines)

        description_short = extract_first_description(
            cleaned_lines[1:],
            skip_prefixes=("rabatt",),
            preferred_words=("solido", "kunex", "rosettenlochbohrung", "türschließer", "blindzylinder"),
        )
        if description_short:
            description_short = re.sub(r"\s+[0-9]+(?:[.,][0-9]+)?-\s*%\s+Rabatt$", "", description_short, flags=re.IGNORECASE)
            description_short = normalize_line(description_short)

        items.append(
            {
                "position_no": match.group("position"),
                "lv_pos": current_section,
                "is_alternative": False,
                "quantity_raw": match.group("qty"),
                "unit": match.group("unit"),
                "width_raw": None,
                "height_raw": None,
                "description_short": description_short,
                "description_long": "\n".join(description_lines)[:8000],
                "unit_price_raw": match.group("unit_price"),
                "line_total_raw": match.group("line_total"),
                "page_ref": page_ref_from_offset(normalized_text, match.start()),
            }
        )

    return items
