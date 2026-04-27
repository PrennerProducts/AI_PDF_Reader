import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from image_assignment import rebalance_unique_primary_image_assignments


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


def test_rebalance_unique_primary_image_assignments_marks_shared_when_no_viable_alternative_exists() -> None:
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

    assert rebalanced[0]["selected_image_ids"] == [101]
    assert rebalanced[1]["selected_image_ids"] == [101]
    assert rebalanced[1]["selected_primary_image_id"] == 101
    assert rebalanced[1]["selection_source"] == "heuristic_shared"
    assert rebalanced[1]["selection_reason"] == "shared_image_no_viable_alternative"
