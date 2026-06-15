import re
from typing import Any

from template_common import extract_amount_tokens, normalize_line, normalize_text
from template_headers import first_match

AMOUNT_PATTERN = r"[0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2}"
TRAILING_AMOUNT_RE = re.compile(rf"(?:^|\s)(?:EUR\s*)?{AMOUNT_PATTERN}\s*$", flags=re.IGNORECASE)
PRICING_COMPONENT_RE = re.compile(rf"^(?P<label>.+?)\s+(?P<amount>{AMOUNT_PATTERN})$")
ROW_WITH_AMOUNTS_RE = re.compile(
    rf"^(?P<position>\d+)\s+(?P<body>.+?)\s+(?P<unit_price>{AMOUNT_PATTERN})\s+(?P<line_total>{AMOUNT_PATTERN})$"
)
ROW_WITH_LINE_TOTAL_RE = re.compile(
    rf"^(?P<position>\d+)\s+(?P<body>.+?)\s+(?P<line_total>{AMOUNT_PATTERN})$"
)
ROW_NO_AMOUNTS_RE = re.compile(r"^(?P<position>\d+)\s+(?P<body>.+)$")
BODY_RE = re.compile(r"^(?:(?P<customer_pos>.+?)\s+)?(?P<qty>\d+)\s+(?P<description>[A-Za-zÄÖÜäöüß].+)$")


def detect(normalized_lower: str) -> bool:
    if "schlotterer sonnenschutz systeme gmbh" not in normalized_lower:
        return False
    return any(
        marker in normalized_lower
        for marker in (
            "auftragsbestätigung:",
            "angebot:",
            "angebotsnummer",
            "gesamt nettosumme",
        )
    )


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    document_number = headers.get("document_number") or first_match(
        [
            r"Angebot:\s*([A-Za-z0-9./-]+)",
            r"Angebotsnummer:\s*([A-Za-z0-9./-]+)",
            r"Auftragsbestätigung:\s*([0-9]+)",
            r"Auftragsnummer:\s*([0-9]+)",
        ],
        normalized_text,
        flags=re.IGNORECASE,
    )
    document_date = headers.get("document_date") or first_match(
        [
            r"Angebot:\s*[A-Za-z0-9./-]+\s+vom:?\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
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
        match = ROW_WITH_LINE_TOTAL_RE.match(line)
        if match:
            position = match.group("position")
            body = match.group("body")
            line_total_raw = normalize_line(match.group("line_total"))
            unit_price_raw = line_total_raw

    if not match:
        match = ROW_NO_AMOUNTS_RE.match(line)
        if not match:
            return None
        position = match.group("position")
        body = match.group("body")

    body_match = BODY_RE.match(normalize_line(body))
    if not body_match:
        return None

    customer_pos_raw = body_match.group("customer_pos")
    customer_pos = normalize_line(customer_pos_raw) if customer_pos_raw else None
    if customer_pos and "," in customer_pos:
        return None
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


def _is_noise_line(line: str) -> bool:
    lower = line.lower()
    if not lower:
        return True
    if lower.startswith(
        (
            "geschäftsführung:",
            "geschaeftsfuehrung:",
            "di peter gubisch",
            "wolfgang neutatz",
            "angebot:",
            "auftragsbestätigung:",
            "auftragsbestaetigung:",
            "auftragsnummer:",
            "pos-nr.",
            "zahlungskonditionen:",
            "gesamtpreis positionen",
            "gesamt nettosumme",
            "rabatte:",
            "zwischensumme",
            "mwst",
            "gesamtsumme",
            "summe:",
        )
    ):
        return True
    if any(
        token in lower
        for token in (
            "wert/stück",
            "wert gesamt",
            "landesgericht",
            "fn212294",
            "uid-nr.",
            "uid-nr",
            "www.schlotterer",
            "office@schlotterer",
            "schlotterer sonnenschutz systeme gmbh",
            "5421 adnet, seefeldmühle",
            "5421 adnet, seefeldmuehle",
        )
    ):
        return True
    return False


def _clean_description_lines(block_lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    in_price_breakdown = False
    for raw_line in block_lines[1:]:
        line = normalize_line(raw_line)
        if not line or _is_noise_line(line):
            continue
        if _parse_row(line) is not None:
            continue
        lower = line.lower()
        if lower.startswith("grundpreis:"):
            in_price_breakdown = True
            continue
        if in_price_breakdown:
            continue
        if lower == "alternative":
            continue
        if lower.startswith("alternative"):
            line = normalize_line(re.sub(r"^Alternative\s*", "", line, flags=re.IGNORECASE))
            if not line:
                continue
        if line == "-":
            continue
        if line.startswith("-") and TRAILING_AMOUNT_RE.search(line):
            continue
        if cleaned and cleaned[-1].lower() == line.lower():
            continue
        cleaned.append(line)
    return cleaned


def _extract_pricing_components(block_lines: list[str]) -> list[dict[str, str]]:
    components: list[dict[str, str]] = []
    for raw_line in block_lines[1:]:
        line = normalize_line(raw_line)
        if not line or _is_noise_line(line):
            continue
        if _parse_row(line) is not None:
            continue
        if line == "-":
            continue
        match = PRICING_COMPONENT_RE.match(line)
        if not match:
            continue
        label = normalize_line(match.group("label"))
        label = re.sub(r"^-\s*", "", label).strip()
        if not label or not re.search(r"[A-Za-zÄÖÜäöüß]", label):
            continue
        components.append(
            {
                "label": label,
                "amount_raw": normalize_line(match.group("amount")),
            }
        )
    return components


def _is_alternative_block(block_lines: list[str]) -> bool:
    return any(normalize_line(line).lower().startswith("alternative") for line in block_lines[1:])


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
        description_lines = _clean_description_lines(block_lines)
        pricing_components = _extract_pricing_components(block_lines)
        is_alternative = _is_alternative_block(block_lines)

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
                "is_alternative": is_alternative,
                "quantity_raw": parsed_row["qty"],
                "unit": "Stk",
                "width_raw": width_raw,
                "height_raw": height_raw,
                "description_short": parsed_row["description"],
                "description_long": "\n".join(description_lines)[:8000],
                "unit_price_raw": unit_price_raw,
                "line_total_raw": line_total_raw,
                "page_ref": page_ref,
                "image_required": False,
                "image_auto_match_allowed": False,
                "alternative_append_at_end": is_alternative,
                "schlotterer_pricing_components": pricing_components,
            }
        )
        idx = end

    return items


def _extract_leading_pricing_components(page_text: str) -> list[dict[str, str]]:
    lines = [normalize_line(raw) for raw in page_text.splitlines() if normalize_line(raw)]
    leading_lines: list[str] = []
    for idx, line in enumerate(lines):
        if _is_row_start(lines, idx):
            break
        leading_lines.append(line)
    return _extract_pricing_components(["", *leading_lines])


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    items: list[dict[str, Any]] = []
    for page_idx, page_text in enumerate(normalized_text.split("\f"), start=1):
        leading_components = _extract_leading_pricing_components(page_text)
        if leading_components and items:
            items[-1].setdefault("schlotterer_pricing_components", []).extend(leading_components)
        items.extend(_extract_page_items(page_text, page_idx))
    return items


def count_positions(text: str) -> int:
    return len(extract_line_items(text))
