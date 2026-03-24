import re
from typing import Any

from template_common import normalize_line, normalize_text, page_ref_from_offset, trim_block_lines
from template_headers import first_match

AMOUNT_PATTERN = r"[0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2}"
POSITION_ROW_RE = re.compile(
    r"(?m)^\s*(?P<position>\d+)\s+"
    r"(?P<qty>\d+)Stk\.\s+"
    r"(?P<bandseite>\S+)\s+"
    r"(?P<depth>[0-9]+)mm\s+"
    r"(?P<width>[0-9]+)mm\s+"
    r"(?P<height>[0-9]+)mm\s+"
    r"(?P<lock_variant>\S+)\s+"
    r"(?P<door_type>.+?)\s*$"
)
PRICE_LINE_RE = re.compile(
    rf"^\s*(?P<qty>[0-9]+)\s+(?P<label>.+?)\s+(?:EUR|\u20ac)\s*(?P<unit_price>{AMOUNT_PATTERN})\s+"
    rf"(?:EUR|\u20ac)\s*(?P<line_total>{AMOUNT_PATTERN})\s*$"
)
SUM_LINE_RE = re.compile(
    rf"^\s*Summe\s+(?:EUR|\u20ac)\s*(?P<unit_price>{AMOUNT_PATTERN})\s+(?:EUR|\u20ac)\s*(?P<line_total>{AMOUNT_PATTERN})\s*$",
    flags=re.IGNORECASE,
)
OBJECT_POSITION_RE = re.compile(r"Objektposition:\s*(.+)", flags=re.IGNORECASE)


def detect(normalized_lower: str) -> bool:
    return (
        "koch türen gmbh" in normalized_lower
        and "angebotsnummer:" in normalized_lower
        and "angebotsdatum:" in normalized_lower
        and "objekt:" in normalized_lower
    )


def count_positions(text: str) -> int:
    return len(POSITION_ROW_RE.findall(text))


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    document_number = headers.get("document_number") or first_match(
        [r"Angebotsnummer:\s*([A-Za-z0-9.-]+)"],
        normalized_text,
    )
    document_date = headers.get("document_date") or first_match(
        [r"Angebotsdatum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})"],
        normalized_text,
    )
    project_ref = headers.get("project_ref") or first_match(
        [r"Objekt:\s*([^\n]+)"],
        normalized_text,
    )

    return {
        **headers,
        "document_number": normalize_line(document_number) if document_number else None,
        "document_date": normalize_line(document_date) if document_date else None,
        "project_ref": normalize_line(project_ref) if project_ref else None,
    }


def _extract_object_position(block_lines: list[str]) -> str | None:
    for line in block_lines:
        match = OBJECT_POSITION_RE.search(line)
        if match:
            return normalize_line(match.group(1))
    return None


def _extract_first_price_label(block_lines: list[str]) -> str | None:
    for line in block_lines:
        match = PRICE_LINE_RE.match(normalize_line(line))
        if match:
            return normalize_line(match.group("label"))
    return None


def _extract_sum_prices(block_lines: list[str]) -> tuple[str | None, str | None]:
    for line in reversed(block_lines):
        match = SUM_LINE_RE.match(normalize_line(line))
        if match:
            return match.group("unit_price"), match.group("line_total")
    return None, None


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    matches = list(POSITION_ROW_RE.finditer(normalized_text))
    items: list[dict[str, Any]] = []

    for idx, match in enumerate(matches):
        block_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized_text)
        block_lines = trim_block_lines(
            normalized_text[match.start() : block_end].splitlines(),
            (
                "angebotsnummer:",
                "gesamtpreis ohne mwst",
                "gesamtpreis incl. mwst",
                "gesamtpreis inkl. mwst",
                "preisliste transportkosten",
                "zahlungskonditionen",
                "mit freundlichen grüßen",
            ),
        )
        if not block_lines:
            continue

        object_position = _extract_object_position(block_lines)
        first_price_label = _extract_first_price_label(block_lines)
        unit_price_raw, line_total_raw = _extract_sum_prices(block_lines)
        description_short = first_price_label or object_position or normalize_line(match.group("door_type"))

        items.append(
            {
                "position_no": match.group("position"),
                "lv_pos": object_position,
                "is_alternative": False,
                "quantity_raw": match.group("qty"),
                "unit": "Stk.",
                "width_raw": match.group("width"),
                "height_raw": match.group("height"),
                "description_short": description_short,
                "description_long": "\n".join(normalize_line(line) for line in block_lines if normalize_line(line))[:8000],
                "unit_price_raw": unit_price_raw,
                "line_total_raw": line_total_raw,
                "page_ref": page_ref_from_offset(normalized_text, match.start()),
            }
        )

    return items
