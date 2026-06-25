"""Regression test for alu_one position long-text de-duplication.

alu_one builds ``description_long`` from the raw position block, whose first
line is the element header that is *also* extracted as ``description_short``
(e.g. ``Türelement 2650 mm x 2700 mm``). That makes the short text appear
twice in the export. The first long-text line is dropped when it duplicates the
short text, scoped to alu_one; the rest of the block is preserved.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from extractor import extract_pdf_text
from parser import parse_document_text
from main import _build_amount_line_rows, _build_line_item_rows
from vendoc_exporter import build_vendoc_payload
import template_alu_one

ALU_ONE_DIR = ROOT / "samples/pdfs/candidates/offers/alu_one"


def test_alu_one_stored_long_text_does_not_repeat_short_text() -> None:
    # The de-duplication must happen at parse time so the *stored* long text
    # (what the app/DB and both exports read) is already clean -- not only the
    # VenDoc payload.
    for pdf_name in ("Angebot 2400061DL-1_i.pdf", "Angebot A2506340MC-1.pdf", "Angebot C2308329MK.pdf"):
        text = extract_pdf_text(ALU_ONE_DIR / pdf_name)
        for item in template_alu_one.extract_line_items(text):
            short = (item["description_short"] or "").strip()
            long_text = item["description_long"] or ""
            first_line = long_text.splitlines()[0].strip() if long_text.splitlines() else ""
            if short:
                assert first_line != short, f"{pdf_name} pos {item['position_no']}: short repeated as long[0]"


def _alu_one_positions(pdf_name: str) -> list[dict]:
    pdf = ALU_ONE_DIR / pdf_name
    text = extract_pdf_text(pdf)
    parsed = parse_document_text(text)
    amount_rows = _build_amount_line_rows(text, parsed["totals"], template=parsed["template"])
    rows = _build_line_item_rows(text, parsed["template"], source_path=pdf, amount_line_rows=amount_rows)
    payload = build_vendoc_payload(
        {
            "document": {
                "id": 1,
                "supplier_name": parsed["supplier_name"],
                "document_type": parsed["document_type"],
                "document_number": parsed["document_number"],
                "document_date": parsed["document_date"],
                "currency": parsed["currency"],
                "apply_pricing_adjustments": True,
            },
            "line_items": rows,
            "images": [],
        }
    )
    return payload["positions"]


def test_alu_one_long_text_does_not_repeat_short_text() -> None:
    for pdf_name in ("Angebot 2400061DL-1_i.pdf", "Angebot A2506340MC-1.pdf", "Angebot C2308329MK.pdf"):
        for position in _alu_one_positions(pdf_name):
            short = (position["description_short"] or "").strip()
            long_text = position["description_long"] or ""
            first_line = long_text.splitlines()[0].strip() if long_text.splitlines() else ""
            if short:
                assert first_line != short, f"{pdf_name} pos {position['position_no']}: short repeated as long[0]"


def test_alu_one_long_text_keeps_the_rest_of_the_block() -> None:
    # Pos 2 header "Fensterelement … 1.1" is dropped from the long text, but the
    # real block content below it (the "Festfeld …" line) must survive.
    positions = _alu_one_positions("Angebot 2400061DL-1_i.pdf")
    pos2 = positions[1]
    assert pos2["description_short"] == "Fensterelement 27200 mm x 2800 mm 1.1"
    assert pos2["description_long"].splitlines()[0] == "Festfeld 27200 mm x 2800 mm 1.1"
