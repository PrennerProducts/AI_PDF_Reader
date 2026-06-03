import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from main import LineItemUpdateRequest, _changed_line_item_updates, _line_item_update_payload


def test_line_item_update_payload_normalizes_edit_values() -> None:
    payload = LineItemUpdateRequest(
        position_no=" 2 ",
        description_short=" ",
        quantity=Decimal("1.23456"),
        unit_price=Decimal("12.345"),
        line_total=Decimal("24.995"),
        page_ref=4,
        is_alternative=False,
    )

    updates = _line_item_update_payload(payload)

    assert updates == {
        "position_no": "2",
        "description_short": None,
        "quantity": Decimal("1.2346"),
        "unit_price": Decimal("12.35"),
        "line_total": Decimal("25.00"),
        "page_ref": 4,
        "is_alternative": False,
    }


def test_changed_line_item_updates_ignores_equivalent_values() -> None:
    current = {
        "position_no": "2",
        "description_short": None,
        "quantity": "1.2346",
        "unit_price": "12.35",
        "line_total": "25.00",
        "page_ref": "4",
        "is_alternative": False,
    }
    updates = _line_item_update_payload(
        LineItemUpdateRequest(
            position_no="2",
            description_short=None,
            quantity=Decimal("1.23460"),
            unit_price=Decimal("12.350"),
            line_total=Decimal("25"),
            page_ref=4,
            is_alternative=False,
        )
    )

    assert _changed_line_item_updates(current, updates) == {}
