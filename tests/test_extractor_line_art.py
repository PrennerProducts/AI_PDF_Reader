import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from extractor import (
    _crop_content_metrics,
    _line_art_metrics,
    _looks_like_position_line_art,
    _position_line_art_boxes,
    _technical_line_art_bbox,
    extract_pdf_images,
)


class _FakeRect:
    width = 600.0
    height = 800.0


class _FakePage:
    rect = _FakeRect()

    def __init__(self, blocks: list[tuple[float, float, float, float, str]]) -> None:
        self._blocks = blocks

    def get_text(self, mode: str):
        assert mode == "blocks"
        return self._blocks


def test_position_line_art_accepts_window_sketch() -> None:
    image = Image.new("RGB", (240, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((35, 30, 185, 205), outline="black", width=3)
    draw.line((110, 30, 110, 205), fill="black", width=3)
    draw.line((35, 30, 110, 205), fill="black", width=2)
    draw.line((185, 30, 110, 205), fill="black", width=2)
    draw.line((25, 220, 195, 220), fill="black", width=2)
    draw.line((205, 30, 205, 205), fill="black", width=2)

    crop_metrics = _crop_content_metrics(image)
    line_metrics = _line_art_metrics(image)

    assert _looks_like_position_line_art(image, crop_metrics, line_metrics) is True


def test_position_line_art_rejects_text_separator_only() -> None:
    image = Image.new("RGB", (240, 180), "white")
    draw = ImageDraw.Draw(image)
    for y in (30, 70, 110):
        draw.line((25, y, 215, y), fill="black", width=2)
    for x in range(35, 190, 26):
        draw.line((x, 140, x + 10, 140), fill="black", width=2)
        draw.line((x, 152, x + 14, 152), fill="black", width=2)

    crop_metrics = _crop_content_metrics(image)
    line_metrics = _line_art_metrics(image)

    assert _looks_like_position_line_art(image, crop_metrics, line_metrics) is False


def test_technical_line_art_bbox_removes_position_header() -> None:
    image = Image.new("RGB", (360, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.line((30, 25, 300, 25), fill="black", width=2)
    draw.text((35, 55), "Pos.", fill="black")
    draw.text((35, 75), "2", fill="black")
    draw.text((230, 75), "1 Stck", fill="black")
    draw.rectangle((70, 110, 180, 190), outline="black", width=3)
    draw.line((125, 110, 125, 190), fill="black", width=2)
    draw.line((70, 110, 125, 190), fill="black", width=2)
    draw.line((180, 110, 125, 190), fill="black", width=2)
    draw.line((60, 210, 190, 210), fill="black", width=2)
    draw.text((80, 218), "1485", fill="black")
    draw.line((235, 110, 235, 190), fill="black", width=2)
    draw.text((245, 145), "1225", fill="black")

    bbox = _technical_line_art_bbox(image)

    assert bbox is not None
    assert bbox[1] > 80
    assert bbox[3] > 220


def test_technical_line_art_bbox_keeps_right_side_dimension_text() -> None:
    image = Image.new("RGB", (430, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((35, 30, 270, 200), outline="black", width=2)
    draw.line((120, 30, 120, 200), fill="black", width=2)
    draw.line((200, 30, 200, 200), fill="black", width=2)
    draw.line((305, 30, 305, 200), fill="black", width=2)
    draw.text((323, 110), "2200", fill="black")
    draw.line((35, 220, 270, 220), fill="black", width=2)
    draw.text((132, 228), "2850", fill="black")

    bbox = _technical_line_art_bbox(image)

    assert bbox is not None
    assert bbox[2] >= 350


def test_technical_line_art_bbox_keeps_immediate_view_label() -> None:
    image = Image.new("RGB", (260, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((45, 30, 165, 160), outline="black", width=2)
    draw.line((45, 30, 165, 160), fill="black", width=2)
    draw.line((165, 30, 45, 160), fill="black", width=2)
    draw.line((42, 182, 168, 182), fill="black", width=2)
    draw.text((80, 190), "800", fill="black")
    draw.text((48, 212), "(Innenansicht)", fill="black")

    bbox = _technical_line_art_bbox(image)

    assert bbox is not None
    assert bbox[3] >= 232


def test_technical_line_art_bbox_keeps_view_label_with_larger_gap() -> None:
    image = Image.new("RGB", (300, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((45, 30, 185, 170), outline="black", width=2)
    draw.line((45, 30, 185, 170), fill="black", width=2)
    draw.line((185, 30, 45, 170), fill="black", width=2)
    draw.line((42, 198, 188, 198), fill="black", width=2)
    draw.text((92, 206), "1200", fill="black")
    draw.text((48, 248), "(Innenansicht)", fill="black")
    draw.text((230, 250), "Rahmenfarbe", fill="black")

    bbox = _technical_line_art_bbox(image)

    assert bbox is not None
    assert bbox[2] < 230
    assert bbox[3] >= 268


def test_technical_line_art_bbox_ignores_following_alternative_heading() -> None:
    image = Image.new("RGB", (360, 760), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 60, 140, 250), outline="black", width=3)
    draw.line((70, 60, 140, 250), fill="black", width=2)
    draw.line((140, 60, 70, 250), fill="black", width=2)
    draw.line((55, 275, 160, 275), fill="black", width=2)
    draw.text((82, 284), "1000", fill="black")
    draw.line((190, 60, 190, 250), fill="black", width=2)
    draw.text((202, 130), "2500", fill="black")
    draw.line((60, 625, 250, 625), fill="black", width=2)
    draw.text((60, 645), "Alternative:", fill="red")
    draw.line((60, 667, 165, 667), fill="red", width=2)

    bbox = _technical_line_art_bbox(image)

    assert bbox is not None
    assert bbox[3] < 380


def test_position_line_art_boxes_use_text_separators_for_last_block() -> None:
    page = _FakePage(
        [
            (43.2, 72.1, 532.7, 155.5, "Pos.\n103\n2 Stck\nB/H: 915x 1120"),
            (
                43.2,
                204.1,
                489.5,
                335.4,
                "------------------------------------------------------------\nPos.\n104\n2 Stck\nB/H: 915x 2065",
            ),
            (
                43.2,
                408.1,
                489.5,
                491.4,
                "------------------------------------------------------------\nPos.\n105\n2 Stck\nB/H: 915x 2065",
            ),
            (
                43.2,
                552.1,
                489.5,
                635.4,
                "------------------------------------------------------------\nPos.\n106\n2 Stck\nB/H: 915x 1120",
            ),
            (57.6, 684.1, 489.5, 695.4, "------------------------------------------------------------"),
        ]
    )
    rendered = Image.new("RGB", (1200, 1600), "white")

    boxes = _position_line_art_boxes(page, rendered)

    assert len(boxes) == 4
    assert boxes[-1][3] == 1356


def test_schuchter_vector_line_art_extracts_position_crops(tmp_path: Path) -> None:
    pdf_path = ROOT / "samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260172.pdf"
    if not pdf_path.exists():
        return

    rows = extract_pdf_images(pdf_path, tmp_path / "images")
    line_art_rows = [
        row
        for row in rows
        if (row.get("metadata_json") or {}).get("layout_source") == "vector_position_line_art"
    ]

    assert len(line_art_rows) == 13


def test_rekord_continuation_page_sketches_are_extracted(tmp_path: Path) -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/rekord_vomp/Angebot_VAX60326.pdf"
    if not pdf_path.exists():
        return

    rows = extract_pdf_images(pdf_path, tmp_path / "images")
    line_art_rows = [
        row
        for row in rows
        if (row.get("metadata_json") or {}).get("layout_source")
        in {"vector_position_line_art", "vector_strip_band"}
    ]

    page_8_rows = [row for row in line_art_rows if row.get("page_ref") == 8]
    page_10_rows = [row for row in line_art_rows if row.get("page_ref") == 10]

    assert len(line_art_rows) == 12
    assert [row["metadata_json"]["layout_source"] for row in page_8_rows] == [
        "vector_strip_band",
        "vector_position_line_art",
    ]
    assert [row["metadata_json"]["layout_source"] for row in page_10_rows] == ["vector_strip_band"]


def test_newo_embedded_product_images_do_not_get_vector_duplicates(tmp_path: Path) -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/newo/AN NEWO BVH Projekt 353 Achhorner.pdf"
    if not pdf_path.exists():
        return

    rows = extract_pdf_images(pdf_path, tmp_path / "images")
    page_three_rows = [row for row in rows if row.get("page_ref") == 3]
    page_three_sources = [
        (row.get("metadata_json") or {}).get("layout_source")
        for row in page_three_rows
    ]

    assert page_three_sources.count("fitz_image_block") == 2
    assert "vector_strip_band" not in page_three_sources


def test_entholzer_header_images_do_not_suppress_position_sketches(tmp_path: Path) -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/entholzer/Angebot 12600422.00 Bernsteiner.pdf"
    if not pdf_path.exists():
        return

    rows = extract_pdf_images(pdf_path, tmp_path / "images")
    sources = [(row.get("metadata_json") or {}).get("layout_source") for row in rows]
    header_like_rows = [
        row
        for row in rows
        if (row.get("metadata_json") or {}).get("top_ratio", 1) <= 0.14
        and (row.get("metadata_json") or {}).get("width_ratio", 0) >= 0.65
    ]
    page_two_rows = [row for row in rows if row.get("page_ref") == 2]

    assert len(rows) == 20
    assert sources.count("vector_position_line_art") == 17
    assert not header_like_rows
    assert [row["metadata_json"]["layout_source"] for row in page_two_rows] == [
        "vector_position_line_art",
        "vector_position_line_art",
    ]
    assert all(
        (row.get("metadata_json") or {}).get("line_art_refined_crop") is True
        for row in rows
        if (row.get("metadata_json") or {}).get("layout_source") == "vector_position_line_art"
    )
