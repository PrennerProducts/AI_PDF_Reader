import re
from typing import Any

from template_common import extract_amount_tokens, normalize_line, normalize_text
from template_headers import first_match

POS_MARKER_RE = re.compile(r"^Pos\.$")
POS_LINE_RE = re.compile(
    r"^(?P<position>\d+[A-Za-z]?)\s+"
    r"(?P<qty>\d+(?:[,.]\d+)?)\s+"
    r"(?P<unit>Stck|Stk\.?|PA|Pauschale|Psch)(?:\s+(?P<label>.+))?$",
    flags=re.IGNORECASE,
)
POS_BOUNDARY_LINE_RE = re.compile(
    r"^(?P<position>\d+[A-Za-z]?)\s+"
    r"(?P<qty>\d+(?:[,.]\d+)?)\s+"
    r"(?P<unit>Stck|Stk\.?|PA|Pauschale|Psch)(?:\s+(?P<label>.+))?$",
    flags=re.IGNORECASE,
)
DIMENSION_RE = re.compile(r"B/H:\s*([0-9]+)\s*x\s*([0-9]+)", flags=re.IGNORECASE)
PRICE_PAIR_RE = re.compile(
    r"\(?\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\s*\)?"
    r"\s*\(?\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\s*\)?$"
)
MONEY_TOKEN_RE = re.compile(r"\(?\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\s*\)?")


def detect(normalized_lower: str) -> bool:
    if "schuchter fenster gmbh" not in normalized_lower:
        return False
    return any(
        marker in normalized_lower
        for marker in (
            "auftragsbestätigung",
            "angebot",
            "angebotsnummer",
            "pos.",
        )
    )


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    document_number = headers.get("document_number") or first_match(
        [
            r"ANGEBOT\s+([A-Za-z0-9./-]+)",
            r"Angebotsnummer\s*:?\s*([A-Za-z0-9./-]+)",
            r"AUFTRAGSBESTÄTIGUNG\s+([0-9]+)",
            r"Auftrag\s+([0-9]+)\s+vom",
        ],
        normalized_text,
        flags=re.IGNORECASE,
    )
    document_date = headers.get("document_date") or first_match(
        [
            r"Angebot\s+[A-Za-z0-9./-]+\s+vom\s+([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
            r"Datum:\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
            r"vom\s+([0-9]{2}\.[0-9]{2}\.[0-9]{4})",
        ],
        normalized_text,
        flags=re.IGNORECASE,
    )
    project_ref = headers.get("project_ref") or first_match(
        [r"Bauvorhaben:\s*([^\n]+)"],
        normalized_text,
        flags=re.IGNORECASE,
    )

    return {
        **headers,
        "document_number": normalize_line(document_number) if document_number else None,
        "document_date": normalize_line(document_date) if document_date else None,
        "project_ref": normalize_line(project_ref) if project_ref else None,
    }


def _is_position_start(lines: list[str], idx: int) -> bool:
    if idx >= len(lines) - 1:
        return False
    if not POS_MARKER_RE.fullmatch(lines[idx]):
        return False
    return bool(POS_LINE_RE.match(lines[idx + 1]))


def _is_position_boundary(lines: list[str], idx: int) -> bool:
    if idx >= len(lines) - 1:
        return False
    if not POS_MARKER_RE.fullmatch(lines[idx]):
        return False
    return bool(POS_BOUNDARY_LINE_RE.match(lines[idx + 1]))


def _extract_description_short(block_lines: list[str], fallback: str) -> str:
    for line in block_lines[1:]:
        lower = line.lower()
        if line in {".", "-"}:
            continue
        if lower.startswith(("b/h:", "übertrag:", "summe netto", "mwst", "summe brutto")):
            continue
        if re.fullmatch(r"[0-9 .]+", line):
            continue
        candidate = re.sub(r"^(?:\d+(?:[.,]\d+)?\s+){1,4}", "", line).strip()
        if any(
            keyword in candidate.lower()
            for keyword in ("fenster", "tür", "tür", "fixteil", "fixelement", "portaltür", "schiebetür")
        ):
            return _strip_trailing_drawing_numbers(candidate)
    return fallback


def _is_image_required(block_text_normalized: str, width_raw: str | None, height_raw: str | None) -> bool:
    if block_text_normalized.startswith("az auf pos.") or "az auf pos." in block_text_normalized:
        return False
    if "transportkosten" in block_text_normalized:
        return False
    if (
        not width_raw
        and not height_raw
        and "bestehend aus" in block_text_normalized
        and (
            "kopplungselement" in block_text_normalized
            or re.search(r"\belement\s+bestehend\s+aus\b", block_text_normalized)
        )
    ):
        return False
    return True


