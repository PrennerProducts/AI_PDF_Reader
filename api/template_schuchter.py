import re
from typing import Any

from template_common import extract_amount_tokens, normalize_line, normalize_text
from template_headers import first_match

POS_MARKER_RE = re.compile(r"^Pos\.$")
POS_LINE_RE = re.compile(
    r"^(?P<position>\d+[A-Za-z]?)\s+"
    r"(?P<qty>\d+(?:[,.]\d+)?)\s+"
    r"(?P<unit>Stck|Stk\.?)(?:\s+(?P<label>.+))?$",
    flags=re.IGNORECASE,
)
DIMENSION_RE = re.compile(r"B/H:\s*([0-9]+)\s*x\s*([0-9]+)", flags=re.IGNORECASE)
PRICE_PAIR_RE = re.compile(
    r"\(?\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\s*\)?"
    r"\s*\(?\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\s*\)?$"
)


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
            return candidate
    return fallback


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
            if _is_position_start(lines, end):
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
            pair_match = PRICE_PAIR_RE.search(line)
            if pair_match:
                unit_price_raw = pair_match.group(1)
                line_total_raw = pair_match.group(2)
                is_alternative = "(" in line and ")" in line
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
        block_text_normalized = normalize_line(block_text).lower()
        image_required = not (
            block_text_normalized.startswith("az auf pos.")
            or "az auf pos." in block_text_normalized
        )

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
                "description_long": block_text[:8000],
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
