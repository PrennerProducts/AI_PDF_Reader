import json
from typing import Any


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalized_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def dedupe_int_list(values: list[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def is_non_visual_line_item(item: dict[str, Any]) -> bool:
    description = _normalized_text(item.get("description_short"))
    position_no = _normalized_text(item.get("position_no"))
    if description.startswith("vorbemerk"):
        return True
    if position_no in {"000", "0"} and description in {"vorbemerkungen", "vorbemerkung"}:
        return True
    return False


def metadata_dict(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata_json")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def metadata_image_assignment(row: dict[str, Any], valid_ids: set[int]) -> dict[str, Any]:
    metadata = metadata_dict(row)
    has_decision = any(
        key in metadata
        for key in (
            "image_assignment_ids",
            "llm_image_ids",
            "image_assignment_source",
            "image_assignment_reason",
            "image_assignment_strategy",
        )
    )
    raw_ids = metadata.get("image_assignment_ids")
    if not isinstance(raw_ids, list):
        raw_ids = metadata.get("llm_image_ids")
    values: list[int] = []
    if isinstance(raw_ids, list):
        for value in raw_ids:
            parsed = _to_int(value)
            if parsed is None or parsed not in valid_ids:
                continue
            values.append(parsed)
    values = dedupe_int_list(values)
    source = str(metadata.get("image_assignment_source") or "").strip() or None
    reason = str(metadata.get("image_assignment_reason") or "").strip() or None
    return {
        "image_ids": values,
        "source": source,
        "reason": reason,
        "has_decision": has_decision,
        "is_final": bool(values),
    }


def metadata_review_state(row: dict[str, Any]) -> dict[str, Any]:
    metadata = metadata_dict(row)
    checked = metadata.get("review_checked") is True
    checked_at_raw = metadata.get("review_checked_at")
    checked_reason_raw = metadata.get("review_checked_reason")
    checked_at = str(checked_at_raw).strip() if checked_at_raw is not None else None
    checked_reason = str(checked_reason_raw).strip() if checked_reason_raw is not None else None
    return {
        "checked": checked,
        "checked_at": checked_at or None,
        "reason": checked_reason or None,
    }


def image_layout_sort_key(image: dict[str, Any]) -> tuple[int, float, float, int, int]:
    metadata = metadata_dict(image)
    top_ratio = _to_float(metadata.get("top_ratio"))
    left_ratio = _to_float(metadata.get("left_ratio"))
    has_layout = top_ratio is not None
    image_index = _to_int(image.get("image_index")) or 0
    image_id = _to_int(image.get("id")) or 0
    return (
        0 if has_layout else 1,
        top_ratio if top_ratio is not None else 0.0,
        left_ratio if left_ratio is not None else 0.0,
        image_index,
        image_id,
    )


def page_candidate_rank(item_page_ref: Any, image_page_ref: Any) -> tuple[int, int, int]:
    item_page = _to_int(item_page_ref)
    image_page = _to_int(image_page_ref)
    if item_page is None or image_page is None:
        return (99, 99, image_page or 0)

    diff = image_page - item_page
    return (
        abs(diff),
        0 if diff >= 0 else 1,
        image_page,
    )


def focused_image_ids(
    image_ids: list[int],
    *,
    item_count: int,
    item_index: int,
    max_candidates: int = 4,
) -> list[int]:
    ids = dedupe_int_list([value for value in image_ids if isinstance(value, int) and value > 0])
    if not ids:
        return []

    max_candidates = max(1, max_candidates)
    if len(ids) <= max_candidates and item_count <= 1:
        return ids[:max_candidates]

    if len(ids) == 1 or item_count <= 1:
        anchor = 0
    else:
        ratio = max(0.0, min(1.0, item_index / max(1, item_count - 1)))
        anchor = int(round(ratio * (len(ids) - 1)))

    ordered_offsets = (0, -1, 1, -2, 2, -3, 3, -4, 4)
    selected: list[int] = []
    for offset in ordered_offsets:
        idx = anchor + offset
        if idx < 0 or idx >= len(ids):
            continue
        image_id = ids[idx]
        if image_id in selected:
            continue
        selected.append(image_id)
        if len(selected) >= max_candidates:
            break
    return selected
