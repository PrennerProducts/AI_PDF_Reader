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
    assert long_texts[0] == "1-flg.Fenster, DK-Links\nB/H: 1000x 600"


def test_schuchter_samples_have_no_leading_number_leaks() -> None:
    # A260079 carries the coordinate-heavy coupling lines; A260151 the leading
    # sash numbers. Neither may leak a line that starts with a bare number.
    for pdf_name in ("schuchter__angebot__A260079.pdf", "schuchter__angebot__A260151.pdf"):
        for long_text in _schuchter_long_texts(pdf_name):
            for line in long_text.splitlines():
                assert not LEADING_NUMBER_LEAK.match(line), f"leak in {pdf_name}: {line!r}"
