import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from vendoc_exporter import build_vendoc_payload, external_document_id, external_line_item_id


def _sample_result(image_path: Path) -> dict:
    return {
        "document": {
            "id": 33,
            "supplier_name": "alu-one Metallbaupartner GmbH",
            "document_type": "angebot",
            "document_number": "C2509283TB",
            "offer_reference": None,
            "document_date": "2025-11-10",
            "project_ref": "Kinderhotel Felben",
            "currency": "EUR",
            "net_total": "16984.29",
            "vat_total": "3396.86",
            "gross_total": "20381.15",
            "approval_status": "approved",
            "status": "processed",
        },
        "line_items": [
            {
                "id": 77,
                "position_no": "001",
                "lv_pos": None,
                "is_alternative": False,
                "quantity": "1.0000",
                "unit": "Stk",
                "width_mm": "860.00",
                "height_mm": "2180.00",
                "page_ref": 3,
                "description_short": "Tuerelement",
                "description_long": "Tuerelement mit Seitenteil",
                "unit_price": "1900.59",
                "line_total": "1900.59",
                "image_ids_primary": [2952],
                "image_ids": [2952],
                "metadata_json": {"referenced_lv_pos": "57.05.21.A"},
            }
        ],
        "images": [
            {
                "id": 2952,
                "page_ref": 3,
                "image_index": 1,
                "mime_type": "image/png",
                "storage_path": str(image_path),
            }
        ],
    }


def test_vendoc_payload_maps_header_positions_and_primary_image(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    image_path.write_bytes(b"fake-image")

    payload = build_vendoc_payload(_sample_result(image_path))

    assert payload["errors"] == []
    assert payload["summary"]["position_count"] == 1
    assert payload["header"]["external_document_id"] == external_document_id(33)
    assert payload["header"]["source_document_id"] == "33"
    assert payload["header"]["supplier_name"] == "alu-one Metallbaupartner GmbH"
    assert payload["header"]["currency_code"] == "EUR"
    assert payload["header"]["net_total"] == 16984.29

    position = payload["positions"][0]
    assert position["external_line_item_id"] == external_line_item_id(33, {"id": 77}, 1)
    assert position["external_document_id"] == payload["header"]["external_document_id"]
    assert position["source_line_item_id"] == "77"
    assert position["position_no"] == "001"
    assert position["quantity"] == 1.0
    assert position["unit_code"] == "Stk"
    assert position["image_mime_type"] == "image/png"
    assert position["image_filename"] == "document_33_position_001_image_2952.png"
    assert position["image_base64"] == base64.b64encode(b"fake-image").decode("ascii")
    assert position["image_is_primary"] is True
    assert position["main_line_item_id"] == "57.05.21.A"


def test_vendoc_payload_reports_missing_primary_image_file(tmp_path: Path) -> None:
    payload = build_vendoc_payload(_sample_result(tmp_path / "missing.png"))

    assert payload["errors"] == []
    assert payload["warnings"][0]["code"] == "primary_image_file_missing"
    assert payload["positions"][0]["image_base64"] is None
    assert payload["positions"][0]["image_is_primary"] is False


def test_vendoc_payload_requires_positions() -> None:
    payload = build_vendoc_payload({"document": {"id": 99}, "line_items": [], "images": []})

    assert payload["summary"]["error_count"] == 1
    assert payload["errors"][0]["code"] == "no_positions"