def _price_pair_from_line(line: str) -> tuple[str | None, str | None, bool]:
    pair_match = PRICE_PAIR_RE.search(line)
    if pair_match:
        return pair_match.group(1), pair_match.group(2), "(" in line and ")" in line

    amount_matches = MONEY_TOKEN_RE.findall(line)
    if len(amount_matches) < 2:
        return None, None, False
    return amount_matches[-2], amount_matches[-1], "(" in line and ")" in line


def _strip_price_pair_from_line(line: str) -> str:
    cleaned = PRICE_PAIR_RE.sub("", line)
    matches = list(MONEY_TOKEN_RE.finditer(cleaned))
    if len(matches) >= 2:
        start = matches[-2].start()
        end = matches[-1].end()
        cleaned = f"{cleaned[:start]} {cleaned[end:]}"
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" .-_\t")


def _is_description_noise_line(line: str) -> bool:
    lower = line.lower()
    if not lower:
        return True
    if line in {".", "-"}:
        return True
    if re.fullmatch(
        r"\d+[A-Za-z]?\s+\d+(?:[,.]\d+)?\s+(?:Stck\.?|Stk\.?|PA|Pauschale|Psch)",
        line,
        flags=re.IGNORECASE,
    ):
        return True
    if re.fullmatch(r"[0-9.,/\sxX*+-]+", line):
        return True
    if re.fullmatch(r"[-_—=]{4,}", line):
        return True
    if lower.startswith(
        (
            "übertrag:",
            "angebot ",
            "auftragsbestätigung ",
            "auftragsbestaetigung ",
            "pos. menge",
            "summe positionen",
            "summe netto",
            "mwst",
            "summe brutto",
        )
    ):
        return True
    return False


LEADING_NUMERIC_TOKEN_RE = re.compile(r"^(?:\d[\d.,:]*\s+)+")
BH_DIMENSION_RE = re.compile(r"B/H:\s*\d+\s*x\s*\d+", flags=re.IGNORECASE)
NUMERIC_LAYOUT_TAIL_RE = re.compile(r"[0-9.,/\sxX*+\-]*")

# A drawing dimension pair can bleed in glued together without a space (e.g.
# "2300"+"2300" -> "23002300"). Real SCHUCHTER spec/measurement values are at
# most 4 digits (specs 60/110/200, B/H heights like 2245), so a trailing run of
# this many bare digits is treated as a glued drawing artifact and cut. This is
# an interim heuristic; ADR-0003 (column-aware extraction) is the target that
# removes the need for it.
_GLUED_DIMENSION_MIN_DIGITS = 6
_TRAILING_GLUED_DIMENSION_RE = re.compile(rf"\s+\d{{{_GLUED_DIMENSION_MIN_DIGITS},}}\s*[.\-]*\s*$")


def _strip_leading_numeric_tokens(line: str) -> str:
    """Remove a run of leading number-only tokens before the real description.

    The PDF layout interleaves sash/flap numbers, coupling coordinates and
    reference codes (e.g. ``11.22.23``, ``22:``, ``1 600``) in front of the
    actual text. Each leading token that is purely numeric (digits plus
    ``. , :``) is dropped; the run stops at the first token containing a letter
    (so ``1-flg``, ``2x``, ``3xEsg``, ``B/H:`` and ``+unten`` are preserved).
    """
    stripped = LEADING_NUMERIC_TOKEN_RE.sub("", line)
    return stripped or line


def _normalize_bh_line(line: str) -> str:
    """Reduce a B/H line to the bare dimension ``B/H: <width>x <height>``.

    Only trailing tokens that are pure layout numbers (appended coordinates) are
    cut, so real words after a B/H mention are never dropped.
    """
    match = BH_DIMENSION_RE.search(line)
    if not match:
        return line
    tail = line[match.end():].strip()
    if tail and not NUMERIC_LAYOUT_TAIL_RE.fullmatch(tail):
        return line
    head = line[: match.start()].strip()
    dimension = match.group(0)
    return f"{head} {dimension}".strip() if head else dimension


