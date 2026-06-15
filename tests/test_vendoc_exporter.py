import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from vendoc_exporter import (
    _split_embedded_alternatives,
    _strip_price_tokens,
    _strip_prices_from_long_text,
    build_vendoc_payload,
    external_document_id,
    external_line_item_id,
)
from vendoc_mssql import (
    POSITION_COLUMNS,
    POSITION_TABLE,
    _binding_row_values,
    _resolve_column_bindings,
    build_srtemp_export_preview,
    build_srtemp_insert_script,
)
from vendoc_rtf import build_vendoc_long_text_rtf, escape_rtf_text
from parser import parse_document_text
from structured_parser import extract_line_items
from main import _build_amount_line_rows, _build_line_item_rows, _parse_eu_decimal


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
    assert position["position_no"] == "1"
    assert position["quantity"] == 1.0
    assert position["unit_code"] == "Stk"
    assert position["description_long"] == "Tuerelement mit Seitenteil"
    assert position["unit_price"] == 1900.59
    assert position["purchase_price"] == 1900.59
    assert position["text_only_rtf"].startswith("{\\rtf1")
    assert "\\pngblip" not in position["text_only_rtf"]
    assert "Tuerelement mit Seitenteil" in position["text_only_rtf"]
    assert position["image_long_text_rtf"].startswith("{\\rtf1")
    assert "\\pngblip" in position["image_long_text_rtf"]
    assert image_bytes.hex() in position["image_long_text_rtf"]
    assert "Tuerelement mit Seitenteil" in position["image_long_text_rtf"]
    assert position["image_only_rtf"].startswith("{\\rtf1")
    assert "\\pngblip" in position["image_only_rtf"]
    assert image_bytes.hex() in position["image_only_rtf"]
    assert "Tuerelement mit Seitenteil" not in position["image_only_rtf"]
    assert position["image_hex"] == image_bytes.hex()
    assert position["image_is_primary"] is True
    assert position["main_line_item_id"] == "57.05.21.A"


def test_vendoc_payload_reports_missing_primary_image_file(tmp_path: Path) -> None:
    payload = build_vendoc_payload(_sample_result(tmp_path / "missing.png"))

    assert payload["errors"] == []
    assert payload["warnings"][0]["code"] == "primary_image_file_missing"
    assert payload["positions"][0]["image_only_rtf"] is None
    assert payload["positions"][0]["image_hex"] is None
    assert "\\pngblip" not in payload["positions"][0]["image_long_text_rtf"]
    assert "\\pngblip" not in payload["positions"][0]["text_only_rtf"]
    assert payload["positions"][0]["image_is_primary"] is False


