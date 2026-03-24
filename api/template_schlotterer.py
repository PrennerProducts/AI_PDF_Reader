import re
from typing import Any

from template_common import extract_amount_tokens, normalize_line, normalize_text
from template_headers import first_match

AMOUNT_PATTERN = r"[0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2}"
ROW_WITH_AMOUNTS_RE = re.compile(
    rf"^(?P<position>\d+)\s+(?P<body>.+?)\s+(?P<unit_price>{AMOUNT_PATTERN})\s+(?P<line_total>{AMOUNT_PATTERN})$"
)
ROW_NO_AMOUNTS_RE = re.compile(r"^(?P<position>\d+)\s+(?P<body>.+)$")
BODY_RE = re.compile(r"^(?P<customer_pos>.*?)\s*(?P<qty>\d+)\s+(?P<description>[A-Za-zÄÖÜäöüß].+)$")


def detect(normalized_lower: str) -> bool:
    return "schlotterer sonnenschutz systeme gmbh" in normalized_lower and "auftragsbestätigung:" in normalized_lower


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    document_number = headers.get("document_number") or first_match(
        [
            r"Auftragsbestätigung:\s*([0-9]+)",
            r"Auftragsnummer:\s*([0-9]+)",
        ],
        normalized_text,
        flags=re.IGNORECASE,
    )
    document_date = headers.get("document_date") or first_match(
        [
            r"vom:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
            r"vom\s+([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
        ],
        normalized_text,
        flags=re.IGNORECASE,
    )
    project_ref = headers.get("project_ref") or first_match(
        [r"Kommission:\s*([^\n]+)"],
        normalized_text,
        flags=re.IGNORECASE,
    )

    return {
        **headers,
        "document_number": normalize_line(document_number) if document_number else None,
        "document_date": normalize_line(document_date) if document_date else None,
        "project_ref": normalize_line(project_ref) if project_ref else None,
    }


def _parse_row(line: str) -> dict[str, str] | None:
    unit_price_raw = None
    line_total_raw = None
    match = ROW_WITH_AMOUNTS_RE.match(line)
    body = None
    position = None

    if match:
        position = match.group("position")
        body = match.group("body")
        unit_price_raw = normalize_line(match.group("unit_price"))
        line_total_raw = normalize_line(match.group("line_total"))
    else:
        match = ROW_NO_AMOUNTS_RE.match(line)
        if not match:
            return None
        position = match.group("position")
        body = match.group("body")

    body_match = BODY_RE.match(normalize_line(body))
    if not body_match:
        return None

    customer_pos = normalize_line(body_match.group("customer_pos")) or None
    description = normalize_line(body_match.group("description"))
    if not description:
        return None

    return {
        "position": position,
        "customer_pos": customer_pos or "",
        "qty": body_match.group("qty"),
        "description": description,
        "unit_price_raw": unit_price_raw or "",
        "line_total_raw": line_total_raw or "",
    }


def _is_row_start(lines: list[str], idx: int) -> bool:
    if idx >= len(lines):
        return False
    return _parse_row(lines[idx]) is not None


def _extract_dimensions(block_text: str) -> tuple[str | None, str | None]:
    width = first_match(
        [
            r"Breite(?: Panzer)?:\s*([0-9]+)mm",
            r"Breite:\s*([0-9]+)mm",
        ],
        block_text,
        flags=re.IGNORECASE,
    )
    height = first_match(
        [
            r"Höhe(?: Panzer)?:\s*([0-9]+)mm",
            r"Höhe:\s*([0-9]+)mm",
        ],
        block_text,
        flags=re.IGNORECASE,
    )
    return width, height


def _extract_page_items(page_text: str, page_ref: int) -> list[dict[str, Any]]:
    lines = [normalize_line(raw) for raw in page_text.splitlines() if normalize_line(raw)]
    items: list[dict[str, Any]] = []
    idx = 0

    while idx < len(lines):
        parsed_row = _parse_row(lines[idx])
        if parsed_row is None:
            idx += 1
            continue

        end = idx + 1
        while end < len(lines):
            line = lines[end]
            if _is_row_start(lines, end):
                break
            if line.startswith(
                (
                    "Gesamtpreis Positionen",
                    "Rabatte:",
                    "Gesamt Nettosumme",
                    "Zwischensumme",
                    "MwSt",
                    "Gesamtsumme",
                    "Zahlungskonditionen:",
                )
            ):
                break
            end += 1

        block_lines = lines[idx:end]
        block_text = "\n".join(block_lines)
        width_raw, height_raw = _extract_dimensions(block_text)

        unit_price_raw = parsed_row["unit_price_raw"] or None
        line_total_raw = parsed_row["line_total_raw"] or None
        if not unit_price_raw or not line_total_raw:
            amount_tokens = extract_amount_tokens(block_text)
            if len(amount_tokens) >= 2:
                unit_price_raw = unit_price_raw or amount_tokens[-2]
                line_total_raw = line_total_raw or amount_tokens[-1]

        items.append(
            {
                "position_no": parsed_row["position"],
                "lv_pos": parsed_row["customer_pos"] or None,
                "is_alternative": False,
                "quantity_raw": parsed_row["qty"],
                "unit": "Stk",
                "width_raw": width_raw,
                "height_raw": height_raw,
                "description_short": parsed_row["description"],
                "description_long": block_text[:8000],
                "unit_price_raw": unit_price_raw,
                "line_total_raw": line_total_raw,
                "page_ref": page_ref,
            }
        )
        idx = end

    return items


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    items: list[dict[str, Any]] = []
    for page_idx, page_text in enumerate(normalized_text.split("\f"), start=1):
        items.extend(_extract_page_items(page_text, page_idx))
    return items


def count_positions(text: str) -> int:
    return len(extract_line_items(text))
