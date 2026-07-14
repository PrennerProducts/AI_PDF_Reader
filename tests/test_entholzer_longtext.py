"""Regression tests for entholzer position long-text cleaning.

The entholzer drawing column bleeds dimension numbers in front of real
description lines (e.g. ``1750 Alu - Schale …``, ``875 875 FLG 74 mm``). These
leading drawing dimensions are >=3-digit integers, while legitimate leading
numbers are 1-2 digit counts/quantities (``2 flügeliges Fenster``,
``3 Dichtungsebenen``, ``2 x Entwässerung``, ``1 Stk. …``). Only the former are
stripped.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from template_entholzer import _strip_leading_drawing_dimensions
from extractor import extract_pdf_text
from parser import parse_document_text
from main import _build_amount_line_rows, _build_line_item_rows
from image_assignment import image_within_item_vertical_window, metadata_dict
from vendoc_exporter import build_vendoc_payload

ENTHOLZER_DIR = ROOT / "samples/pdfs/candidates/offers/entholzer"
ENTHOLZER_REGRESSION_DIR = ROOT / "samples/pdfs/regression/offers/entholzer"
LEADING_DIMENSION = re.compile(r"^\s*\d{3,}\b")


def test_strips_leading_drawing_dimensions() -> None:
    assert _strip_leading_drawing_dimensions("1750 Alu - Schale RAL 8017") == "Alu - Schale RAL 8017"
    assert _strip_leading_drawing_dimensions("875 875 FLG 74 mm") == "FLG 74 mm"
    assert _strip_leading_drawing_dimensions("1260 960 4 x Entwässerung nach vorne") == "4 x Entwässerung nach vorne"
    assert _strip_leading_drawing_dimensions("600 1 x EW Kappen je nach Außenfarbe") == "1 x EW Kappen je nach Außenfarbe"
    assert _strip_leading_drawing_dimensions("1085 äußere Dichtungen eingezogen; grau") == "äußere Dichtungen eingezogen; grau"
    assert _strip_leading_drawing_dimensions("1256 Glasart:Ug 0,5 W/m²K") == "Glasart:Ug 0,5 W/m²K"


def test_keeps_legitimate_leading_quantities() -> None:
    for line in (
        "1 Stk. Koppeldicht. G022 grau; Maß:1667",
        "2 flügeliges Fenster mit Stulp",
        "2 teilige Festverglasung",
        "3 Dichtungsebenen",
        "2 x Entwässerung nach vorne",
        "4 x EW Kappen je nach Außenfarbe",
        "B/H: 1750 x 1095",
    ):
        assert _strip_leading_drawing_dimensions(line) == line


def test_two_positions_on_one_page_get_a_vertical_image_window() -> None:
    # Bernsteiner page 4 holds Pos 6 (Festverglasung, upper sketch) and Pos 7
    # (Hebeschiebetuer, lower sketch). Both sketches are near-square, so the
    # aspect-ratio tie-breaker swapped them. Populating item_top_ratio /
    # next_position_* gives each position its own vertical window, so the upper
    # image (center_y ~0.28) belongs to Pos 6 and the lower image (~0.57) to
    # Pos 7 -- and neither is a candidate for the other position.
    pdf = ENTHOLZER_REGRESSION_DIR / "Angebot 12600422.00 Bernsteiner.pdf"
    text = extract_pdf_text(pdf)
    rows = _build_line_item_rows(text, "entholzer")
    by_pos = {str(row.get("position_no")): row for row in rows}

    pos6, pos7 = by_pos["6"], by_pos["7"]
    assert metadata_dict(pos6).get("item_top_ratio") is not None
    assert metadata_dict(pos6).get("item_top_ratio") < metadata_dict(pos7).get("item_top_ratio")

    upper_image = {"id": 319, "page_ref": 4, "width": 202, "height": 251,
                   "metadata_json": {"center_y_ratio": 0.28, "top_ratio": 0.21}}
    lower_image = {"id": 320, "page_ref": 4, "width": 208, "height": 251,
                   "metadata_json": {"center_y_ratio": 0.57, "top_ratio": 0.51}}

    assert image_within_item_vertical_window(pos6, upper_image) is True
    assert image_within_item_vertical_window(pos6, lower_image) is False
    assert image_within_item_vertical_window(pos7, upper_image) is False
    assert image_within_item_vertical_window(pos7, lower_image) is True


def _entholzer_long_texts(pdf_name: str) -> list[str]:
    pdf = ENTHOLZER_DIR / pdf_name
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
    return [position["description_long"] or "" for position in payload["positions"]]


def test_entholzer_samples_have_no_leading_dimension_leaks() -> None:
    for pdf_name in (
        "Angebot 12600512-00_20260209_Email.pdf",
        "Angebot 12600930.00 Sagun, Kirchberg in Tirol.pdf",
    ):
        for long_text in _entholzer_long_texts(pdf_name):
            for line in long_text.splitlines():
                assert not LEADING_DIMENSION.match(line), f"leak in {pdf_name}: {line!r}"
