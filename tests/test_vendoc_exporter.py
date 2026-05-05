import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from vendoc_exporter import build_vendoc_payload, external_document_id, external_line_item_id
from vendoc_mssql import POSITION_COLUMNS, build_srtemp_export_preview, build_srtemp_insert_script
from vendoc_rtf import build_vendoc_long_text_rtf, escape_rtf_text


def _write_png(path: Path) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (2, 1), (255, 0, 0, 255)).save(output, format="PNG")
    payload = output.getvalue()
    path.write_bytes(payload)
    return payload


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
    image_bytes = _write_png(image_path)

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
    assert position["description_long"] == "Tuerelement mit Seitenteil"
    assert position["image_long_text_rtf"].startswith("{\\rtf1")
    assert "\\pngblip" in position["image_long_text_rtf"]
    assert image_bytes.hex() in position["image_long_text_rtf"]
    assert "Tuerelement mit Seitenteil" in position["image_long_text_rtf"]
    assert position["image_is_primary"] is True
    assert position["main_line_item_id"] == "57.05.21.A"


def test_vendoc_payload_reports_missing_primary_image_file(tmp_path: Path) -> None:
    payload = build_vendoc_payload(_sample_result(tmp_path / "missing.png"))

    assert payload["errors"] == []
    assert payload["warnings"][0]["code"] == "primary_image_file_missing"
    assert "\\pngblip" not in payload["positions"][0]["image_long_text_rtf"]
    assert payload["positions"][0]["image_is_primary"] is False


def test_vendoc_payload_requires_positions() -> None:
    payload = build_vendoc_payload({"document": {"id": 99}, "line_items": [], "images": []})

    assert payload["summary"]["error_count"] == 1
    assert payload["errors"][0]["code"] == "no_positions"


def test_vendoc_rtf_escapes_unicode_and_control_characters() -> None:
    assert escape_rtf_text("Maß {A}\\B\nÖ") == "Ma\\u223? \\{A\\}\\\\B\\line \\u214?"


def test_vendoc_rtf_embeds_png_hex(tmp_path: Path) -> None:
    image_path = tmp_path / "sample.png"
    image_bytes = _write_png(image_path)

    rtf = build_vendoc_long_text_rtf("Langtext", image_bytes=image_bytes, image_name="sample.png")

    assert rtf.startswith("{\\rtf1")
    assert "\\pngblip" in rtf
    assert "89504e470d0a1a0a" in rtf
    assert "49454e44ae426082" in rtf
    assert image_bytes.hex() in rtf


def test_srtemp_insert_script_targets_confirmed_image_long_text_schema(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    payload = build_vendoc_payload(_sample_result(image_path))

    script = build_srtemp_insert_script(payload)

    assert "dbo.vendoc_import_headers" in script
    assert "dbo.vendoc_import_positions" in script
    assert "image_long_text_rtf" in script
    assert "\\pngblip" in script
    assert "image_base64" not in script
    assert "image_mime_type" not in script
    assert "image_filename" not in script
    assert POSITION_COLUMNS == [
        "external_line_item_id",
        "external_document_id",
        "source_line_item_id",
        "position_no",
        "item_type",
        "is_alternative",
        "quantity",
        "unit_code",
        "width_mm",
        "height_mm",
        "description_short",
        "description_long",
        "unit_price",
        "page_ref",
        "image_long_text_rtf",
        "image_is_primary",
        "created_at",
        "article_no",
        "discount_1",
        "discount_2",
        "vat_type",
        "unity",
        "main_line_item_id",
    ]


def test_srtemp_preview_uses_runtime_resolved_column_names(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    payload = build_vendoc_payload(_sample_result(image_path))

    def _fake_resolve(cursor=None):
        return {
            "dbo.vendoc_import_headers": [
                ("external_document_id", "external_document_id"),
                ("source_document_id", "source_document_id"),
                ("is_alternative", "is_alternate"),
            ],
            "dbo.vendoc_import_positions": [
                ("external_line_item_id", "external_line_item_id"),
                ("external_document_id", "external_document_id"),
                ("source_line_item_id", "source_line_item_id"),
                ("is_alternative", "is_alternative"),
            ],
        }

    monkeypatch.setattr("vendoc_mssql._resolve_table_bindings", _fake_resolve)

    preview = build_srtemp_export_preview(payload)

    assert preview["header_columns"] == [
        "external_document_id",
        "source_document_id",
        "is_alternative",
    ]
    assert "INSERT INTO dbo.vendoc_import_headers (external_document_id, source_document_id, is_alternative)" in preview["sql_script"]
    assert "is_alternate" not in preview["sql_script"]
