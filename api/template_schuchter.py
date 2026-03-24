import re
from typing import Any

from template_common import normalize_text


def detect(normalized_lower: str) -> bool:
    return "todo-schuchter" in normalized_lower


def count_positions(text: str) -> int:
    return 0


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    return dict(headers)


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    items: list[dict[str, Any]] = []

    # TODO: replace the placeholder detector and implement provider-specific parsing.
    _ = normalized_text
    return items
