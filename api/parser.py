import re
from decimal import Decimal, InvalidOperation
from typing import Any

from template_common import extract_amount_tokens as _extract_amount_tokens
from template_common import normalize_line as _normalize_line
from template_common import normalize_text as _normalize_text
from template_registry import count_positions as _count_positions
from template_registry import detect_template as _detect_template
from template_registry import supplier_name_for_template

LABEL_ONLY_RE = re.compile(r"^[A-Za-zÄÖÜäöüß .()/+-]+:\s*$")
DATE_ONLY_RE = re.compile(r"^[0-9]{2}\.[0-9]{2}\.[0-9]{4}$")
PHONE_ONLY_RE = re.compile(r"^\+?[0-9][0-9 /().-]{6,}$")
INLINE_LABEL_VALUE_RE = re.compile(r"^[A-Za-zÄÖÜäöüß .()/+-]+:\s*.+$")


def _first_match(patterns: list[str], text: str, flags: int = 0) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
    return None


def _normalized_non_empty_lines(text: str) -> list[str]:
    return [line for line in (_normalize_line(raw) for raw in text.splitlines()) if line]


def _collapse_header_value(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip()


def _find_nearby_label_value(
    lines: list[str],
    label: str,
    validator,
    *,
    search_before: int = 6,
    search_after: int = 6,
) -> str | None:
    label_lower = label.lower()
    for idx, line in enumerate(lines):
        if line.lower() != label_lower:
            continue
        for step in range(1, search_after + 1):
            probe_idx = idx + step
            if probe_idx >= len(lines):
                break
            probe = lines[probe_idx]
            if LABEL_ONLY_RE.match(probe):
                continue
            if validator(probe):
                return probe
        for step in range(1, search_before + 1):
            probe_idx = idx - step
            if probe_idx < 0:
                break
            probe = lines[probe_idx]
            if LABEL_ONLY_RE.match(probe):
                continue
            if validator(probe):
                return probe
    return None


def _looks_like_document_number(value: str | None) -> bool:
    if not value:
        return False
    clean = value.strip()
    if " " in clean:
        return False
    lower = clean.lower()
    if any(token in lower for token in ("vorgang", "belegdatum", "seite")):
        return False
    if re.fullmatch(r"[A-Z][0-9]{7}[A-Z]{2}", clean):
        return True
    if re.fullmatch(r"[0-9]{5,}(?:[.-][0-9]+)?", clean):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9.-]*\d[A-Za-z0-9.-]*", clean) and re.search(r"[A-Za-z]", clean))


def _looks_like_project_ref(value: str | None) -> bool:
    if not value:
        return False
    clean = value.strip()
    lower = clean.lower()
    if not clean or clean.endswith(":"):
        return False
    if DATE_ONLY_RE.fullmatch(clean) or PHONE_ONLY_RE.fullmatch(clean):
        return False
    if lower.startswith(("nummer", "druckdatum", "anfrage", "kommission", "bearbeiter", "fax", "tel", "frau ", "herr ")):
        return False
    return bool(re.search(r"[A-Za-zÄÖÜäöüß]", clean))


def _looks_like_document_date(value: str | None) -> bool:
    return bool(value and DATE_ONLY_RE.fullmatch(value.strip()))


def _looks_like_rekord_project_part(value: str | None) -> bool:
    if not value:
        return False
    clean = value.strip()
    lower = clean.lower()
    if not clean or clean.endswith(":"):
        return False
    if DATE_ONLY_RE.fullmatch(clean) or PHONE_ONLY_RE.fullmatch(clean):
        return False
    if lower.startswith(
        (
            "belegdatum",
            "seite",
            "angebot",
            "vorgang",
            "bearbeiter",
            "kundenkontakt",
            "name :",
            "tel. :",
            "mail :",
            "sehr geehrte",
        )
    ):
        return False
    return bool(re.search(r"[A-Za-zÄÖÜäöüß]", clean))


