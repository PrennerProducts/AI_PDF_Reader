from pathlib import Path

from extractor import extract_pdf_images, extract_pdf_text
from main import _postprocess_image_rows
from parser import parse_document_text
from template_koch_detail import parse_page_details

ROOT = Path(__file__).resolve().parents[1]


def test_koch_offer_extracts_document_notes_and_suppresses_table_crops(tmp_path: Path) -> None:
    pdf_path = ROOT / "samples/pdfs/candidates/offers/koch/1050824_Angebot.pdf"
    text = extract_pdf_text(pdf_path)
    parsed = parse_document_text(text)

    assert parsed["template"] == "koch"
    assert parsed["document_type"] == "angebot"
    assert parsed["document_notes"]
    assert "Allgemeine Ausführung" in parsed["document_notes"]
    assert "System Niveau" in parsed["document_notes"]

    image_rows = extract_pdf_images(pdf_path, tmp_path / "images")
    assert image_rows
    assert {(row.get("metadata_json") or {}).get("layout_source") for row in image_rows} == {"vector_strip_band"}

    filtered = _postprocess_image_rows(
        image_rows,
        template=parsed["template"],
        document_type=parsed["document_type"],
        extracted_text=text,
    )
    assert filtered == []


def test_koch_detail_pdf_is_detected_and_pages_map_to_positions() -> None:
    pdf_path = ROOT / "samples/pdfs/non_offer/grafik_technik/koch/Detailzeichnungen_Koch.pdf"
    text = extract_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    page_details = parse_page_details(text)

    assert parsed["template"] == "koch_detail"
    assert parsed["supplier_name"] == "Koch Türen GmbH"
    assert parsed["document_type"] == "detailzeichnung"
    assert parsed["document_number"] == "50309"
    assert page_details[1]["source_position_numbers"] == ["1"]
    assert page_details[3]["source_position_numbers"] == ["2"]
    assert page_details[1]["source_detail_type"] == "Visualisierung mit Stockmaßen"


def test_koch_total_without_vat_label_does_not_create_implied_vat() -> None:
    parsed = parse_document_text(
        "\n".join(
            [
                "KOCH TÜREN GMBH",
                "ANGEBOT",
                "Objekt: Danzl Daniel",
                "Angebotsdatum: 29.11.2024",
                "Angebotsnummer: 1046184",
                "Gesamtpreis ohne Mwst.           € 9.361,00",
            ]
        )
    )

    assert parsed["template"] == "koch"
    assert parsed["totals"] == {
        "net_total": "€ 9.361,00",
        "vat_total": None,
        "gross_total": None,
    }
