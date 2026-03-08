import re
from decimal import Decimal, InvalidOperation
from typing import Any

SPACE_CHARS_RE = re.compile(r"[\u00a0\u2007\u202f]")
MULTI_SPACE_RE = re.compile(r"[ \t]+")
AMOUNT_TOKEN_RE = re.compile(
    r"-?\s*(?:EUR|\u20ac)?\s*[0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|-?\s*(?:EUR|\u20ac)?\s*[0-9]+,[0-9]{2}"
)


def _first_match(patterns: list[str], text: str, flags: int = 0) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
    return None


def _normalize_text(text: str) -> str:
    return SPACE_CHARS_RE.sub(" ", text.replace("\r", ""))


def _normalize_line(text: str) -> str:
    return MULTI_SPACE_RE.sub(" ", _normalize_text(text)).strip()


def _extract_amount_tokens(text: str) -> list[str]:
    normalized = _normalize_text(text)
    return [MULTI_SPACE_RE.sub(" ", token).strip() for token in AMOUNT_TOKEN_RE.findall(normalized)]


def _parse_eu_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = value.upper().replace("EUR", "").replace("\u20ac", "")
    cleaned = cleaned.replace("−", "-").replace("–", "-")
    cleaned = re.sub(r"[^0-9,.\-]", "", cleaned)
    if not cleaned or cleaned in {"-", "--"}:
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
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


def _find_labeled_amount(lines: list[str], labels: tuple[str, ...], *, pick: str = "first") -> str | None:
    for idx, line in enumerate(lines):
        lower = line.lower()
        if not any(label in lower for label in labels):
            continue

        direct_tokens = _extract_amount_tokens(line)
        if direct_tokens:
            return direct_tokens[-1]

        lookahead_tokens: list[str] = []
        for step in range(1, 8):
            if idx + step >= len(lines):
                break
            probe = lines[idx + step]
            if not probe:
                continue
            if step > 1 and any(label in probe.lower() for label in labels) and lookahead_tokens:
                break
            lookahead_tokens.extend(_extract_amount_tokens(probe))

        if lookahead_tokens:
            if pick == "last":
                return lookahead_tokens[-1]
            return lookahead_tokens[0]
    return None


def detect_template(text: str) -> str:
    normalized = _normalize_text(text).lower()
    if "newo-sachbearbeiter" in normalized or ("angebotsnummer:" in normalized and "newo" in normalized):
        return "newo"
    if "entholzer" in normalized or "angebot n" in normalized:
        return "entholzer"
    if "rieder-zillertal.at" in normalized or "ku.pos.:" in normalized:
        return "rieder"
    if "angebot:" in normalized and "kommission" in normalized:
        return "rieder"
    return "generic"


def _extract_totals(text: str) -> dict[str, str | None]:
    lines = [_normalize_line(line) for line in text.splitlines()]
    net_total = _find_labeled_amount(lines, ("nettosumme",), pick="first")
    vat_total = _find_labeled_amount(lines, ("mehrwertsteuer",), pick="first")
    gross_total = _find_labeled_amount(lines, ("angebotssumme", "gesamtsumme"), pick="last")

    net_dec = _parse_eu_decimal(net_total)
    vat_dec = _parse_eu_decimal(vat_total)
    gross_dec = _parse_eu_decimal(gross_total)

    if net_dec is not None and gross_dec is not None:
        implied_vat = (gross_dec - net_dec).quantize(Decimal("0.01"))
        if vat_dec is None or abs(vat_dec - implied_vat) > Decimal("0.05"):
            vat_total = _format_eu_decimal(implied_vat)

    if gross_dec is None and net_dec is not None and vat_dec is not None:
        gross_total = _format_eu_decimal((net_dec + vat_dec).quantize(Decimal("0.01")))
    if net_dec is None and gross_dec is not None and vat_dec is not None:
        net_total = _format_eu_decimal((gross_dec - vat_dec).quantize(Decimal("0.01")))

    return {"net_total": net_total, "vat_total": vat_total, "gross_total": gross_total}


def _count_positions(template: str, text: str) -> int:
    if template == "rieder":
        return len(re.findall(r"^Position:\s*\d+", text, flags=re.MULTILINE))
    if template == "entholzer":
        return len(re.findall(r"^Pos\.:", text, flags=re.MULTILINE))
    if template == "newo":
        return len(re.findall(r"^\s*\d{3}\s+\d+,\d{2}\s+\w+", text, flags=re.MULTILINE))
    return len(re.findall(r"^Pos", text, flags=re.MULTILINE))


def parse_document_text(text: str) -> dict[str, Any]:
    normalized_text = _normalize_text(text)
    template = detect_template(text)
    document_number = _first_match(
        [
            r"Angebot:\s*([0-9]+)",
            r"Angebot\s+([0-9]+\.[0-9]+)",
            r"Angebot N[^:]*:\s*([0-9]+\.[0-9]+)",
            r"Angebotsnummer:\s*([0-9]+)",
        ],
        normalized_text,
    )
    document_date = _first_match(
        [
            r"Belegdatum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
            r"Datum\s*:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
            r"Ried,\s+am\s+([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
            r"\b([0-9]{2}\.[0-9]{2}\.[0-9]{4})\b",
        ],
        normalized_text,
    )
    project_ref = _first_match(
        [
            r"Kommission:\s*(.+)",
            r"Kommission\s*:\s*(.+)",
            r'Bauvorhaben\s*"([^"]+)"',
        ],
        normalized_text,
    )
    currency = "EUR" if ("\u20ac" in normalized_text or "EUR" in normalized_text.upper()) else None
    totals = _extract_totals(normalized_text)

    return {
        "template": template,
        "document_number": document_number,
        "document_date": document_date,
        "project_ref": project_ref,
        "currency": currency,
        "position_count": _count_positions(template, normalized_text),
        "totals": totals,
        "notes": [
            "Initial parser skeleton for supplier template detection and core field extraction.",
            "Next step: replace regex-only extraction with template-specific line-item parsers.",
        ],
    }
