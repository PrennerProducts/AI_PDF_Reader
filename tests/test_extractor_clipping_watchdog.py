"""Clipping watchdog for position images (PRD 0002 stage 2).

`_edge_content_ratios` measures how much non-white content sits in each edge
band of a crop. Run on the RAW crop box (before trim/pad), a high right-edge
ratio means the drawing runs up to the box's right edge — a sign the box may
have clipped the rightmost dimensions (the bug PRD 0002 is about).

Finding from the current sample corpus: SCHUCHTER position crops (right edge =
the 'Bezeichnung' column, per the stage-1 fix) leave the right band nearly
white, i.e. the drawings + their rightmost dimensions are contained, not
clipped. The originally reported case (doc #585) is not in the sample set, so
this stays a regression guard rather than a reproduction.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import fitz
from PIL import Image, ImageDraw

from extractor import (
    VECTOR_RENDER_SCALE,
    _edge_content_ratios,
    _position_line_art_boxes,
)


# --- metric correctness (synthetic) ----------------------------------------

def test_edge_ratios_blank_image_is_all_zero() -> None:
    blank = Image.new("RGB", (100, 100), "white")
    assert _edge_content_ratios(blank, 6) == {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0}


def test_edge_ratios_detects_content_at_right_edge() -> None:
    img = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(img).rectangle([94, 0, 99, 99], fill="black")  # rightmost 6 px
    ratios = _edge_content_ratios(img, 6)
    assert ratios["right"] > 0.9
    assert ratios["left"] == 0.0
    # only the corners of the black bar fall into the top/bottom bands
    assert ratios["top"] < 0.2 and ratios["bottom"] < 0.2


def test_edge_ratios_centered_content_keeps_clean_margins() -> None:
    img = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(img).rectangle([40, 40, 60, 60], fill="black")
    assert max(_edge_content_ratios(img, 6).values()) == 0.0


# --- cross-supplier watchdog over real samples -----------------------------

def _schuchter_position_crops():
    margin_px = round(3 * VECTOR_RENDER_SCALE)
    for pdf in sorted((ROOT / "samples/pdfs/candidates/offers/schuchter").glob("*.pdf")):
        document = fitz.open(str(pdf))
        try:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(VECTOR_RENDER_SCALE, VECTOR_RENDER_SCALE), alpha=False)
                rendered = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                for box in _position_line_art_boxes(page, rendered):
                    yield pdf.name, box, _edge_content_ratios(rendered.crop(box), margin_px)
        finally:
            document.close()


def test_schuchter_position_crops_do_not_clip_the_right_edge() -> None:
    crops = list(_schuchter_position_crops())
    assert crops, "expected SCHUCHTER position line-art boxes in the samples"
    worst_name, _box, worst = max(crops, key=lambda item: item[2]["right"])
    # The right edge stays essentially white: the drawing + rightmost dimensions
    # sit inside the Bezeichnung-column boundary instead of being clipped.
    assert worst["right"] < 0.12, f"{worst_name}: right-edge content {worst['right']:.3f} suggests clipping"
