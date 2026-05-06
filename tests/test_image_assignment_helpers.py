import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from image_assignment import (
    focused_image_ids,
    image_layout_sort_key,
    is_non_visual_line_item,
    metadata_image_assignment,
    metadata_review_state,
)
from db import _line_item_sort_key
from main import _candidate_images_for_item, _heuristic_match_for_item, _item_for_image_matching


def test_focused_image_ids_spreads_assignments_across_page() -> None:
    image_ids = [101, 102, 103, 104]

    first = focused_image_ids(image_ids, item_count=4, item_index=0, max_candidates=3)
    second = focused_image_ids(image_ids, item_count=4, item_index=1, max_candidates=3)
    last = focused_image_ids(image_ids, item_count=4, item_index=3, max_candidates=3)

    assert first[0] == 101
    assert second[0] in {102, 103}
    assert last[0] == 104


def test_focused_image_ids_reuses_nearest_image_when_items_exceed_images() -> None:
    image_ids = [201, 202]

    selections = [
        focused_image_ids(image_ids, item_count=6, item_index=index, max_candidates=2)[0]
        for index in range(6)
    ]

    assert selections[:3] == [201, 201, 201]
    assert selections[3:] == [202, 202, 202]


def test_metadata_image_assignment_reads_generic_assignment_fields() -> None:
    row = {
        "metadata_json": {
            "image_assignment_ids": [7, 8, 999],
            "image_assignment_source": "heuristic",
            "image_assignment_reason": "same_page_image_distribution",
        }
    }

    assignment = metadata_image_assignment(row, {7, 8, 9})

    assert assignment["image_ids"] == [7, 8]
    assert assignment["source"] == "heuristic"
    assert assignment["reason"] == "same_page_image_distribution"
    assert assignment["has_decision"] is True
    assert assignment["is_final"] is True


def test_metadata_image_assignment_keeps_empty_decision() -> None:
    row = {
        "metadata_json": {
            "image_assignment_ids": [],
            "image_assignment_source": "unmatched",
            "image_assignment_reason": "no_confident_candidate",
        }
    }

    assignment = metadata_image_assignment(row, {7, 8, 9})

    assert assignment["image_ids"] == []
    assert assignment["source"] == "unmatched"
    assert assignment["reason"] == "no_confident_candidate"
    assert assignment["has_decision"] is True
    assert assignment["is_final"] is False


def test_metadata_review_state_reads_checked_flag() -> None:
    row = {
        "metadata_json": {
            "review_checked": True,
            "review_checked_at": "2026-03-25T13:22:09Z",
            "review_checked_reason": "ui_manual_review",
        }
    }

    state = metadata_review_state(row)

    assert state["checked"] is True
    assert state["checked_at"] == "2026-03-25T13:22:09Z"
    assert state["reason"] == "ui_manual_review"


def test_image_required_false_marks_item_non_visual() -> None:
    item = {
        "description_short": "Neopor Platte,",
        "metadata_json": {
            "image_required": False,
            "referenced_lv_pos": "57.05.21.A",
        },
    }

    assert is_non_visual_line_item(item) is True


def test_image_layout_sort_key_prefers_visual_page_order() -> None:
    upper = {"id": 1, "image_index": 9, "metadata_json": {"top_ratio": 0.10, "left_ratio": 0.40}}
    lower = {"id": 2, "image_index": 1, "metadata_json": {"top_ratio": 0.70, "left_ratio": 0.20}}

    assert image_layout_sort_key(upper) < image_layout_sort_key(lower)


def test_line_item_sort_key_uses_extraction_order_for_mixed_subpositions() -> None:
    items = [
        {"id": 12, "position_no": "1b"},
        {"id": 13, "position_no": "1c"},
        {"id": 14, "position_no": "1"},
    ]

    ordered = sorted(items, key=_line_item_sort_key)

    assert [item["position_no"] for item in ordered] == ["1b", "1c", "1"]


def test_candidate_images_disallow_next_page_for_non_last_item() -> None:
    item = {
        "page_ref": 1,
        "image_candidate_ids": [21],
        "image_assignment_is_final": False,
        "image_next_page_allowed": False,
    }
    image_by_id = {
        21: {
            "id": 21,
            "page_ref": 2,
            "width": 900,
            "height": 900,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        }
    }

    candidates = _candidate_images_for_item(item, image_by_id, max_candidates=4)

    assert candidates == []


def test_candidate_images_allow_next_page_for_last_item_without_same_page_visual() -> None:
    item = {
        "page_ref": 1,
        "image_candidate_ids": [21],
        "image_assignment_is_final": False,
        "image_next_page_allowed": True,
    }
    image_by_id = {
        21: {
            "id": 21,
            "page_ref": 2,
            "width": 900,
            "height": 900,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        }
    }

    candidates = _candidate_images_for_item(item, image_by_id, max_candidates=4)

    assert [candidate["id"] for candidate in candidates] == [21]


