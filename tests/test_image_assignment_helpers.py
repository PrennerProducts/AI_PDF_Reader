import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from image_assignment import (
    focused_image_ids,
    image_layout_sort_key,
    metadata_image_assignment,
    metadata_review_state,
)
from main import _candidate_images_for_item


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


def test_image_layout_sort_key_prefers_visual_page_order() -> None:
    upper = {"id": 1, "image_index": 9, "metadata_json": {"top_ratio": 0.10, "left_ratio": 0.40}}
    lower = {"id": 2, "image_index": 1, "metadata_json": {"top_ratio": 0.70, "left_ratio": 0.20}}

    assert image_layout_sort_key(upper) < image_layout_sort_key(lower)


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
