import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from db import _line_item_with_document_pricing_mode


def test_document_pricing_mode_can_show_entholzer_basis_price() -> None:
    item = {
        "quantity": "1",
        "unit_price": "676.30",
        "line_total": "676.30",
        "metadata_json": {
            "pricing_adjustments_applied": True,
            "pricing_original_unit_price": "751.44",
            "pricing_original_line_total": "751.44",
            "pricing_adjusted_unit_price": "676.30",
            "pricing_adjusted_line_total": "676.30",
            "entholzer_pricing_applied": True,
        },
    }

    adjusted = _line_item_with_document_pricing_mode(item, apply_pricing_adjustments=False)

    assert adjusted["unit_price"] == Decimal("751.44")
    assert adjusted["line_total"] == Decimal("751.44")
    assert adjusted["metadata_json"]["pricing_disabled_by_document"] is True
    assert adjusted["metadata_json"]["entholzer_pricing_disabled_by_document"] is True
