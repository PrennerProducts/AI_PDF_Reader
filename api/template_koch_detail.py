import re
from typing import Any

from template_common import normalize_line, normalize_text

ORDER_RE = re.compile(r"\bAuftrag\s*:\s*([A-Za-z0-9.-]+)", flags=re.IGNORECASE)
POSITION_RE = re.compile(r"\bPosition(?:\(en\))?\s*:\s*([0-9][0-9,\s./-]*)", flags=re.IGNORECASE)
DETAIL_TITLE_RE = re.compile(r"(?m)^\s*(Visualisierung[^\n]*|Systemdetails[^\n]*|SYSTEM\s+[^\n]*)\s*$", flags=re.IGNORECASE)


def detect(normalized_lower: str) -> bool:
    return (
        "auftrag:" in normalized_lower
        and ("position:" in normalized_lower or "position(en):" in normalized_lower)
        and (
            "visualisierung" in normalized_lower
            or "systemdetails" in normalized_lower
            or "system " in normalized_lower
            or "mit stockmaßen" in normalized_lower
            or "türdesign" in normalized_lower
            or "m=1:2" in normalized_lower
        )
    )


def count_positions(_: str) -> int:
    return 0


def extract_line_items(_: str) -> list[dict[str, Any]]:
    return []


def _position_numbers(raw: str | None) -> list[str]:
    if not raw:
        return []
    values: list[str] = []
    for part in re.split(r"[,/;\s]+", raw):
        cleaned = part.strip(" .-")
        if cleaned.isdigit() and cleaned not in values:
            values.append(cleaned)
    return values


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    order_match = ORDER_RE.search(normalized_text)
    title_match = DETAIL_TITLE_RE.search(normalized_text)
    return {
        **headers,
        "document_number": normalize_line(order_match.group(1)) if order_match else headers.get("document_number"),
        "project_ref": normalize_line(title_match.group(1)) if title_match else headers.get("project_ref"),
    }


def parse_page_details(text: str) -> dict[int, dict[str, Any]]:
    normalized_text = normalize_text(text)
    pages = normalized_text.split("\f")
    details: dict[int, dict[str, Any]] = {}
    for index, page_text in enumerate(pages, start=1):
        order_match = ORDER_RE.search(page_text)
        position_match = POSITION_RE.search(page_text)
        title_match = DETAIL_TITLE_RE.search(page_text)
        if not order_match and not position_match and not title_match:
            continue

        positions = _position_numbers(position_match.group(1) if position_match else None)
        details[index] = {
            "source_document_kind": "koch_detail_drawing",
            "source_order_number": normalize_line(order_match.group(1)) if order_match else None,
            "source_position_numbers": positions,
            "source_detail_type": normalize_line(title_match.group(1)) if title_match else None,
            "source_mapping_confidence": "high" if order_match and positions else "medium",
        }
    return details
