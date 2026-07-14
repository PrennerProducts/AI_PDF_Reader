"""Position-image crop must extend to the 'Bezeichnung' column (not a fixed pt).

Dragan reported that SCHUCHTER position drawings clipped their rightmost
dimensions. The crop's right edge was a fixed constant (220pt); it now follows
the start of the table's 'Bezeichnung' column so the dimensions (which sit just
left of that column) are kept. See docs/prds/0002-image-dimension-crop.md.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import fitz
from PIL import Image

from extractor import (
    VECTOR_RENDER_SCALE,
    _description_column_left_pt,
    _position_line_art_boxes,
    _technical_line_art_bbox,
)


class _FakeRect:
    def __init__(self, width: float, height: float) -> None:
        self.width = width
        self.height = height


class _FakePage:
    def __init__(self, words: list, width: float = 595.0, height: float = 842.0) -> None:
        self._words = words
        self.rect = _FakeRect(width, height)

    def get_text(self, kind: str):  # noqa: ARG002 - signature parity with fitz
        return self._words


def test_description_column_left_pt_finds_header_x() -> None:
    words = [
        (26.0, 360.0, 60.0, 372.0, "Pos."),
        (244.8, 360.0, 320.0, 372.0, "Bezeichnung"),
        (400.0, 360.0, 470.0, 372.0, "Einzelpreis"),
    ]
    assert round(_description_column_left_pt(_FakePage(words), 595.0), 1) == 244.8


def test_description_column_left_pt_guards_implausible_matches() -> None:
    # Too far left (within the position columns) or too far right -> ignored.
    assert _description_column_left_pt(_FakePage([(100.0, 0, 0, 0, "Bezeichnung")]), 595.0) is None
    assert _description_column_left_pt(_FakePage([(500.0, 0, 0, 0, "Bezeichnung")]), 595.0) is None
    assert _description_column_left_pt(_FakePage([(40.0, 0, 0, 0, "Pos.")]), 595.0) is None


def test_schuchter_position_crop_reaches_description_column() -> None:
    pdf = ROOT / "samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260396.pdf"
    document = fitz.open(str(pdf))
    try:
        for page_index in range(document.page_count):
            page = document[page_index]
            desc_left = _description_column_left_pt(page, page.rect.width)
            if desc_left is None:
                continue
            pixmap = page.get_pixmap(matrix=fitz.Matrix(VECTOR_RENDER_SCALE, VECTOR_RENDER_SCALE))
            rendered = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            boxes = _position_line_art_boxes(page, rendered)
            if not boxes:
                continue
            scale_x = rendered.width / page.rect.width
            right_pt = boxes[0][2] / scale_x
            # Wider than the old fixed 220pt, and capped at the Bezeichnung column.
            assert right_pt > 230.0
            assert right_pt <= desc_left + 1.0
            return
    finally:
        document.close()
    raise AssertionError("no SCHUCHTER page with both positions and a Bezeichnung header")


def test_schuchter_refinement_keeps_right_dimensions() -> None:
    # A260172 Pos 3 is a wide, short window whose right-hand height dimensions
    # ("685"/"720" plus their vertical lines) were clipped: the content
    # refinement tracked only long ruled strokes and dropped the thin dimension
    # marks, zooming into the drawing. Because the crop is bounded by the
    # Bezeichnung column, the refinement must keep the rightmost content instead.
    pdf = ROOT / "samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260172.pdf"
    document = fitz.open(str(pdf))
    try:
        recovered_any = False
        for page_index in range(document.page_count):
            page = document[page_index]
            if _description_column_left_pt(page, page.rect.width) is None:
                continue
            pixmap = page.get_pixmap(matrix=fitz.Matrix(VECTOR_RENDER_SCALE, VECTOR_RENDER_SCALE))
            rendered = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            for box in _position_line_art_boxes(page, rendered):
                raw = rendered.crop(box)
                kept = _technical_line_art_bbox(raw, preserve_right_dimensions=True)
                trimmed = _technical_line_art_bbox(raw, preserve_right_dimensions=False)
                if kept is None or trimmed is None:
                    continue
                # Preserving never crops further right than the run-based bbox.
                assert kept[2] >= trimmed[2]

                gray = raw.convert("L")
                pixels = gray.load()
                crop_w, crop_h = gray.size
                band_top = max(0, kept[1])
                band_bottom = min(crop_h, kept[3])
                rightmost_dark = -1
                for x in range(crop_w - 1, -1, -1):
                    if any(pixels[x, y] < 245 for y in range(band_top, band_bottom)):
                        rightmost_dark = x
                        break
                if rightmost_dark < 0:
                    continue
                # The preserved bbox always covers the rightmost real content
                # (the dimensions), which the run-based bbox may clip off.
                assert kept[2] >= rightmost_dark
                if trimmed[2] < rightmost_dark - 4:
                    recovered_any = True
        assert recovered_any, "expected at least one clipped right dimension to be recovered"
    finally:
        document.close()