def test_candidate_images_prefer_same_page_visual_over_next_page_carryover() -> None:
    item = {
        "page_ref": 1,
        "image_candidate_ids": [11, 21],
        "image_assignment_is_final": False,
        "image_next_page_allowed": True,
    }
    image_by_id = {
        11: {
            "id": 11,
            "page_ref": 1,
            "width": 480,
            "height": 900,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        },
        21: {
            "id": 21,
            "page_ref": 2,
            "width": 900,
            "height": 900,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        },
    }

    candidates = _candidate_images_for_item(item, image_by_id, max_candidates=4)

    assert [candidate["id"] for candidate in candidates] == [11]


def test_candidate_images_keep_next_page_option_when_size_hint_exists() -> None:
    item = {
        "page_ref": 7,
        "image_candidate_ids": [13814, 13815],
        "image_assignment_is_final": False,
        "image_next_page_allowed": True,
        "width_raw": "2500",
        "height_raw": "2135",
    }
    image_by_id = {
        13814: {
            "id": 13814,
            "page_ref": 7,
            "width": 1200,
            "height": 219,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        },
        13815: {
            "id": 13815,
            "page_ref": 8,
            "width": 1200,
            "height": 1059,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        },
    }

    candidates = _candidate_images_for_item(item, image_by_id, max_candidates=4)

    assert [candidate["id"] for candidate in candidates] == [13815, 13814]


def test_candidate_images_use_page_all_when_primary_candidates_miss_same_page_visual() -> None:
    item = {
        "page_ref": 1,
        "image_candidate_ids": [21],
        "image_ids_page_all": [11],
        "image_assignment_is_final": False,
        "image_next_page_allowed": True,
    }
    image_by_id = {
        11: {
            "id": 11,
            "page_ref": 1,
            "width": 480,
            "height": 900,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        },
        21: {
            "id": 21,
            "page_ref": 2,
            "width": 900,
            "height": 900,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        },
    }

    candidates = _candidate_images_for_item(item, image_by_id, max_candidates=4)

    assert [candidate["id"] for candidate in candidates] == [11]


def test_candidate_images_keep_persisted_final_assignment_across_pages() -> None:
    item = {
        "page_ref": 1,
        "image_candidate_ids": [21],
        "image_ids_primary": [21],
        "image_assignment_is_final": True,
        "image_next_page_allowed": False,
    }
    image_by_id = {
        21: {
            "id": 21,
            "page_ref": 2,
            "width": 900,
            "height": 900,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        }
    }

    candidates = _candidate_images_for_item(item, image_by_id, max_candidates=4)

    assert [candidate["id"] for candidate in candidates] == [21]


def test_heuristic_image_match_prefers_layout_candidate_over_larger_lower_image() -> None:
    item = {
        "page_ref": 2,
        "image_assignment_is_final": False,
        "image_next_page_allowed": False,
    }
    candidates = [
        {
            "id": 9586,
            "page_ref": 2,
            "width": 254,
            "height": 161,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        },
        {
            "id": 9587,
            "page_ref": 2,
            "width": 358,
            "height": 300,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        },
    ]

    match = _heuristic_match_for_item(item, candidates, allow_multiple=False)

    assert match["selected_image_ids"] == [9586]


def test_heuristic_image_match_prefers_aspect_ratio_fit_over_same_page_strip() -> None:
    item = {
        "page_ref": 7,
        "image_assignment_is_final": False,
        "image_next_page_allowed": True,
        "width_raw": "2500",
        "height_raw": "2135",
    }
    candidates = [
        {
            "id": 13814,
            "page_ref": 7,
            "width": 1200,
            "height": 219,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        },
        {
            "id": 13815,
            "page_ref": 8,
            "width": 1200,
            "height": 1059,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        },
    ]

    match = _heuristic_match_for_item(item, candidates, allow_multiple=False)

    assert match["selected_image_ids"] == [13815]
    assert match["scores"][0]["image_id"] == 13815


def test_heuristic_image_match_keeps_candidates_but_blocks_unsafe_auto_match() -> None:
    item = {
        "page_ref": 2,
        "image_assignment_is_final": False,
        "image_next_page_allowed": False,
        "image_auto_match_allowed": False,
    }
    candidates = [
        {
            "id": 9586,
            "page_ref": 2,
            "width": 254,
            "height": 161,
            "is_probably_decorative": False,
            "is_repeated_across_pages": False,
        }
    ]

    match = _heuristic_match_for_item(item, candidates, allow_multiple=False)

    assert match["selected_image_ids"] == []
    assert match["scores"][0]["image_id"] == 9586
    assert match["auto_match_allowed"] is False


def test_automatic_image_assignment_is_not_final_input_for_next_match() -> None:
    item = {
        "page_ref": 2,
        "image_ids": [9587],
        "image_ids_primary": [9587],
        "image_assignment_is_final": True,
        "image_assignment_source": "heuristic",
    }

    matching_item = _item_for_image_matching(item)

    assert matching_item["image_assignment_is_final"] is False
    assert matching_item["image_ids"] == []
    assert matching_item["image_ids_primary"] == []


def test_manual_image_assignment_stays_final_input_for_next_match() -> None:
    item = {
        "page_ref": 2,
        "image_ids": [9587],
        "image_ids_primary": [9587],
        "image_assignment_is_final": True,
        "image_assignment_source": "manual",
    }

    assert _item_for_image_matching(item) is item
