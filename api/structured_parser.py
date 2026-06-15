import re
from typing import Any

from template_common import extract_amount_tokens as _extract_amount_tokens
from template_common import normalize_line as _normalize_line
from template_registry import extract_line_items_for_template

PERCENT_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*%")
INLINE_ITEM_DISCOUNT_RE = re.compile(r"\b[0-9]+(?:[.,][0-9]+)?-\s*%\s*Rabatt\b", flags=re.IGNORECASE)


def _has_vat_term(lower: str) -> bool:
    return bool(
        "mehrwertsteuer" in lower
        or "mwst" in lower
        or "umsatzsteuer" in lower
        or re.search(r"\bust\.?\b", lower)
    )


def _is_amount_header_line(line: str) -> bool:
    lower = line.lower()
    return ("einzelpreis" in lower and "gesamtpreis" in lower) or ("preis/me" in lower and "nettobetrag" in lower)


def _classify_amount_line(label: str) -> str:
    lower = label.lower()
    if "gesamtbetrag netto" in lower or "gesamtbetrag (netto)" in lower or "summe positionen" in lower or "gesamtpreis positionen" in lower:
        return "net_total"
    if "gesamtpreis ohne mwst" in lower or "gesamtpreis ohne ust" in lower or "nettosumme" in lower or "nettowert" in lower or "summe netto" in lower:
        return "net_total"
    if "endbetrag" in lower or "gesamtbetrag" in lower:
        return "total"
    if "gesamtpreis incl. mwst" in lower or "gesamtpreis inkl. mwst" in lower or "angebotssumme" in lower or "gesamtsumme" in lower or "gesamt eur" in lower or "bruttobetrag" in lower or "summe brutto" in lower:
        return "total"
    if "zwischensumme" in lower or "summe ohne montagekosten" in lower or "summe der positionen" in lower or lower.startswith("summe"):
        return "subtotal"
    if lower.startswith("zuzüglich") and _has_vat_term(lower):
        return "vat"
    if _has_vat_term(lower):
        return "vat"
    if "rabatt" in lower or "abzug" in lower:
        return "discount"
    if "zuschlag" in lower or "frachtkosten" in lower or "zustellung" in lower or "baustellenanlieferung" in lower:
        return "surcharge"
    return "other"


def _has_amount_trigger(line: str) -> bool:
    lower = line.lower()
    if _is_amount_header_line(line):
        return False
    if "inklusive rabatte" in lower:
        return False
    if lower.startswith("der sonderrabatt ist"):
        return False
    if INLINE_ITEM_DISCOUNT_RE.search(line) and not lower.startswith(("abzüglich", "zuzüglich", "rabatt", "zuschlag")):
        return False
    return any(
        word in lower
        for word in (
            "summe",
            "summe positionen",
            "gesamtbetrag netto",
            "gesamtbetrag",
            "endbetrag",
            "gesamtpreis",
            "nettosumme",
            "nettowert",
            "summe netto",
            "angebotssumme",
            "gesamtsumme",
            "gesamt eur",
            "bruttobetrag",
            "summe brutto",
            "mehrwertsteuer",
            "ust.",
            "mwst",
            "umsatzsteuer",
            "rabatt",
            "zuschlag",
            "frachtkosten",
            "baustellenanlieferung",
            "zustellung",
        )
    ) or bool(re.search(r"\bust\.?\b", lower))


def _candidate_amount_for_trigger(lines: list[str], idx: int, line: str) -> tuple[str | None, str | None]:
    lower = line.lower()
    direct_tokens = _extract_amount_tokens(line)
    if direct_tokens:
        base = direct_tokens[-2] if len(direct_tokens) > 1 else None
        return direct_tokens[-1], base

    merged: list[str] = []
    for step in range(1, 4):
        if idx + step >= len(lines):
            break
        next_line = lines[idx + step]
        if _has_amount_trigger(next_line):
            break
        if next_line:
            merged.append(next_line)
    if merged:
        merged_tokens = _extract_amount_tokens(f"{line} {' '.join(merged)}")
        if merged_tokens:
            if "angebotssumme" in lower or "gesamtsumme" in lower or "gesamt eur" in lower or "bruttobetrag" in lower or "summe brutto" in lower:
                return merged_tokens[-1], None
            if "%" in lower or any(word in lower for word in ("rabatt", "zuschlag", "mehrwertsteuer", "ust.", "mwst")):
                base = merged_tokens[1] if len(merged_tokens) > 1 else None
                return merged_tokens[0], base
            base = merged_tokens[-2] if len(merged_tokens) > 1 else None
            return merged_tokens[0], base

    lookahead_tokens: list[str] = []
    for step in range(1, 8):
        if idx + step >= len(lines):
            break
        probe = lines[idx + step]
        if not probe:
            continue
        if _has_amount_trigger(probe):
            break
        tokens = _extract_amount_tokens(probe)
        if tokens:
            lookahead_tokens.extend(tokens)

    if not lookahead_tokens:
        return None, None
    if "angebotssumme" in lower or "gesamtsumme" in lower or "gesamt eur" in lower or "bruttobetrag" in lower or "summe brutto" in lower:
        return lookahead_tokens[-1], None
    return lookahead_tokens[0], None


def extract_amount_lines(text: str) -> list[dict[str, Any]]:
    lines = [_normalize_line(line) for line in text.splitlines()]
    amount_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    sort_order = 0

    for idx, line in enumerate(lines):
        if not line or not _has_amount_trigger(line):
            continue
        if _is_amount_header_line(line):
            continue

        amount_raw, base_amount_raw = _candidate_amount_for_trigger(lines, idx, line)
        if not amount_raw:
            continue

        line_type = _classify_amount_line(line)
        if line_type == "discount" and not amount_raw.strip().startswith("-"):
            amount_raw = f"-{amount_raw.strip()}"

        key = (line.lower(), amount_raw, line_type)
        if key in seen:
            continue
        seen.add(key)

        percent_match = PERCENT_RE.search(line)
        percent_raw = percent_match.group(1) if percent_match else None
        amount_rows.append(
            {
                "line_type": line_type,
                "label_raw": line,
                "percent_raw": percent_raw,
                "base_amount_raw": base_amount_raw,
                "amount_raw": amount_raw,
                "sort_order": sort_order,
            }
        )
        sort_order += 1

    return amount_rows


def extract_line_items(text: str, template: str) -> list[dict[str, Any]]:
    return extract_line_items_for_template(text, template)
