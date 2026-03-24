import re
from typing import Callable

LABEL_ONLY_RE = re.compile(r"^[A-Za-zÄÖÜäöüß .()/+-]+:\s*$")
DATE_ONLY_RE = re.compile(r"^[0-9]{2}\.[0-9]{2}\.[0-9]{4}$")
PHONE_ONLY_RE = re.compile(r"^\+?[0-9][0-9 /().-]{6,}$")
INLINE_LABEL_VALUE_RE = re.compile(r"^[A-Za-zÄÖÜäöüß .()/+-]+:\s*.+$")


def first_match(patterns: list[str], text: str, flags: int = 0) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
    return None


def collapse_header_value(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip()


def normalized_non_empty_lines(text: str, normalize_line: Callable[[str], str]) -> list[str]:
    return [line for line in (normalize_line(raw) for raw in text.splitlines()) if line]


def find_nearby_label_value(
    lines: list[str],
    label: str,
    validator: Callable[[str], bool],
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


def looks_like_document_number(value: str | None) -> bool:
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


def looks_like_project_ref(value: str | None) -> bool:
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


def looks_like_document_date(value: str | None) -> bool:
    return bool(value and DATE_ONLY_RE.fullmatch(value.strip()))


def looks_like_rekord_project_part(value: str | None) -> bool:
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


def extract_order_confirmation_number(normalized_text: str) -> str | None:
    return first_match(
        [
            r"(?mi)^\s*Auftragsbest[aä]tigung(?:\s*N[°o])?\s*:\s*([A-Za-z0-9.-]+)\b",
            r"(?mi)^\s*Auftragsbest[aä]tigung\s+([A-Za-z0-9.-]+)\b",
        ],
        normalized_text,
    )


def collect_multiline_label_value(lines: list[str], label: str, *, max_lines: int = 2) -> str | None:
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
            return collapse_header_value(" ".join(parts))
    return None
