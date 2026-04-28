import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from image_assignment import (
    page_visual_slot_image_id,
    rebalance_unique_primary_image_assignments,
    spare_carryover_image_ids,
)


def test_page_visual_slot_image_id_does_not_reuse_images_when_items_exceed_images() -> None:
    image_ids = [101]

    assert page_visual_slot_image_id(image_ids, 0) == 101
    assert page_visual_slot_image_id(image_ids, 1) is None


def test_spare_carryover_image_ids_only_returns_unclaimed_next_page_images() -> None:
    image_ids = [201, 202, 203]

    assert spare_carryover_image_ids(image_ids, next_page_visual_item_count=3) == []
    assert spare_carryover_image_ids(image_ids, next_page_visual_item_count=2) == [201]
    assert spare_carryover_image_ids(image_ids, next_page_visual_item_count=0) == [201, 202, 203]


def test_rebalance_unique_primary_image_assignments_moves_duplicate_to_best_alternative() -> None:
    items = [
        {
            "line_item_id": 1,
            "candidate_image_ids": [101, 102],
            "heuristic": {"scores": [{"image_id": 101, "score": 0.95}, {"image_id": 102, "score": 0.60}]},
            "selected_image_ids": [101],
            "selected_primary_image_id": 101,
            "selection_source": "heuristic",
            "selection_reason": "heuristic_default",
        },
        {
            "line_item_id": 2,
            "candidate_image_ids": [101, 103],
            "heuristic": {"scores": [{"image_id": 101, "score": 0.91}, {"image_id": 103, "score": 0.89}]},
            "selected_image_ids": [101],
            "selected_primary_image_id": 101,
            "selection_source": "heuristic",
            "selection_reason": "heuristic_default",
        },
    ]

    rebalanced = rebalance_unique_primary_image_assignments(items, minimum_score=0.25)

    assert rebalanced[0]["selected_image_ids"] == [101]
    assert rebalanced[1]["selected_image_ids"] == [103]
    assert rebalanced[1]["selection_reason"] == "unique_image_resolution"


def test_rebalance_unique_primary_image_assignments_clears_unresolved_duplicate() -> None:
    items = [
        {
            "line_item_id": 1,
            "candidate_image_ids": [101],
            "heuristic": {"scores": [{"image_id": 101, "score": 0.95}]},
            "selected_image_ids": [101],
            "selected_primary_image_id": 101,
            "selection_source": "heuristic",
            "selection_reason": "heuristic_default",
        },
        {
            "line_item_id": 2,
            "candidate_image_ids": [101, 102],
            "heuristic": {"scores": [{"image_id": 101, "score": 0.91}, {"image_id": 102, "score": 0.10}]},
            "selected_image_ids": [101],
            "selected_primary_image_id": 101,
            "selection_source": "heuristic",
            "selection_reason": "heuristic_default",
        },
    ]

    rebalanced = rebalance_unique_primary_image_assignments(items, minimum_score=0.25)

    assert rebalanced[0]["selected_image_ids"] == []
    assert rebalanced[0]["selected_primary_image_id"] is None
    assert rebalanced[0]["selection_source"] == "heuristic_manual_required"
    assert rebalanced[0]["selection_reason"] == "duplicate_image_requires_manual_review"
    assert rebalanced[1]["selected_image_ids"] == []
    assert rebalanced[1]["selected_primary_image_id"] is None
    assert rebalanced[1]["selection_source"] == "heuristic_manual_required"
    assert rebalanced[1]["selection_reason"] == "duplicate_image_requires_manual_review"
