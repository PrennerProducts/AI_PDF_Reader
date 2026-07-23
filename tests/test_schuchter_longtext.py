"""Regression tests for SCHUCHTER position long-text cleaning.

Dragan reported that SCHUCHTER position long texts still contained numbers that
do not belong there (sash/flap numbers, coupling coordinates, reference codes
like ``11.22.23``, prices). These must be filtered out cleanly while keeping the
real description and legitimate measurements.

Rules confirmed with the user:
- leading number-only tokens at the start of a line are stripped;
- trailing numbers are left untouched (they are often real mm measurements);
- B/H lines are reduced to the bare ``B/H: <width>x <height>`` dimension.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from template_schuchter import (
    _clean_description_lines,
    _extract_description_short,
    _normalize_bh_line,
    _strip_leading_numeric_tokens,
    _strip_trailing_drawing_numbers,
)
from extractor import extract_pdf_text
from parser import parse_document_text
from main import _build_amount_line_rows, _build_line_item_rows
from image_assignment import image_within_item_vertical_window, metadata_dict
from validation import build_document_validation
from vendoc_exporter import build_vendoc_payload

LEADING_NUMBER_LEAK = re.compile(r"^\s*\d[\d.,:]*\s+\S")


# --- leading number-token stripping ----------------------------------------

def test_strip_leading_numbers_handles_dragan_examples() -> None:
    # Lines reconstructed from Dragan's screenshot of document #25 (pos 1/2).
    assert _strip_leading_numeric_tokens("11.22.23 flache Thermobodenschwelle") == "flache Thermobodenschwelle"
    assert _strip_leading_numeric_tokens("22002200 3xEsg Glas") == "3xEsg Glas"
    assert _strip_leading_numeric_tokens("22: B/H:2850x 2200") == "B/H:2850x 2200"
    assert _strip_leading_numeric_tokens("1 600 1-flg.Fenster, DK-Links") == "1-flg.Fenster, DK-Links"
    assert _strip_leading_numeric_tokens("11 22 33 2x Fixteile, gekoppelt") == "2x Fixteile, gekoppelt"
    assert _strip_leading_numeric_tokens("1 2 3 1xSetzholz / 1xStulp") == "1xSetzholz / 1xStulp"


def test_strip_leading_numbers_keeps_legitimate_starts() -> None:
    # Tokens that start with a digit but contain letters must be preserved.
    for line in (
        "1-flg.Fenster, DK-Links",
        "2x Fixteile, gekoppelt",
        "3xEsg Glas",
        "+unten Purenitaufdopplung 130",
        "Esg Glas",
        "B/H: 1000x 600",
    ):
        assert _strip_leading_numeric_tokens(line) == line


def test_strip_leading_numbers_keeps_trailing_numbers() -> None:
    # Trailing sash/measurement numbers are intentionally left untouched.
    assert _strip_leading_numeric_tokens("1 2 Sonderholzbreite bis 110") == "Sonderholzbreite bis 110"
    assert _strip_leading_numeric_tokens("1325 1345 rechts Kopplungsdichtung 4") == "rechts Kopplungsdichtung 4"


# --- B/H normalization ------------------------------------------------------

def test_normalize_bh_line_cuts_trailing_coordinates() -> None:
    assert _normalize_bh_line("B/H: 2678x 1400 2600 78") == "B/H: 2678x 1400"
    assert _normalize_bh_line("B/H: 3040x 1400 2962 78") == "B/H: 3040x 1400"


def test_normalize_bh_line_keeps_clean_dimensions_and_real_words() -> None:
    assert _normalize_bh_line("B/H: 1000x 600") == "B/H: 1000x 600"
    assert _normalize_bh_line("B/H:2850x 2200") == "B/H:2850x 2200"
    assert _normalize_bh_line("Esg Glas") == "Esg Glas"
    # A real word after the dimension must not be dropped.
    assert _normalize_bh_line("B/H: 1000x 600 innen") == "B/H: 1000x 600 innen"


# --- trailing drawing-dimension stripping ----------------------------------

def test_strip_trailing_drawing_numbers_cuts_dimension_pairs() -> None:
    # The "965 1000" pair comes from the drawing and must go (short and long).
    assert _strip_trailing_drawing_numbers("2-flg.Fenster, D/DK-Stulp 965 1000 .") == "2-flg.Fenster, D/DK-Stulp"
    assert _strip_trailing_drawing_numbers("2-flg.Fenster, D/DK-Stulp 965 1000") == "2-flg.Fenster, D/DK-Stulp"
    assert _strip_trailing_drawing_numbers("1-flg.Fenster, DK-Rechts 685 720") == "1-flg.Fenster, DK-Rechts"


def test_strip_trailing_drawing_numbers_cuts_single_sash_number() -> None:
    # A single one-digit trailing number is a sash/flap number (from the drawing).
    assert _strip_trailing_drawing_numbers("1-flg.Fenster, DK-Rechts 1") == "1-flg.Fenster, DK-Rechts"
    assert _strip_trailing_drawing_numbers("Fixteil 1") == "Fixteil"


def test_strip_trailing_drawing_numbers_keeps_single_spec_numbers() -> None:
    # Single trailing numbers are real specs/measurements and must be kept.
    assert _strip_trailing_drawing_numbers("+unten Purnitaudopplung 200") == "+unten Purnitaudopplung 200"
    assert _strip_trailing_drawing_numbers("Sonderholzbreite bis 110") == "Sonderholzbreite bis 110"
    assert _strip_trailing_drawing_numbers("B/H: 1500x 1000") == "B/H: 1500x 1000"
    assert _strip_trailing_drawing_numbers("1-flg.Türe, DK-Rechts") == "1-flg.Türe, DK-Rechts"


def test_strip_trailing_drawing_numbers_cuts_glued_dimension_pairs() -> None:
    # A trailing run of 6+ bare digits is a drawing dimension pair glued without
    # a space (e.g. "2300"+"2300" -> "23002300"); it bleeds from the sketch and
    # must go, while real <=4-digit spec/measurement values are kept.
    assert _strip_trailing_drawing_numbers("+unten Blindaufdopplung 23002300") == "+unten Blindaufdopplung"
    assert _strip_trailing_drawing_numbers("gekoppelt 23002300") == "gekoppelt"
    # Guard: 2-4 digit trailing values stay (specs + B/H heights).
    assert _strip_trailing_drawing_numbers("unten Blindaufdopplung 60") == "unten Blindaufdopplung 60"
    assert _strip_trailing_drawing_numbers("B/H: 830x 2245") == "B/H: 830x 2245"


def test_extract_description_short_drops_trailing_dimensions() -> None:
    block = ["HEADER", "1 2 2-flg.Fenster, D/DK-Stulp 965 1000 ."]
    assert _extract_description_short(block, fallback="x") == "2-flg.Fenster, D/DK-Stulp"


# --- end-to-end on the cleaning function -----------------------------------

def test_clean_description_lines_strips_leading_and_trailing_drawing_numbers() -> None:
    block = [
        "HEADER (skipped)",
        "1 600 1-flg.Fenster, DK-Links",
        "B/H: 1000x 600",
        "Fixteil 1",
        "893.3 839.3 867.3 78 B/H: 2678x 1400 2600 78",
    ]
    assert _clean_description_lines(block) == [
        "1-flg.Fenster, DK-Links",
        "B/H: 1000x 600",
        "Fixteil",  # trailing single sash number removed
        "B/H: 2678x 1400",
    ]


# --- integration against a real sample -------------------------------------

def _schuchter_long_texts(pdf_name: str) -> list[str]:
    pdf = ROOT / "samples/pdfs/candidates/offers/schuchter" / pdf_name
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


def test_schuchter_sample_first_position_long_text_is_clean() -> None:
    long_texts = _schuchter_long_texts("schuchter__angebot__A260151.pdf")
    # The room label (lv_pos, here "KG") is prepended as the first line.
    assert long_texts[0] == "KG\n1-flg.Fenster, DK-Links\nB/H: 1000x 600"


def test_schuchter_room_label_prepended_to_long_text() -> None:
    # Dragan needs the room/location label in the VenDoc import; SCHUCHTER keeps
    # it in lv_pos (e.g. "KG", "EG: T1"), which the payload otherwise drops. It
    # must lead the long text without disturbing the description below it.
    long_texts = _schuchter_long_texts("schuchter__angebot__A260151.pdf")
    assert long_texts[0].startswith("KG\n")
    assert long_texts[1].startswith("EG: T1\n")
    assert long_texts[1] == "EG: T1\n1-flg.Fenster, DK-Links\nB/H: 800x 1000"


def test_schuchter_same_page_positions_get_ordered_image_windows() -> None:
    # A260172 page 5 holds Pos 10-13, each with its own sketch. Without accurate
    # vertical anchors the matcher swapped the two near-square sketches of Pos 11
    # and 12 (Dragan). PDF-coordinate layout hints give each position its own
    # vertical window, so four sketches (top->bottom) map 1:1 to the positions.
    pdf = ROOT / "samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260172.pdf"
    text = extract_pdf_text(pdf)
    rows = _build_line_item_rows(text, "schuchter", source_path=pdf)
    by_pos = {str(row["position_no"]): row for row in rows}

    page5 = ["10", "11", "12", "13"]
    tops = [metadata_dict(by_pos[p]).get("item_top_ratio") for p in page5]
    assert all(top is not None for top in tops)
    assert tops == sorted(tops)  # anchors increase down the page

    # Four sketches ordered top->bottom must map to the four positions 1:1.
    centers = [0.20, 0.38, 0.55, 0.75]
    images = [
        {"id": 900 + i, "page_ref": 5, "width": 200, "height": 200,
         "metadata_json": {"center_y_ratio": center}}
        for i, center in enumerate(centers)
    ]
    for pos, expected in zip(page5, images):
        candidates = [img["id"] for img in images if image_within_item_vertical_window(by_pos[pos], img)]
        assert candidates == [expected["id"]], f"Pos {pos} -> {candidates}"


def test_schuchter_kopplungselement_label_only_in_long_text() -> None:
    # A260344 Pos 1 is a priced "Kopplungselement bestehend aus: Pos.1a+1b+1c"
    # aggregate. Its label must appear in the long text only; the Kurztext stays
    # empty so it is not duplicated on the printed export. The position keeps its
    # price and is not turned informational.
    pdf = ROOT / "samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260344.pdf"
    text = extract_pdf_text(pdf)
    parsed = parse_document_text(text)
    amount_rows = _build_amount_line_rows(text, parsed["totals"], template=parsed["template"])
    rows = _build_line_item_rows(text, parsed["template"], source_path=pdf, amount_line_rows=amount_rows)
    by_pos = {str(row.get("position_no")): row for row in rows}

    koppel = by_pos["1"]
    assert koppel["description_short"] == ""
    assert (koppel["description_long"] or "").startswith("Kopplungselement bestehend aus:")
    assert "Pos.1a+1b+1c" in koppel["description_long"]
    assert koppel["line_total"] is not None and koppel["line_total"] > 0

    validation = build_document_validation(
        document={
            "supplier_name": parsed["supplier_name"],
            "document_type": parsed["document_type"],
            "document_number": parsed["document_number"],
            "document_date": "2026-03-25",
            "project_ref": parsed.get("project_ref"),
            "currency": "EUR",
            "customer_name": "Testkunde",
            "net_total": (parsed["totals"].get("net_total") or "").replace(".", "").replace(",", "."),
            "vat_total": (parsed["totals"].get("vat_total") or "").replace(".", "").replace(",", "."),
            "gross_total": (parsed["totals"].get("gross_total") or "").replace(".", "").replace(",", "."),
            "parse_confidence": "0.99",
        },
        amount_lines=amount_rows,
        line_items=rows,
        images=[],
    )
    # Blanking the Kurztext must not raise a "Kurzbeschreibung fehlt" warning:
    # the label lives in the long text, so no line-item warning is expected.
    assert validation["status"] == "auto_accept"
    assert validation["line_item_summary"]["warning_count"] == 0


def test_schuchter_samples_have_no_leading_number_leaks() -> None:
    # A260079 carries the coordinate-heavy coupling lines; A260151 the leading
    # sash numbers. Neither may leak a line that starts with a bare number.
    for pdf_name in ("schuchter__angebot__A260079.pdf", "schuchter__angebot__A260151.pdf"):
        for long_text in _schuchter_long_texts(pdf_name):
            for line in long_text.splitlines():
                assert not LEADING_NUMBER_LEAK.match(line), f"leak in {pdf_name}: {line!r}"
