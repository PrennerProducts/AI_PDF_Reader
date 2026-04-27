import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from extractor import (
    _crop_content_metrics,
    _line_art_metrics,
    _looks_like_position_line_art,
    _technical_line_art_bbox,
    extract_pdf_images,
)


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
