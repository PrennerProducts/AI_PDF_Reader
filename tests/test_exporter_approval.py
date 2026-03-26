import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from exporter import build_export_content


def _sample_result() -> dict:
    return {
        "document": {
            "id": 33,
            "source_file": "/tmp/sample.pdf",
            "original_filename": "sample.pdf",
            "file_size_bytes": 123,
            "content_type": "application/pdf",
            "supplier_name": "alu-one Metallbaupartner GmbH",
            "document_type": "angebot",
            "offer_reference": None,
            "document_number": "C2509283TB",
            "document_date": "2025-11-10",
            "project_ref": "Kinderhotel Felben",
            "currency": "EUR",
            "net_total": "16984.29",
            "vat_total": "3396.86",
            "gross_total": "20381.15",
            "parse_confidence": "0.9900",
            "approval_status": "approved",
            "reviewed_by": "Daniela",
            "reviewed_at": "2026-03-26T10:00:00Z",
            "approval_note": "Freigegeben",
            "status": "processed",
            "error_message": None,
            "raw_text_path": "/tmp/sample.txt",
            "created_at": "2026-03-26T10:00:00Z",
            "updated_at": "2026-03-26T10:05:00Z",
        },
        "amount_lines": [],
        "line_items": [
            {
                "position_no": "001",
                "lv_pos": None,
                "is_alternative": False,
                "quantity": "1.0000",
                "unit": "Stk",
                "width_mm": "860.00",
                "height_mm": "2180.00",
                "page_ref": 3,
                "description_short": "Türelement",
                "unit_price": "1900.59",
                "line_total": "1900.59",
                "confidence": "0.8500",
                "image_count": 1,
                "image_ids": [2952],
                "metadata_json": {"review_checked": True},
            }
        ],
        "images": [],
        "validation": {},
    }


def test_csv_export_includes_document_approval_fields() -> None:
    _ext, _media_type, content = build_export_content(_sample_result(), "csv")

    assert "approval_status" in content
    assert "reviewed_by" in content
    assert "reviewed_at" in content
    assert "approval_note" in content
    assert "approved" in content
    assert "Daniela" in content
    assert "Freigegeben" in content


def test_sql_export_includes_document_approval_columns() -> None:
    _ext, _media_type, content = build_export_content(_sample_result(), "sql")

    assert "approval_status" in content
    assert "reviewed_by" in content
    assert "reviewed_at" in content
    assert "approval_note" in content
    assert "'approved'" in content
    assert "'Daniela'" in content