def _extract_order_confirmation_number(normalized_text: str) -> str | None:
    return _first_match(
        [
            r"(?mi)^\s*Auftragsbest[aä]tigung(?:\s*N[°o])?\s*:\s*([A-Za-z0-9.-]+)\b",
            r"(?mi)^\s*Auftragsbest[aä]tigung\s+([A-Za-z0-9.-]+)\b",
        ],
        normalized_text,
    )


def _collect_multiline_label_value(lines: list[str], label: str, *, max_lines: int = 2) -> str | None:
    label_prefix = f"{label.lower()}:"
    for idx, line in enumerate(lines):
        if not line.lower().startswith(label_prefix):
            continue

        initial = line.split(":", 1)[1].strip()
        parts = [initial] if initial else []

        for step in range(1, max_lines + 1):
            probe_idx = idx + step
            if probe_idx >= len(lines):
                break
            probe = lines[probe_idx]
            if LABEL_ONLY_RE.match(probe) or INLINE_LABEL_VALUE_RE.match(probe):
                break
            if DATE_ONLY_RE.fullmatch(probe) or PHONE_ONLY_RE.fullmatch(probe):
                break
            if not probe:
                break
            parts.append(probe)

        if parts:
            return _collapse_header_value(" ".join(parts))
    return None


def _apply_alu_one_header_fallbacks(
    normalized_text: str,
    *,
    document_number: str | None,
    document_date: str | None,
    project_ref: str | None,
) -> tuple[str | None, str | None, str | None]:
    lines = _normalized_non_empty_lines(normalized_text)

    if not _looks_like_document_number(document_number):
        document_number = _find_nearby_label_value(lines, "Nummer:", _looks_like_document_number)

    if not _looks_like_document_date(document_date):
        document_date = _find_nearby_label_value(lines, "Druckdatum:", _looks_like_document_date)

    if not _looks_like_project_ref(project_ref):
        project_ref = _find_nearby_label_value(lines, "Kommission:", _looks_like_project_ref)

    return document_number, document_date, project_ref


def _apply_rekord_vomp_header_fallbacks(
    normalized_text: str,
    *,
    document_number: str | None,
    document_date: str | None,
    project_ref: str | None,
) -> tuple[str | None, str | None, str | None]:
    lines = _normalized_non_empty_lines(normalized_text)

    if not _looks_like_document_number(document_number):
        document_number = _first_match(
            [
                r"Angebot\s*:\s*([A-Z]{2,6}[0-9]{4,}(?:[A-Z]{1,3}(?![a-z]))?)",
                r"(?mi)^\s*Angebot\s*:\s*([A-Za-z0-9.-]+)\s*$",
                r"Angebot\s*:\s*([A-Za-z0-9.-]+)",
            ],
            normalized_text,
        )

    if not _looks_like_project_ref(project_ref):
        for idx, line in enumerate(lines):
            if "bauvorhaben:" not in line.lower():
                continue
            inline_value = line.split(":", 1)[1].strip() if ":" in line else ""
            if _looks_like_project_ref(inline_value):
                project_ref = inline_value
                break
            collected: list[str] = []
            for step in range(1, 5):
                probe_idx = idx + step
                if probe_idx >= len(lines):
                    break
                probe = lines[probe_idx]
                if LABEL_ONLY_RE.match(probe):
                    break
                if DATE_ONLY_RE.fullmatch(probe):
                    break
                if not _looks_like_rekord_project_part(probe):
                    break
                collected.append(probe)
            if collected:
                project_ref = " ".join(collected)
                break

    return document_number, document_date, project_ref


def _apply_entholzer_header_fallbacks(
    normalized_text: str,
    *,
    document_number: str | None,
    project_ref: str | None,
) -> tuple[str | None, str | None]:
    if not _looks_like_document_number(document_number):
        document_number = _extract_order_confirmation_number(normalized_text)

    if not _looks_like_project_ref(project_ref):
        project_ref = _collect_multiline_label_value(_normalized_non_empty_lines(normalized_text), "Kommission")

    return document_number, project_ref