def _strip_trailing_drawing_numbers(text: str) -> str:
    """Remove a trailing run of two or more bare numbers (drawing dimensions).

    Window drawings put dimension pairs like ``965 1000`` / ``685 720`` next to
    the type label; these bleed into the position text and are pure noise (the
    element size is stored separately as ``width_mm``/``height_mm``). Only runs
    of 2+ space-separated bare numbers (plus trailing dots/dashes) are cut, as
    well as a single trailing one-digit number (a sash/flap number like the
    ``1`` in ``DK-Rechts 1``). Multi-digit single numbers are spec values and
    are kept, so ``bis 110``, ``Aufdopplung 200`` and a B/H height
    (``B/H: 1500x 1000``) survive.

    A dimension pair can also bleed in glued together without a space (e.g.
    ``2300``+``2300`` -> ``23002300``); such a trailing run of
    ``_GLUED_DIMENSION_MIN_DIGITS``+ bare digits is a drawing artifact too and is
    cut, while real spec/measurement values (<=4 digits, incl. B/H heights like
    ``2245``) are kept.
    """
    cleaned = re.sub(r"(?:\s+\d+(?:[.,]\d+)?){2,}\s*[.\-]*\s*$", "", text)
    cleaned = _TRAILING_GLUED_DIMENSION_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+\d\s*[.\-]*\s*$", "", cleaned)
    if cleaned == text:
        return text.strip()
    return cleaned.rstrip(" .-").strip() or text


def _clean_description_lines(block_lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw_line in block_lines[1:]:
        line = normalize_line(raw_line)
        if _is_description_noise_line(line):
            continue
        line = _strip_price_pair_from_line(line)
        line = _strip_leading_numeric_tokens(line)
        line = _normalize_bh_line(line)
        line = _strip_trailing_drawing_numbers(line)
        if not line or _is_description_noise_line(line):
            continue
        if cleaned and cleaned[-1].lower() == line.lower():
            continue
        cleaned.append(line)
    return cleaned


def _extract_items_from_records(line_records: list[tuple[str, int]]) -> list[dict[str, Any]]:
    lines = [line for line, _page_ref in line_records]
    items: list[dict[str, Any]] = []
    idx = 0

    while idx < len(lines):
        if not _is_position_start(lines, idx):
            idx += 1
            continue

        header_match = POS_LINE_RE.match(lines[idx + 1])
        if not header_match:
            idx += 1
            continue

        end = idx + 2
        while end < len(lines):
            if _is_position_boundary(lines, end):
                break
            if lines[end].startswith(("Summe Positionen", "Summe Netto", "MwSt", "Summe Brutto")):
                break
            end += 1

        block_lines = lines[idx + 1 : end]
        block_text = "\n".join(block_lines)
        unit_price_raw = None
        line_total_raw = None
        is_alternative = False
        for line in reversed(block_lines):
            unit_candidate, total_candidate, candidate_is_alternative = _price_pair_from_line(line)
            if unit_candidate and total_candidate:
                unit_price_raw = unit_candidate
                line_total_raw = total_candidate
                is_alternative = candidate_is_alternative
                break
        if unit_price_raw is None or line_total_raw is None:
            pricing_text = "\n".join(
                line for line in block_lines if not line.lower().startswith(("übertrag:", "summe positionen"))
            )
            amount_tokens = extract_amount_tokens(pricing_text)
            unit_price_raw = amount_tokens[-2] if len(amount_tokens) >= 2 else None
            line_total_raw = amount_tokens[-1] if len(amount_tokens) >= 1 else None
        dimensions = DIMENSION_RE.search(block_text)
        width_raw = dimensions.group(1) if dimensions else None
        height_raw = dimensions.group(2) if dimensions else None
        lv_pos = normalize_line(header_match.group("label") or "")
        description_short = _extract_description_short(block_lines, fallback=lv_pos)
        # Aggregate "Kopplungselement bestehend aus: ..." positions have no own
        # product name, so the fallback repeats the label as the short text --
        # and _prepend_room_label_to_long_text (main) also puts that label at the
        # head of the long text. Keep it in the long text only so the Kurztext
        # column is not duplicated on the printed export (same intent as the
        # NEWO note rule). A real product short never contains "bestehend aus".
        if "bestehend aus" in description_short.lower():
            description_short = ""
        block_text_normalized = normalize_line(block_text).lower()
        image_required = _is_image_required(block_text_normalized, width_raw, height_raw)
        description_lines = _clean_description_lines(block_lines)

        items.append(
            {
                "position_no": header_match.group("position"),
                "lv_pos": lv_pos,
                "image_required": image_required,
                "is_alternative": is_alternative,
                "quantity_raw": header_match.group("qty"),
                "unit": header_match.group("unit"),
                "width_raw": width_raw,
                "height_raw": height_raw,
                "description_short": description_short,
                "description_long": "\n".join(description_lines)[:8000],
                "unit_price_raw": unit_price_raw,
                "line_total_raw": line_total_raw,
                "page_ref": line_records[idx][1],
            }
        )
        idx = end

    return items


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    line_records: list[tuple[str, int]] = []
    for page_idx, page_text in enumerate(normalized_text.split("\f"), start=1):
        for raw in page_text.splitlines():
            line = normalize_line(raw)
            if line:
                line_records.append((line, page_idx))
    return _extract_items_from_records(line_records)


def count_positions(text: str) -> int:
    return len(extract_line_items(text))
