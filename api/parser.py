import re
from decimal import Decimal, InvalidOperation
from typing import Any

from template_common import extract_amount_tokens as _extract_amount_tokens
from template_common import normalize_line as _normalize_line
from template_common import normalize_text as _normalize_text
from template_registry import count_positions as _count_positions
from template_registry import detect_template as _detect_template
from template_registry import refine_headers_for_template
from template_registry import supplier_name_for_template
from template_headers import collapse_header_value as _collapse_header_value
from template_headers import first_match as _first_match


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


def _currency_prefix(*values: str | None) -> str:
    for value in values:
        if not value:
            continue
        stripped = value.strip()
        if stripped.startswith("\u20ac"):
            return "\u20ac "
        if stripped.upper().startswith("EUR"):
            return "EUR "
    return ""


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


def _extract_amount_via_inline_pattern(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _detect_document_type(normalized_text: str, template: str) -> str:
    first_page = normalized_text.split("\f", 1)[0]
    head_text = "\n".join(first_page.splitlines()[:80])
    head_lower = head_text.lower()

    if re.search(r"(?mi)^\s*auftragsbest[aä]tigung\b", head_text):
        return "auftragsbestaetigung"
    if re.search(r"(?mi)^\s*auftragsnummer\s*:", head_text):
        return "auftragsbestaetigung"
    if re.search(r"(?mi)^\s*auftrag\b(?:\s*:)?\s*[A-Za-z0-9.-]+\b", head_text):
        return "auftragsbestaetigung"
    if re.search(r"(?mi)^\s*angebot(?:\s*:|\b)", head_text) or "angebotsnummer" in head_lower:
        return "angebot"

    lower = normalized_text.lower()
    if re.search(r"(?mi)\bauftragsbest[aä]tigung\s*:", normalized_text):
        return "auftragsbestaetigung"
    if re.search(r"(?mi)^\s*angebot(?:\s*:|\b)", normalized_text) or "angebotsnummer" in lower:
        return "angebot"
    return "angebot"


def _clean_reference_value(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = _collapse_header_value(value)
    if collapsed is None:
        return None
    cleaned = collapsed.strip(" \t\r\n,;:.")
    return cleaned or None


def _extract_offer_reference(normalized_text: str, document_type: str) -> str | None:
    if document_type != "auftragsbestaetigung":
        return None
    return _clean_reference_value(
        _first_match(
            [
                r"(?mi)^\s*Kommission:\s*[^\n]*?\bzu\s+([A-Za-z0-9.+/\- ]+?)\s*$",
                r"(?mi)^\s*Projekt:\s*[^\n]*?\bzu\s+([A-Za-z0-9.+/\- ]+?)\s*$",
                r"(?mi)\bzu\s+Angebot(?:snummer)?\s*:?\s*([A-Za-z0-9.+/\- ]+)\b",
                r"(?mi)\bAngebotsreferenz\s*:?\s*([A-Za-z0-9.+/\- ]+)\b",
                r"(?mi)\bReferenzangebot\s*:?\s*([A-Za-z0-9.+/\- ]+)\b",
                r"(?mi)\bbezugnehmend auf Angebot\s*:?\s*([A-Za-z0-9.+/\- ]+)\b",
            ],
            normalized_text,
        )
    )


def _extract_offer_reference_from_project_ref(project_ref: str | None) -> str | None:
    if not project_ref:
        return None
    return _clean_reference_value(
        _first_match(
            [
                r"\bzu\s+([A-Za-z0-9.+/\-]+(?:\s*\+\s*[A-Za-z0-9.+/\-]+)*)\b",
            ],
            project_ref,
            flags=re.IGNORECASE,
        )
    )


def detect_template(text: str) -> str:
    return _detect_template(text)


def _extract_totals(text: str) -> dict[str, str | None]:
    lines = [_normalize_line(line) for line in text.splitlines()]
    net_total = _extract_amount_via_inline_pattern(
        text,
        (
            r"Gesamtbetrag netto\s*(?:EUR|\u20ac)?\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Gesamt Nettosumme\s*(?:EUR|\u20ac)?\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Summe Netto\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Nettosumme\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        ),
    )
    if net_total is None:
        net_total = _find_labeled_amount(
            lines,
            ("gesamt nettosumme", "gesamtbetrag netto", "nettosumme"),
            pick="first",
        )
    if net_total is None:
        net_total = _find_labeled_amount(lines, ("zwischensumme ohne ust", "zwischensumme", "nettowert", "summe netto"), pick="last")
    if net_total is None:
        net_total = _find_labeled_amount(
            lines,
            ("summe positionen", "gesamtpreis positionen", "gesamtpreis ohne mwst"),
            pick="first",
        )
    vat_total = _extract_amount_via_inline_pattern(
        text,
        (
            r"zuzüglich\s*[0-9., ]*%\s*(?:MwSt|Mwst|Mehrwertsteuer|USt\.)\s*(?:EUR|\u20ac)?\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"(?:MwSt|Mehrwertsteuer|USt\.)\s*[0-9., ]*%\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"(?:MwSt|Mwst|Mehrwertsteuer|USt\.)\s*[0-9., ]*%\s*(?:EUR|\u20ac)?\s*[+-]?\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        ),
    )
    if vat_total is None:
        vat_total = _find_labeled_amount(lines, ("zuzüglich", "mwst", "mehrwertsteuer", "ust."), pick="first")
    gross_total = _extract_amount_via_inline_pattern(
        text,
        (
            r"Endbetrag\s*(?:EUR|\u20ac)?\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Gesamtbetrag(?!\s*netto)\s*(?:EUR|\u20ac)?\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Gesamtpreis incl\. Mwst\.\s*(?:EUR|\u20ac)?\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Gesamtpreis inkl\. Mwst\.\s*(?:EUR|\u20ac)?\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Summe Brutto\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Gesamt EUR\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Bruttobetrag\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        ),
    )
    if gross_total is None:
        gross_total = _find_labeled_amount(lines, ("endbetrag", "gesamtbetrag", "gesamtpreis incl. mwst", "gesamtpreis inkl. mwst", "angebotssumme", "gesamtsumme", "gesamt eur", "bruttobetrag", "summe brutto"), pick="last")

    net_dec = _parse_eu_decimal(net_total)
    vat_dec = _parse_eu_decimal(vat_total)
    gross_dec = _parse_eu_decimal(gross_total)
    currency_prefix = _currency_prefix(net_total, vat_total, gross_total)

    if currency_prefix:
        if net_total and not net_total.strip().startswith(("\u20ac", "EUR")):
            net_total = f"{currency_prefix}{net_total.strip()}"
        if vat_total and not vat_total.strip().startswith(("\u20ac", "EUR")):
            vat_total = f"{currency_prefix}{vat_total.strip()}"
        if gross_total and not gross_total.strip().startswith(("\u20ac", "EUR")):
            gross_total = f"{currency_prefix}{gross_total.strip()}"

    if net_dec is not None and gross_dec is not None:
        implied_vat = (gross_dec - net_dec).quantize(Decimal("0.01"))
        if vat_dec is None or abs(vat_dec - implied_vat) > Decimal("0.05"):
            vat_total = f"{currency_prefix}{_format_eu_decimal(implied_vat)}"

    if gross_dec is None and net_dec is not None and vat_dec is not None:
        gross_total = f"{currency_prefix}{_format_eu_decimal((net_dec + vat_dec).quantize(Decimal('0.01')))}"
    if net_dec is None and gross_dec is not None and vat_dec is not None:
        net_total = f"{currency_prefix}{_format_eu_decimal((gross_dec - vat_dec).quantize(Decimal('0.01')))}"

    return {"net_total": net_total, "vat_total": vat_total, "gross_total": gross_total}


def parse_document_text(text: str) -> dict[str, Any]:
    normalized_text = _normalize_text(text)
    template = detect_template(text)
    document_type = _detect_document_type(normalized_text, template)
    headers = refine_headers_for_template(
        template,
        normalized_text,
        {
            "document_number": _collapse_header_value(
                _first_match(
                    [
                        r"(?mi)^\s*Angebot\s*:\s*([A-Za-z0-9.-]+)\s*$",
                        r"(?m)^\s*Nummer:\s*([A-Za-z0-9.-]+)\s*$",
                        r"(?mi)^\s*Angebotsnummer\s*:?\s*([A-Za-z0-9.-]*\d[A-Za-z0-9.-]*)\s*$",
                        r"(?mi)^\s*Angebot:\s*([0-9]+)\s*$",
                        r"(?mi)^\s*Angebot\s+([0-9]+\.[0-9]+)\s*$",
                        r"(?mi)^\s*Angebot N[^:]*:\s*([0-9]+\.[0-9]+)\s*$",
                        r"(?mi)^\s*Angebotsnummer:\s*([0-9]+)\s*$",
                    ],
                    normalized_text,
                )
            ),
            "document_date": _first_match(
                [
                    r"(?m)^\s*Druckdatum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
                    r"Belegdatum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
                    r"Datum\s*:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
                    r"Ried,\s+am\s+([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
                    r"\b([0-9]{2}\.[0-9]{2}\.[0-9]{4})\b",
                ],
                normalized_text,
            ),
            "project_ref": _collapse_header_value(
                _first_match(
                    [
                        r"Kommission:\s*([^\n]+)",
                        r"Kommission\s*:\s*([^\n]+)",
                        r'Bauvorhaben\s*"([^"]+)"',
                        r"(?m)^Projekt\s+(.+)$",
                    ],
                    normalized_text,
                )
            ),
        },
    )
    document_number = headers.get("document_number")
    document_date = headers.get("document_date")
    project_ref = headers.get("project_ref")
    offer_reference = _extract_offer_reference(normalized_text, document_type)
    if offer_reference is None:
        offer_reference = _extract_offer_reference_from_project_ref(project_ref)
    currency = "EUR" if ("\u20ac" in normalized_text or "EUR" in normalized_text.upper()) else None
    totals = _extract_totals(normalized_text)

    return {
        "template": template,
        "supplier_name": supplier_name_for_template(template),
        "document_type": document_type,
        "document_number": document_number,
        "offer_reference": offer_reference,
        "document_date": document_date,
        "project_ref": project_ref,
        "currency": currency,
        "position_count": _count_positions(template, normalized_text),
        "totals": totals,
        "notes": [
            "Template detection and header extraction are now routed via a template registry.",
            "Next step: expand golden regression coverage per customer layout.",
        ],
    }