def test_vendoc_payload_exports_embedded_alternatives_nested(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["alternative_position_mode"] = "nested"
    result["line_items"][0]["position_no"] = "1"
    result["line_items"][0]["description_long"] = "\n".join(
        [
            "Fenster 2flg DLS DKR",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 119,90 GP: € 1.438,80",
            "Alternativ: Holzart: Lärche 3-schicht verleimt",
        ]
    )

    payload = build_vendoc_payload(result)

    assert payload["summary"]["position_count"] == 3
    assert payload["summary"]["alternative_position_mode"] == "nested"
    assert payload["summary"]["alternative_position_count"] == 2
    assert [position["position_no"] for position in payload["positions"]] == ["1", "1.1", "1.2"]
    assert payload["positions"][0]["is_alternative"] is False
    assert payload["positions"][0]["description_long"] == "Fenster 2flg DLS DKR"
    assert "Alternativ:" not in payload["positions"][0]["description_long"]
    assert payload["positions"][1]["is_alternative"] is True
    assert payload["positions"][1]["description_short"] == "Holzart: Douglas 3-schicht verleimt"
    assert payload["positions"][1]["unit_price"] == 119.9
    assert payload["positions"][1]["purchase_price"] == 119.9
    assert payload["positions"][1]["image_is_primary"] is False
    assert payload["positions"][2]["description_short"] == "Holzart: Lärche 3-schicht verleimt"


def test_vendoc_payload_appends_one_embedded_alternative_by_parent_override(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["alternative_position_mode"] = "nested"
    result["line_items"][0]["position_no"] = "1"
    result["line_items"][0]["description_long"] = "\n".join(
        [
            "Fenster 2flg DLS DKR",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 119,90 GP: € 1.438,80",
            "Alternativ: Holzart: Lärche 3-schicht verleimt",
        ]
    )
    result["line_items"][0]["metadata_json"] = {
        "embedded_alternative_append_at_end": {"1": True},
    }

    payload = build_vendoc_payload(result)

    assert [position["position_no"] for position in payload["positions"]] == ["1", "1.1", "2"]
    assert payload["positions"][1]["description_short"] == "Holzart: Lärche 3-schicht verleimt"
    assert payload["positions"][2]["description_short"] == "Holzart: Douglas 3-schicht verleimt"


def test_vendoc_payload_applies_rieder_sequence_to_embedded_alternatives(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Rieder"
    result["document"]["alternative_position_mode"] = "nested"
    result["line_items"][0]["description_long"] = "\n".join(
        [
            "Fenster 1flg DKL",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 57,97 GP: € 57,97",
        ]
    )
    result["line_items"][0]["metadata_json"] = {
        "rieder_pricing_applied": True,
        "rieder_pricing_operations": [
            {"line_type": "surcharge", "percent": "3"},
            {"line_type": "discount", "percent": "38"},
            {"line_type": "discount", "percent": "8"},
            {"line_type": "discount", "percent": "8"},
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["positions"][1]["description_short"] == "Holzart: Douglas 3-schicht verleimt"
    assert payload["positions"][1]["unit_price"] == 57.97
    assert payload["positions"][1]["purchase_price"] == 31.33


def test_vendoc_payload_embedded_alternative_purchase_ignores_parent_adjusted_price(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Rieder"
    result["document"]["alternative_position_mode"] = "nested"
    result["line_items"][0]["description_long"] = "\n".join(
        [
            "Fenster 2flg DLS DKR",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 119,90 GP: € 1.438,80",
        ]
    )
    result["line_items"][0]["metadata_json"] = {
        "rieder_pricing_applied": True,
        "rieder_original_unit_price": "1385.02",
        "rieder_adjusted_unit_price": "748.62",
        "rieder_original_line_total": "16620.24",
        "rieder_adjusted_line_total": "8983.44",
        "rieder_pricing_operations": [
            {"line_type": "surcharge", "percent": "3"},
            {"line_type": "discount", "percent": "38"},
            {"line_type": "discount", "percent": "8"},
            {"line_type": "discount", "percent": "8"},
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["positions"][0]["unit_price"] == 1385.02
    assert payload["positions"][0]["purchase_price"] == 748.62
    assert payload["positions"][1]["unit_price"] == 119.9
    assert payload["positions"][1]["purchase_price"] == 64.81


def test_vendoc_payload_groups_duplicate_nested_embedded_alternatives_per_parent(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Rieder"
    result["document"]["alternative_position_mode"] = "nested"
    result["line_items"][0]["quantity"] = "12"
    result["line_items"][0]["description_long"] = "\n".join(
        [
            "Fenster 2flg DLS DKR",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 119,90 GP: € 1.438,80",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 190,90 GP: € 2.290,80",
            "Alternativ: Holzart: Lärche 3-schicht verleimt EP: € 147,15 GP: € 1.765,80",
            "Alternativ: Holzart: Lärche 3-schicht verleimt EP: € 218,15 GP: € 2.617,80",
        ]
    )
    result["line_items"][0]["metadata_json"] = {
        "rieder_pricing_applied": True,
        "rieder_original_unit_price": "1385.02",
        "rieder_adjusted_unit_price": "748.62",
        "rieder_pricing_operations": [
            {"line_type": "surcharge", "percent": "3"},
            {"line_type": "discount", "percent": "38"},
            {"line_type": "discount", "percent": "8"},
            {"line_type": "discount", "percent": "8"},
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["summary"]["position_count"] == 3
    assert payload["summary"]["alternative_position_count"] == 4
    assert [position["position_no"] for position in payload["positions"]] == ["1", "1.1", "1.2"]
    douglas = payload["positions"][1]
    laerche = payload["positions"][2]
    assert douglas["description_short"] == "Holzart: Douglas 3-schicht verleimt"
    assert douglas["description_long"] == "Gesammelte Alternative: Holzart: Douglas 3-schicht verleimt\nAnzahl Quellpositionen: 2"
    assert "119,90" not in douglas["description_long"]
    assert "119.90" not in douglas["description_long"]
    assert douglas["quantity"] == 12.0
    assert douglas["unit_price"] == 310.8
    assert douglas["purchase_price"] == 167.99
    assert laerche["description_short"] == "Holzart: Lärche 3-schicht verleimt"
    assert laerche["quantity"] == 12.0
    assert laerche["unit_price"] == 365.3
    assert laerche["purchase_price"] == 197.45


def test_vendoc_payload_groups_duplicate_embedded_alternatives_with_pricing_disabled(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Rieder"
    result["document"]["alternative_position_mode"] = "nested"
    result["document"]["apply_pricing_adjustments"] = False
    result["line_items"][0]["quantity"] = "12"
    result["line_items"][0]["description_long"] = "\n".join(
        [
            "Fenster 2flg DLS DKR",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 119,90 GP: € 1.438,80",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 190,90 GP: € 2.290,80",
        ]
    )
    result["line_items"][0]["metadata_json"] = {
        "rieder_pricing_applied": True,
        "rieder_original_unit_price": "1385.02",
        "rieder_adjusted_unit_price": "748.62",
        "rieder_pricing_operations": [
            {"line_type": "surcharge", "percent": "3"},
            {"line_type": "discount", "percent": "38"},
            {"line_type": "discount", "percent": "8"},
            {"line_type": "discount", "percent": "8"},
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["summary"]["apply_pricing_adjustments"] is False
    assert [position["position_no"] for position in payload["positions"]] == ["1", "1.1"]
    assert payload["positions"][0]["unit_price"] == 1385.02
    assert payload["positions"][1]["description_short"] == "Holzart: Douglas 3-schicht verleimt"
    assert payload["positions"][1]["unit_price"] == 310.8
    assert payload["positions"][1]["purchase_price"] == 167.99


def test_vendoc_payload_groups_duplicate_embedded_alternatives_before_appending(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Rieder"
    result["document"]["alternative_position_mode"] = "append"
    result["document"]["apply_pricing_adjustments"] = False
    result["line_items"][0]["quantity"] = "12"
    result["line_items"][0]["description_long"] = "\n".join(
        [
            "Fenster 2flg DLS DKR",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 119,90 GP: € 1.438,80",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 190,90 GP: € 2.290,80",
        ]
    )
    result["line_items"][0]["metadata_json"] = {
        "rieder_pricing_applied": True,
        "rieder_original_unit_price": "1385.02",
        "rieder_adjusted_unit_price": "748.62",
        "rieder_pricing_operations": [
            {"line_type": "surcharge", "percent": "3"},
            {"line_type": "discount", "percent": "38"},
            {"line_type": "discount", "percent": "8"},
            {"line_type": "discount", "percent": "8"},
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["summary"]["alternative_position_mode"] == "append"
    assert [position["position_no"] for position in payload["positions"]] == ["1", "2"]
    appended = payload["positions"][1]
    assert appended["description_short"] == "Holzart: Douglas 3-schicht verleimt"
    assert appended["quantity"] == 12.0
    assert appended["unit_price"] == 310.8
    assert appended["purchase_price"] == 167.99


def test_vendoc_payload_can_skip_rieder_sequence_for_embedded_alternatives(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Rieder"
    result["document"]["alternative_position_mode"] = "nested"
    result["document"]["apply_pricing_adjustments"] = False
    result["line_items"][0]["description_long"] = "\n".join(
        [
            "Fenster 1flg DKL",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 57,97 GP: € 57,97",
        ]
    )
    result["line_items"][0]["metadata_json"] = {
        "rieder_pricing_applied": True,
        "rieder_pricing_operations": [
            {"line_type": "surcharge", "percent": "3"},
            {"line_type": "discount", "percent": "38"},
            {"line_type": "discount", "percent": "8"},
            {"line_type": "discount", "percent": "8"},
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["summary"]["apply_pricing_adjustments"] is False
    assert payload["positions"][1]["description_short"] == "Holzart: Douglas 3-schicht verleimt"
    assert payload["positions"][1]["unit_price"] == 57.97
    assert payload["positions"][1]["purchase_price"] == 31.33


def test_vendoc_payload_can_skip_rieder_sequence_for_stored_positions(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Rieder"
    result["document"]["apply_pricing_adjustments"] = False
    result["line_items"][0]["unit_price"] = "31.33"
    result["line_items"][0]["line_total"] = "31.33"
    result["line_items"][0]["metadata_json"] = {
        "rieder_pricing_applied": True,
        "rieder_original_unit_price": "57.97",
        "rieder_original_line_total": "57.97",
        "rieder_pricing_operations": [
            {"line_type": "surcharge", "percent": "3"},
            {"line_type": "discount", "percent": "38"},
            {"line_type": "discount", "percent": "8"},
            {"line_type": "discount", "percent": "8"},
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["summary"]["apply_pricing_adjustments"] is False
    assert payload["positions"][0]["unit_price"] == 57.97
    assert payload["positions"][0]["purchase_price"] == 31.33


def test_vendoc_payload_exports_rieder_basis_unit_and_discounted_purchase_when_enabled(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Rieder"
    result["document"]["apply_pricing_adjustments"] = True
    result["line_items"][0]["unit_price"] = "31.33"
    result["line_items"][0]["line_total"] = "31.33"
    result["line_items"][0]["metadata_json"] = {
        "rieder_pricing_applied": True,
        "rieder_original_unit_price": "57.97",
        "rieder_original_line_total": "57.97",
        "rieder_pricing_operations": [
            {"line_type": "surcharge", "percent": "3"},
            {"line_type": "discount", "percent": "38"},
            {"line_type": "discount", "percent": "8"},
            {"line_type": "discount", "percent": "8"},
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["summary"]["apply_pricing_adjustments"] is True
    assert payload["positions"][0]["unit_price"] == 57.97
    assert payload["positions"][0]["purchase_price"] == 31.33


def test_vendoc_payload_exports_rieder_processed_rows_with_basis_and_purchase_prices() -> None:
    text = (ROOT / "samples/text/AN_Rieder_F_20252082_BV_Achhorner.txt").read_text(encoding="utf-8")
    parsed = parse_document_text(text)
    amount_rows = _build_amount_line_rows(text, parsed["totals"])
    rows = _build_line_item_rows(text, parsed["template"], amount_line_rows=amount_rows)

    payload = build_vendoc_payload(
        {
            "document": {
                "id": 20252082,
                "supplier_name": parsed["supplier_name"],
                "document_type": parsed["document_type"],
                "document_number": parsed["document_number"],
                "document_date": "2025-09-05",
                "project_ref": parsed["project_ref"],
                "currency": parsed["currency"],
                "apply_pricing_adjustments": True,
            },
            "line_items": rows,
            "images": [],
        }
    )

    assert payload["positions"][0]["unit_price"] == 6531.88
    assert payload["positions"][0]["purchase_price"] == 3530.55
    assert payload["positions"][1]["is_alternative"] is True
    assert payload["positions"][1]["unit_price"] == 3258.05
    assert payload["positions"][1]["purchase_price"] == 1761.01


def test_vendoc_payload_exports_newo_without_raw_header_prices() -> None:
    text = (ROOT / "samples/text/AN_NEWO_BVH_Projekt_353_Achhorner.txt").read_text(encoding="utf-8")
    parsed = parse_document_text(text)
    amount_rows = _build_amount_line_rows(text, parsed["totals"])
    rows = _build_line_item_rows(text, parsed["template"], amount_line_rows=amount_rows)

    payload = build_vendoc_payload(
        {
            "document": {
                "id": 25002995,
                "supplier_name": parsed["supplier_name"],
                "document_type": parsed["document_type"],
                "document_number": parsed["document_number"],
                "document_date": "2025-09-04",
                "project_ref": parsed["project_ref"],
                "currency": parsed["currency"],
                "net_total": _parse_eu_decimal(parsed["totals"]["net_total"]),
                "vat_total": _parse_eu_decimal(parsed["totals"]["vat_total"]),
                "gross_total": _parse_eu_decimal(parsed["totals"]["gross_total"]),
            },
            "line_items": rows,
            "images": [],
        }
    )

    first = payload["positions"][0]
    zero_note = payload["positions"][1]
    referenced = payload["positions"][6]

    assert payload["header"]["supplier_id"] == "300877"
    assert payload["header"]["net_total"] == 9959.3
    assert payload["summary"]["alternative_position_count"] == 0
    assert len(payload["positions"]) == 8
    assert first["description_short"] == "NeWo Raffstore Lite, i80"
    assert first["unit_price"] == 640.12
    assert first["purchase_price"] == 640.12
    assert "640,12" not in first["description_long"]
    assert "2.560,48" not in first["description_long"]
    assert first["description_long"].splitlines()[0] == "NeWo Raffstore Lite, i80"
    assert zero_note["unit_price"] == 0.0
    assert zero_note["purchase_price"] == 0.0
    assert "0,00 0,00" not in zero_note["description_long"]
    assert referenced["main_line_item_id"] == "57.05.21.A"


def test_vendoc_payload_reconstructs_rieder_purchase_when_result_is_already_basis_price(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Rieder"
    result["document"]["apply_pricing_adjustments"] = False
    result["line_items"][0]["unit_price"] = "57.97"
    result["line_items"][0]["line_total"] = "57.97"
    result["line_items"][0]["metadata_json"] = {
        "rieder_pricing_applied": True,
        "rieder_original_unit_price": "57.97",
        "rieder_original_line_total": "57.97",
        "rieder_pricing_operations": [
            {"line_type": "surcharge", "percent": "3"},
            {"line_type": "discount", "percent": "38"},
            {"line_type": "discount", "percent": "8"},
            {"line_type": "discount", "percent": "8"},
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["summary"]["apply_pricing_adjustments"] is False
    assert payload["positions"][0]["unit_price"] == 57.97
    assert payload["positions"][0]["purchase_price"] == 31.33


def test_vendoc_payload_exports_generic_basis_unit_and_discounted_purchase_when_enabled(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Entholzer"
    result["document"]["apply_pricing_adjustments"] = True
    result["line_items"][0]["unit_price"] = "676.30"
    result["line_items"][0]["line_total"] = "676.30"
    result["line_items"][0]["metadata_json"] = {
        "pricing_adjustments_applied": True,
        "pricing_original_unit_price": "751.44",
        "pricing_original_line_total": "751.44",
        "pricing_adjusted_unit_price": "676.30",
        "pricing_adjusted_line_total": "676.30",
        "entholzer_pricing_applied": True,
        "entholzer_original_unit_price": "751.44",
        "entholzer_original_line_total": "751.44",
        "entholzer_adjusted_unit_price": "676.30",
        "entholzer_adjusted_line_total": "676.30",
        "entholzer_pricing_operations": [
            {"line_type": "discount", "percent": "10", "label_raw": "abzüglich 10% Sonderrabatt"}
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["summary"]["apply_pricing_adjustments"] is True
    assert payload["positions"][0]["unit_price"] == 751.44
    assert payload["positions"][0]["purchase_price"] == 676.30


def test_vendoc_payload_exports_koch_basis_unit_and_discounted_purchase(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Koch Türen GmbH"
    result["document"]["apply_pricing_adjustments"] = True
    result["line_items"][0]["unit_price"] = "813.04"
    result["line_items"][0]["line_total"] = "4878.24"
    result["line_items"][0]["quantity"] = "6"
    result["line_items"][0]["metadata_json"] = {
        "pricing_adjustments_applied": True,
        "pricing_original_unit_price": "1339.00",
        "pricing_original_line_total": "8034.00",
        "pricing_adjusted_unit_price": "813.04",
        "pricing_adjusted_line_total": "4878.24",
        "koch_pricing_applied": True,
        "koch_original_unit_price": "1339.00",
        "koch_original_line_total": "8034.00",
        "koch_adjusted_unit_price": "813.04",
        "koch_adjusted_line_total": "4878.24",
        "koch_pricing_operations": [
            {"line_type": "discount", "percent": "34", "label_raw": "abzüglich 34% Rabatt"},
            {"line_type": "discount", "percent": "8", "label_raw": "abzüglich 8% Sonderrabatt"},
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["summary"]["apply_pricing_adjustments"] is True
    assert payload["positions"][0]["unit_price"] == 1339.0
    assert payload["positions"][0]["purchase_price"] == 813.04


def test_vendoc_payload_exports_schachermayer_basis_unit_and_discounted_purchase(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Schachermayer GmbH"
    result["document"]["apply_pricing_adjustments"] = True
    result["line_items"][0]["unit_price"] = "110.09"
    result["line_items"][0]["line_total"] = "2642.11"
    result["line_items"][0]["quantity"] = "24"
    result["line_items"][0]["metadata_json"] = {
        "pricing_adjustments_applied": True,
        "pricing_original_unit_price": "200.16",
        "pricing_original_line_total": "4803.84",
        "pricing_adjusted_unit_price": "110.09",
        "pricing_adjusted_line_total": "2642.11",
        "schachermayer_pricing_applied": True,
        "schachermayer_original_unit_price": "200.16",
        "schachermayer_original_line_total": "4803.84",
        "schachermayer_adjusted_unit_price": "110.09",
        "schachermayer_adjusted_line_total": "2642.11",
        "schachermayer_pricing_operations": [
            {"line_type": "discount", "percent": "45", "label_raw": "Schachermayer Positionsrabatt laut Nettobetrag"}
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["summary"]["apply_pricing_adjustments"] is True
    assert payload["positions"][0]["unit_price"] == 200.16
    assert payload["positions"][0]["purchase_price"] == 110.09


def test_vendoc_payload_can_skip_entholzer_sonderrabatt_for_stored_positions(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["supplier_name"] = "Entholzer"
    result["document"]["apply_pricing_adjustments"] = False
    result["line_items"][0]["unit_price"] = "676.30"
    result["line_items"][0]["line_total"] = "676.30"
    result["line_items"][0]["metadata_json"] = {
        "pricing_adjustments_applied": True,
        "pricing_original_unit_price": "751.44",
        "pricing_original_line_total": "751.44",
        "pricing_adjusted_unit_price": "676.30",
        "pricing_adjusted_line_total": "676.30",
        "entholzer_pricing_applied": True,
        "entholzer_pricing_operations": [
            {"line_type": "discount", "percent": "10", "label_raw": "abzüglich 10% Sonderrabatt"}
        ],
    }

    payload = build_vendoc_payload(result)

    assert payload["summary"]["apply_pricing_adjustments"] is False
    assert payload["positions"][0]["unit_price"] == 751.44
    assert payload["positions"][0]["purchase_price"] == 676.30


def test_vendoc_payload_renumbers_nested_alternatives_without_gaps(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["alternative_position_mode"] = "nested"
    result["line_items"] = [
        {
            **result["line_items"][0],
            "id": 77,
            "position_no": "1",
            "description_short": "Fixfenster",
            "description_long": "Fixfenster",
        },
        {
            **result["line_items"][0],
            "id": 78,
            "position_no": "2",
            "is_alternative": True,
            "description_short": "Alternative HS Schema A",
            "description_long": "Alternative HS Schema A",
        },
        {
            **result["line_items"][0],
            "id": 79,
            "position_no": "3",
            "description_short": "Fenster KIPP",
            "description_long": "Fenster KIPP",
        },
    ]

    payload = build_vendoc_payload(result)

    assert [position["position_no"] for position in payload["positions"]] == ["1", "1.1", "2"]
    assert [position["is_alternative"] for position in payload["positions"]] == [False, True, False]


def test_vendoc_payload_appends_single_nested_alternative_by_override(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["alternative_position_mode"] = "nested"
    result["line_items"] = [
        {
            **result["line_items"][0],
            "id": 77,
            "position_no": "1",
            "description_short": "Fixfenster",
            "description_long": "Fixfenster",
        },
        {
            **result["line_items"][0],
            "id": 78,
            "position_no": "1.1",
            "is_alternative": True,
            "description_short": "Alternative am Ende",
            "description_long": "Alternative am Ende",
            "metadata_json": {"alternative_append_at_end": True},
        },
        {
            **result["line_items"][0],
            "id": 79,
            "position_no": "1.2",
            "is_alternative": True,
            "description_short": "Alternative unter Hauptposition",
            "description_long": "Alternative unter Hauptposition",
        },
        {
            **result["line_items"][0],
            "id": 80,
            "position_no": "2",
            "description_short": "Fenster KIPP",
            "description_long": "Fenster KIPP",
        },
    ]

    payload = build_vendoc_payload(result)

    assert payload["summary"]["alternative_position_mode"] == "nested"
    assert payload["summary"]["alternative_position_count"] == 2
    assert [(position["position_no"], position["description_short"]) for position in payload["positions"]] == [
        ("1", "Fixfenster"),
        ("1.1", "Alternative unter Hauptposition"),
        ("2", "Fenster KIPP"),
        ("3", "Alternative am Ende"),
    ]
    assert [position["is_alternative"] for position in payload["positions"]] == [False, True, False, True]


def test_vendoc_payload_exports_alternatives_appended(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["alternative_position_mode"] = "append"
    result["line_items"] = [
        {
            **result["line_items"][0],
            "id": 77,
            "position_no": "1",
            "description_long": "Fenster\nAlternativ: Holzart: Douglas 3-schicht verleimt",
        },
        {
            **result["line_items"][0],
            "id": 78,
            "position_no": "3",
            "description_short": "Tuer",
            "description_long": "Tuer",
        },
        {
            **result["line_items"][0],
            "id": 79,
            "position_no": "2.1",
            "is_alternative": True,
            "description_short": "Alternative Griff",
            "description_long": "Alternative Griff",
        },
    ]

    payload = build_vendoc_payload(result)

    assert payload["summary"]["position_count"] == 4
    assert payload["summary"]["alternative_position_mode"] == "append"
    assert payload["summary"]["alternative_position_count"] == 2
    assert [position["position_no"] for position in payload["positions"]] == ["1", "2", "3", "4"]
    assert [position["is_alternative"] for position in payload["positions"]] == [False, False, True, True]
    assert payload["positions"][2]["description_short"] == "Holzart: Douglas 3-schicht verleimt"
    assert payload["positions"][3]["description_short"] == "Alternative Griff"


def test_vendoc_payload_groups_appended_alternatives_by_description(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    result = _sample_result(image_path)
    result["document"]["alternative_position_mode"] = "append"
    result["line_items"] = [
        {
            **result["line_items"][0],
            "id": 77,
            "position_no": "1",
            "quantity": "4",
            "description_long": "Fenster\nAlternativ: Holzart: Fichte 3-schicht verleimt EP: € 10,00",
        },
        {
            **result["line_items"][0],
            "id": 78,
            "position_no": "2",
            "quantity": "6",
            "description_short": "Tuer",
            "description_long": "Tuer\nAlternativ: Holzart: Fichte 3-schicht verleimt EP: € 20,00",
        },
    ]

    payload = build_vendoc_payload(result)

    assert payload["summary"]["alternative_position_mode"] == "append"
    assert payload["summary"]["alternative_position_count"] == 2
    assert payload["summary"]["position_count"] == 3
    assert [position["position_no"] for position in payload["positions"]] == ["1", "2", "3"]
    grouped = payload["positions"][2]
    assert grouped["is_alternative"] is True
    assert grouped["description_short"] == "Holzart: Fichte 3-schicht verleimt"
    assert grouped["description_long"] == "Gesammelte Alternative: Holzart: Fichte 3-schicht verleimt\nAnzahl Quellpositionen: 2"
    assert grouped["quantity"] == 10.0
    assert grouped["unit_price"] == 16.0
    assert grouped["purchase_price"] == 16.0
    assert grouped["image_is_primary"] is False


def test_vendoc_payload_exports_rieder_alternative_under_parent() -> None:
    text = (ROOT / "samples/text/AN_Rieder_F_20252082_BV_Achhorner.txt").read_text(encoding="utf-8")
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    payload = build_vendoc_payload(
        {
            "document": {
                "id": 20252082,
                "supplier_name": parsed["supplier_name"],
                "document_type": parsed["document_type"],
                "document_number": parsed["document_number"],
                "document_date": "2025-09-05",
                "project_ref": parsed["project_ref"],
                "currency": parsed["currency"],
                "alternative_position_mode": "nested",
            },
            "line_items": items,
            "images": [],
        }
    )

    assert payload["header"]["supplier_id"] == "300774"
    assert payload["summary"]["alternative_position_count"] == 1
    assert payload["summary"]["alternative_position_mode"] == "nested"
    assert [(position["position_no"], position["is_alternative"]) for position in payload["positions"]] == [
        ("1", False),
        ("1.1", True),
        ("2", False),
        ("3", False),
        ("4", False),
    ]
    assert payload["positions"][1]["description_short"] == "HS Schema A nach links"
    assert payload["positions"][1]["description_long"].splitlines()[0] == "B/H: 4000,0 x 2520,0"
    assert payload["positions"][1]["description_long"].splitlines()[-1] == "FlgNr: 2 Griffsitz: 1 000,0"
    assert "1 Stück B/H" not in payload["positions"][1]["description_long"]
    assert "Alternative:" not in payload["positions"][1]["description_long"]


def test_vendoc_payload_exports_rieder_alternative_appended() -> None:
    text = (ROOT / "samples/text/AN_Rieder_F_20252082_BV_Achhorner.txt").read_text(encoding="utf-8")
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    payload = build_vendoc_payload(
        {
            "document": {
                "id": 20252082,
                "supplier_name": parsed["supplier_name"],
                "document_type": parsed["document_type"],
                "document_number": parsed["document_number"],
                "document_date": "2025-09-05",
                "project_ref": parsed["project_ref"],
                "currency": parsed["currency"],
                "alternative_position_mode": "append",
            },
            "line_items": items,
            "images": [],
        }
    )

    assert payload["summary"]["alternative_position_count"] == 1
    assert payload["summary"]["alternative_position_mode"] == "append"
    assert [(position["position_no"], position["is_alternative"]) for position in payload["positions"]] == [
        ("1", False),
        ("2", False),
        ("3", False),
        ("4", False),
        ("5", True),
    ]
    assert payload["positions"][-1]["description_short"] == "HS Schema A nach links"
    assert payload["positions"][-1]["description_long"].splitlines()[0] == "B/H: 4000,0 x 2520,0"
    assert payload["positions"][-1]["description_long"].splitlines()[-1] == "FlgNr: 2 Griffsitz: 1 000,0"
    assert "1 Stück B/H" not in payload["positions"][-1]["description_long"]
    assert "Alternative:" not in payload["positions"][-1]["description_long"]


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
    assert "image_hex" in script
    assert f"0x{payload['positions'][0]['image_hex']}" in script
    assert "\\pngblip" in script
    assert "CONVERT(datetime, '20251110', 112)" in script
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
        "text_only_rtf",
        "unit_price",
        "purchase_price",
        "page_ref",
        "image_long_text_rtf",
        "image_only_rtf",
        "image_hex",
        "image_is_primary",
        "created_at",
        "article_no",
        "discount_1",
        "discount_2",
        "vat_type",
        "unity",
        "main_line_item_id",
    ]


def test_srtemp_image_hex_binds_as_varbinary_bytes(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    image_bytes = _write_png(image_path)
    payload = build_vendoc_payload(_sample_result(image_path))

    values = _binding_row_values(
        POSITION_TABLE,
        payload["positions"][0],
        [("image_hex", "image_hex")],
    )

    assert values == [image_bytes]


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


def test_srtemp_position_rtf_aliases_match_dragan_columns() -> None:
    bindings = _resolve_column_bindings(
        POSITION_TABLE,
        POSITION_COLUMNS,
        set(),
        [
            "external_line_item_id",
            "external_document_id",
            "source_line_item_id",
            "long_text_rtf",
            "image_rtf",
        ],
    )

    assert ("long_text_rtf", "text_only_rtf") in bindings
    assert ("image_rtf", "image_only_rtf") in bindings


def test_strip_price_tokens_removes_trailing_short_text_price() -> None:
    assert _strip_price_tokens("Fenster 2flg DLS DKR € 1.090,00 €") == "Fenster 2flg DLS DKR"


def test_strip_prices_from_long_text_removes_embedded_price_and_alternative_lines() -> None:
    raw = "\n".join(
        [
            "Fenster 2flg DLS DKR € 1.090,00 €",
            "EP: 1 385,02 GP: € 16.620,24",
            "Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 119,90 GP: € 1.438,80",
            "Alternative: EP: € 3.258,05 GP: € 3.258,05",
            "12 Stück B/H: 950,0 x 1300,0",
        ]
    )

    cleaned = _strip_prices_from_long_text(raw)

    assert cleaned == "\n".join(
        [
            "Fenster 2flg DLS DKR",
            "12 Stück B/H: 950,0 x 1300,0",
        ]
    )


def test_strip_prices_from_long_text_keeps_weights_and_measurements() -> None:
    raw = "\n".join(
        [
            "59,36 kg / Elementumfang 4,5 lfm",
            "95,6 kg / Elementumfang 6,8 lfm",
            "EP: 1 385,02 GP: € 16.620,24",
        ]
    )

    cleaned = _strip_prices_from_long_text(raw)

    assert cleaned == "\n".join(
        [
            "59,36 kg / Elementumfang 4,5 lfm",
            "95,6 kg / Elementumfang 6,8 lfm",
        ]
    )


def test_strip_prices_from_long_text_removes_customer_position_marker() -> None:
    raw = "\n".join(
        [
            "B/H: 4000,0 x 2520,0",
            "Ku.Pos.: Pos 1",
            "Ku.Pos.: Variante",
            "Fixfenster 1flg",
        ]
    )

    cleaned = _strip_prices_from_long_text(raw)

    assert cleaned == "\n".join(
        [
            "B/H: 4000,0 x 2520,0",
            "Fixfenster 1flg",
        ]
    )


def test_strip_prices_from_long_text_removes_only_leading_position_quantity() -> None:
    raw = "\n".join(
        [
            "1 Stück B/H: 4000,0 x 2520,0",
            "1 Stk. ECO PASS bis 240 mm, Maß: 4000*220",
        ]
    )

    cleaned = _strip_prices_from_long_text(raw, quantity="1", unit="Stück")

    assert cleaned == "\n".join(
        [
            "B/H: 4000,0 x 2520,0",
            "1 Stk. ECO PASS bis 240 mm, Maß: 4000*220",
        ]
    )


def test_split_embedded_alternatives_ignores_price_only_alternative_marker() -> None:
    main, alternatives = _split_embedded_alternatives(
        "\n".join(
            [
                "Fenster 1flg",
                "Alternative: EP: € 3.258,05 GP: € 3.258,05",
                "Alternativ: Holzart: Douglas EP: € 119,90 GP: € 119,90",
            ]
        )
    )

    assert main == "Fenster 1flg"
    assert alternatives == ["Holzart: Douglas EP: € 119,90 GP: € 119,90"]
