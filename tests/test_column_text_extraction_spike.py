"""SPIKE (ADR 0003): column-aware position-text extraction for SCHUCHTER.

These tests are **additive and off-by-default**. They exercise ``api/column_text``
— a self-contained module that nothing in the production parse path imports — to
prove the target architecture of ADR 0003: reading the position description
directly from the table's *Bezeichnung* column (between its left x and the price
column's left x) so that drawing dimensions (left columns) and prices (right
columns) *never enter the text* in the first place.

The assertions check the column-extracted text **directly**, without calling any
of the production regex cleaners (``_strip_leading_numeric_tokens``,
``_normalize_bh_line``, ``_strip_trailing_drawing_numbers``). The point is the
geometric guarantee, not a post-hoc clean-up:

- no price tokens (``€`` or ``1.234,56``) in any position description line;
- no trailing dimension pair (2+ trailing bare numbers — drawing maße);
- no trailing lone single-digit sash/flap number;
- no *leading*-bare-number leak from the left drawing column on the two samples
  Dragan flagged (A260079: coupling coordinates; A260151: leading sash numbers);
- positive: real description words survive (Fenster / Glas / a ``B/H:`` line).

Known, intentional finding (documented, not asserted away): some samples carry
genuine *Bezeichnung-column* content that begins with a number — RAL colour
codes (``7016 matt glatt``) and element/room IDs (``511101 A``). These sit at the
Bezeichnung column-left, i.e. they are real content, not column bleed; the
production regex would have stripped them. The column approach correctly keeps
them, so the leading-number assertion is scoped to the reported-leak samples.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from column_text import document_description_blocks, document_description_lines

SCHUCHTER_DIR = ROOT / "samples/pdfs/candidates/offers/schuchter"

ALL_SAMPLES = (
    "schuchter__angebot__A260079.pdf",
    "schuchter__angebot__A260151.pdf",
    "schuchter__angebot__A260172.pdf",
    "schuchter__angebot__A260343.pdf",
    "schuchter__angebot__A260344.pdf",
    "schuchter__angebot__A260396.pdf",
)
# Samples where leading-number column bleed from the drawing was reported.
REPORTED_LEAK_SAMPLES = (
    "schuchter__angebot__A260079.pdf",
    "schuchter__angebot__A260151.pdf",
)

PRICE_RE = re.compile(r"€|\d{1,3}(?:\.\d{3})*,\d{2}")
LEADING_NUMBER_LEAK = re.compile(r"^\s*\d[\d.,:]*\s+\S")
TRAILING_DIMENSION_PAIR = re.compile(r"(?:\s+\d+(?:[.,]\d+)?){2,}\s*[.\-]*\s*$")
TRAILING_SINGLE_SASH = re.compile(r"\s+\d\s*[.\-]*\s*$")


def _lines(pdf_name: str) -> list[str]:
    return document_description_lines(str(SCHUCHTER_DIR / pdf_name))


# --- the column band is geometrically clean of the right-column maße/preise ---

def test_no_price_tokens_in_any_sample() -> None:
    for pdf_name in ALL_SAMPLES:
        for line in _lines(pdf_name):
            assert not PRICE_RE.search(line), f"price leak in {pdf_name}: {line!r}"


def test_no_trailing_dimension_pairs_in_any_sample() -> None:
    # A "B/H: 1000x 600" line legitimately ends in two numbers; that is the one
    # allowed dimension form, so it is excluded from the trailing-pair check.
    for pdf_name in ALL_SAMPLES:
        for line in _lines(pdf_name):
            if line.lstrip().lower().startswith("b/h:"):
                continue
            assert not TRAILING_DIMENSION_PAIR.search(line), f"maße leak in {pdf_name}: {line!r}"


def test_no_trailing_single_sash_number_in_any_sample() -> None:
    for pdf_name in ALL_SAMPLES:
        for line in _lines(pdf_name):
            if line.lstrip().lower().startswith("b/h:"):
                continue
            assert not TRAILING_SINGLE_SASH.search(line), f"sash leak in {pdf_name}: {line!r}"


def test_no_leading_number_leak_on_reported_samples() -> None:
    # On the two flagged offers there is no genuine number-leading Bezeichnung
    # content, so every leading bare number would be a drawing-column bleed.
    for pdf_name in REPORTED_LEAK_SAMPLES:
        for line in _lines(pdf_name):
            assert not LEADING_NUMBER_LEAK.match(line), f"leading leak in {pdf_name}: {line!r}"


# --- real description content survives --------------------------------------

def test_real_description_words_survive() -> None:
    lines = _lines("schuchter__angebot__A260151.pdf")
    assert any("Fenster" in line for line in lines)
    assert any("Glas" in line for line in lines)
    assert any(line.lstrip().lower().startswith("b/h:") for line in lines)


def test_first_position_block_reads_as_a_clean_description() -> None:
    blocks = document_description_blocks(str(SCHUCHTER_DIR / "schuchter__angebot__A260151.pdf"))
    assert blocks, "expected at least one position block"
    first = blocks[0]
    assert any("Fenster" in line for line in first), first
    assert any(line.lower().startswith("b/h:") for line in first), first
    # No price / dimension-pair bleed in the first block.
    for line in first:
        assert not PRICE_RE.search(line), first


# --- the band keeps genuine numeric Bezeichnung content (documented finding) --

def test_band_preserves_genuine_numeric_element_ids() -> None:
    # A260396 carries element IDs like "511101 A" *in* the Bezeichnung column;
    # the column approach keeps them (the production regex would strip them).
    lines = _lines("schuchter__angebot__A260396.pdf")
    assert any(re.match(r"^5111\d\d\b", line) for line in lines), "expected element IDs preserved"