def _apply_rieder_header_fallbacks(
    normalized_text: str,
    *,
    document_number: str | None,
    project_ref: str | None,
) -> tuple[str | None, str | None]:
    if not _looks_like_document_number(document_number):
        document_number = _extract_order_confirmation_number(normalized_text)

    if not _looks_like_project_ref(project_ref) or (project_ref and project_ref.endswith("+")):
        multiline_project_ref = _collect_multiline_label_value(_normalized_non_empty_lines(normalized_text), "Kommission")
        if multiline_project_ref:
            project_ref = multiline_project_ref

    return document_number, project_ref


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


def _extract_amount_via_inline_pattern(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def detect_template(text: str) -> str:
    return _detect_template(text)


def _extract_totals(text: str) -> dict[str, str | None]:
    lines = [_normalize_line(line) for line in text.splitlines()]
    net_total = _extract_amount_via_inline_pattern(
        text,
        (
            r"Summe Netto\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Nettosumme\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        ),
    )
    if net_total is None:
        net_total = _find_labeled_amount(lines, ("nettosumme",), pick="first")
    if net_total is None:
        net_total = _find_labeled_amount(lines, ("zwischensumme ohne ust", "zwischensumme", "nettowert", "summe netto"), pick="last")
    vat_total = _extract_amount_via_inline_pattern(
        text,
        (
            r"(?:MwSt|Mehrwertsteuer|USt\.)\s*[0-9., ]*%\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        ),
    )
    if vat_total is None:
        vat_total = _find_labeled_amount(lines, ("mehrwertsteuer", "ust.", "mwst"), pick="first")
    gross_total = _extract_amount_via_inline_pattern(
        text,
        (
            r"Summe Brutto\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Gesamt EUR\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
            r"Bruttobetrag\s*([0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        ),
    )
    if gross_total is None:
        gross_total = _find_labeled_amount(lines, ("angebotssumme", "gesamtsumme", "gesamt eur", "bruttobetrag", "summe brutto"), pick="last")

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


def parse_document_text(text: str) -> dict[str, Any]:
    normalized_text = _normalize_text(text)
    template = detect_template(text)
    document_number = _collapse_header_value(
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
    )
    document_date = _first_match(
        [
            r"(?m)^\s*Druckdatum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
            r"Belegdatum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
            r"Datum\s*:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
            r"Ried,\s+am\s+([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
            r"\b([0-9]{2}\.[0-9]{2}\.[0-9]{4})\b",
        ],
        normalized_text,
    )
    project_ref = _collapse_header_value(
        _first_match(
        [
            r"Kommission:\s*([^\n]+)",
            r"Kommission\s*:\s*([^\n]+)",
            r'Bauvorhaben\s*"([^"]+)"',
            r"(?m)^Projekt\s+(.+)$",
        ],
        normalized_text,
        )
    )
    if template == "alu_one":
        document_number, document_date, project_ref = _apply_alu_one_header_fallbacks(
            normalized_text,
            document_number=document_number,
            document_date=document_date,
            project_ref=project_ref,
        )
    elif template == "entholzer":
        document_number, project_ref = _apply_entholzer_header_fallbacks(
            normalized_text,
            document_number=document_number,
            project_ref=project_ref,
        )
    elif template == "rekord_vomp":
        document_number, document_date, project_ref = _apply_rekord_vomp_header_fallbacks(
            normalized_text,
            document_number=document_number,
            document_date=document_date,
            project_ref=project_ref,
        )
    elif template == "rieder":
        document_number, project_ref = _apply_rieder_header_fallbacks(
            normalized_text,
            document_number=document_number,
            project_ref=project_ref,
        )
    currency = "EUR" if ("\u20ac" in normalized_text or "EUR" in normalized_text.upper()) else None
    totals = _extract_totals(normalized_text)

    return {
        "template": template,
        "supplier_name": supplier_name_for_template(template),
        "document_number": document_number,
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
