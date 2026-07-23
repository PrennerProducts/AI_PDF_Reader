import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from parser import parse_document_text
from structured_parser import extract_amount_lines, extract_line_items
from validation import build_document_validation

from test_offer_corpus_smoke import GREEN_OFFER_CASES


def _read_pdf_text(path: Path) -> str:
    return subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True)


def _validation_document(parsed: dict[str, object]) -> dict[str, object]:
    totals = parsed.get("totals") if isinstance(parsed.get("totals"), dict) else {}
    return {
        "supplier_name": parsed.get("supplier_name"),
        "document_type": parsed.get("document_type"),
        "document_number": parsed.get("document_number"),
        "document_date": parsed.get("document_date"),
        "project_ref": parsed.get("project_ref"),
        "currency": parsed.get("currency") or "EUR",
        # Kunde ist Pflichtfeld (wird vor Freigabe zugewiesen); im Corpus fix gesetzt.
        "customer_name": "Testkunde",
        "net_total": totals.get("net_total"),
        "vat_total": totals.get("vat_total"),
        "gross_total": totals.get("gross_total"),
        "parse_confidence": "0.99",
        "raw_text_path": None,
        "approval_status": "pending",
    }


def _validation_line_item(item: dict[str, object]) -> dict[str, object]:
    return {
        "position_no": item.get("position_no"),
        "lv_pos": item.get("lv_pos"),
        "description_short": item.get("description_short"),
        "description_long": item.get("description_long"),
        "quantity": item.get("quantity_raw"),
        "unit": item.get("unit"),
        "unit_price": item.get("unit_price_raw"),
        "line_total": item.get("line_total_raw"),
        "page_ref": item.get("page_ref"),
        "is_alternative": item.get("is_alternative"),
        "image_ids": [],
    }


@pytest.mark.parametrize("case", GREEN_OFFER_CASES, ids=[Path(case["path"]).name for case in GREEN_OFFER_CASES])
def test_green_offer_corpus_has_no_amount_validation_warnings(case: dict[str, object]) -> None:
    text = _read_pdf_text(ROOT / str(case["path"]))
    parsed = parse_document_text(text)
    line_items = [_validation_line_item(item) for item in extract_line_items(text, str(parsed["template"]))]
    validation = build_document_validation(
        document=_validation_document(parsed),
        amount_lines=extract_amount_lines(text),
        line_items=line_items,
        images=[],
    )

    assert validation["status"] == "auto_accept"
    assert validation["error_count"] == 0
    assert validation["warning_count"] == 0
