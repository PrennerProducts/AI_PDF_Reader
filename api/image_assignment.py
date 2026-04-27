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
    lv_pos = _normalized_text(item.get("lv_pos"))
    if description in {"umfang", "lieferung", "montage", "fracht", "transport", "rabatt", "skonto"}:
        return True
    if description.startswith("vorbemerk"):
        return True
    if description.startswith("az - ") or description.startswith("az-"):
        return True
    if lv_pos == "umfang":
        return True
    if position_no in {"000", "0"} and description in {"vorbemerkungen", "vorbemerkung"}:
        return True
    return False


def is_viable_auto_assignment_image(image: dict[str, Any]) -> bool:
    if not isinstance(image, dict):
        return False
    if image.get("is_probably_decorative"):
        return False
    width = _to_int(image.get("width")) or 0
    height = _to_int(image.get("height")) or 0
    return width > 0 and height > 0


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


def _match_item_candidate_ids(match_item: dict[str, Any]) -> list[int]:
    raw = match_item.get("candidate_image_ids")
    if not isinstance(raw, list):
        return []
    values: list[int] = []
    for value in raw:
        parsed = _to_int(value)
        if parsed is not None:
            values.append(parsed)
    return dedupe_int_list(values)


def _match_item_score_map(match_item: dict[str, Any]) -> dict[int, float]:
    scores: dict[int, float] = {}
    heuristic = match_item.get("heuristic")
    raw_rows = heuristic.get("scores") if isinstance(heuristic, dict) else None
    if isinstance(raw_rows, list):
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            image_id = _to_int(row.get("image_id"))
            score = _to_float(row.get("score"))
            if image_id is None or score is None:
                continue
            scores[image_id] = score
    return scores


def _selected_primary_image_id(match_item: dict[str, Any]) -> int | None:
    raw = match_item.get("selected_image_ids")
    if not isinstance(raw, list):
        return None
    for value in raw:
        parsed = _to_int(value)
        if parsed is not None:
            return parsed
    return None


def _best_alternative_image_id(
    match_item: dict[str, Any],
    *,
    blocked_ids: set[int],
    minimum_score: float,
) -> int | None:
    candidate_ids = _match_item_candidate_ids(match_item)
    if not candidate_ids:
        return None
    score_map = _match_item_score_map(match_item)
    ordered = sorted(
        candidate_ids,
        key=lambda image_id: (
            -(score_map.get(image_id, float("-inf"))),
            candidate_ids.index(image_id),
            image_id,
        ),
    )
    for image_id in ordered:
        if image_id in blocked_ids:
            continue
        if score_map.get(image_id, float("-inf")) < minimum_score:
            continue
        return image_id
    return None


def rebalance_unique_primary_image_assignments(
    match_items: list[dict[str, Any]],
    *,
    minimum_score: float = 0.25,
) -> list[dict[str, Any]]:
    if not match_items:
        return match_items

    while True:
        assigned_by_image: dict[int, list[int]] = {}
        for item_index, match_item in enumerate(match_items):
            selected_id = _selected_primary_image_id(match_item)
            if selected_id is None:
                continue
            assigned_by_image.setdefault(selected_id, []).append(item_index)

        duplicate_groups = {
            image_id: item_indexes
            for image_id, item_indexes in assigned_by_image.items()
            if len(item_indexes) > 1
        }
        if not duplicate_groups:
            return match_items

        reserved_unique_ids = {
            image_id
            for image_id, item_indexes in assigned_by_image.items()
            if len(item_indexes) == 1
        }
        changed = False

        for image_id, item_indexes in duplicate_groups.items():
            score_map_by_item = {
                item_index: _match_item_score_map(match_items[item_index])
                for item_index in item_indexes
            }

            def _keeper_key(item_index: int) -> tuple[int, float, float, int]:
                match_item = match_items[item_index]
                item_scores = score_map_by_item[item_index]
                selected_score = item_scores.get(image_id, float("-inf"))
                alt_blocked_ids = set(reserved_unique_ids)
                alt_blocked_ids.add(image_id)
                alt_id = _best_alternative_image_id(
                    match_item,
                    blocked_ids=alt_blocked_ids,
                    minimum_score=minimum_score,
                )
                alt_score = item_scores.get(alt_id, float("-inf")) if alt_id is not None else float("-inf")
                no_alternative = 1 if alt_id is None else 0
                margin = selected_score - alt_score if alt_id is not None else 999.0
                return (no_alternative, margin, selected_score, -item_index)

            keeper_index = max(item_indexes, key=_keeper_key)
            reserved_unique_ids.add(image_id)

            for item_index in item_indexes:
                if item_index == keeper_index:
                    continue
                match_item = match_items[item_index]
                alt_image_id = _best_alternative_image_id(
                    match_item,
                    blocked_ids=reserved_unique_ids,
                    minimum_score=minimum_score,
                )
                if alt_image_id is None:
                    match_item["selected_image_ids"] = [image_id]
                    match_item["selected_primary_image_id"] = image_id
                    previous_source = str(match_item.get("selection_source") or "").strip()
                    match_item["selection_source"] = (
                        f"{previous_source}_shared" if previous_source else "shared_image"
                    )
                    match_item["selection_reason"] = "shared_image_no_viable_alternative"
                    continue

                if _selected_primary_image_id(match_item) != alt_image_id:
                    changed = True
                match_item["selected_image_ids"] = [alt_image_id]
                match_item["selected_primary_image_id"] = alt_image_id
                previous_source = str(match_item.get("selection_source") or "").strip()
                match_item["selection_source"] = f"{previous_source}_unique" if previous_source else "unique_rebalanced"
                match_item["selection_reason"] = "unique_image_resolution"
                reserved_unique_ids.add(alt_image_id)

        if not changed:
            return match_items
