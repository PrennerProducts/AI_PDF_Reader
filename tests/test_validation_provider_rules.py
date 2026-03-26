from decimal import Decimal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from validation import build_document_validation


def test_sr_schauraum_optional_item_counts_towards_component_sum() -> None:
    validation = build_document_validation(
        document={
            "supplier_name": "Lupre AI Solutions",
            "document_type": "angebot",
            "document_number": "AN-2025-113",
            "document_date": "2025-12-08",
            "project_ref": "KI-PDF-Reader",
            "currency": "EUR",
            "net_total": "4600.00",
            "vat_total": "920.00",
            "gross_total": "5520.00",
            "parse_confidence": "0.99",
            "raw_text_path": None,
        },
        amount_lines=[],
        line_items=[
            {"position_no": "1", "description_short": "MODUL 1", "quantity": "22", "unit_price": "100.00", "line_total": "2200.00", "page_ref": 1, "is_alternative": False},
            {"position_no": "2", "description_short": "MODUL 2", "quantity": "16", "unit_price": "100.00", "line_total": "1600.00", "page_ref": 2, "is_alternative": False},
            {"position_no": "3", "description_short": "OPTIONAL: ON-PREM", "quantity": "1", "unit_price": "800.00", "line_total": "800.00", "page_ref": 3, "is_alternative": True},
        ],
        images=[],
    )

    assert validation["status"] == "auto_accept"
    assert validation["totals"]["component_included_line_item_sum"] == Decimal("4600.00")
    assert validation["totals"]["component_sum_matches_net"] is True


def test_alu_one_provider_policy_excludes_az_and_vorbemerkungen() -> None:
    validation = build_document_validation(
        document={
            "supplier_name": "alu-one Metallbaupartner GmbH",
            "document_type": "angebot",
            "document_number": "C2509283TB",
            "document_date": "2025-11-10",
            "project_ref": "Kinderhotel Felben",
            "currency": "EUR",
            "net_total": "16984.29",
            "vat_total": "3396.86",
            "gross_total": "20381.15",
            "parse_confidence": "0.99",
            "raw_text_path": None,
        },
        amount_lines=[],
        line_items=[
            {"position_no": "000", "description_short": "Vorbemerkungen", "quantity": "1", "unit_price": "0.00", "line_total": "0.00", "page_ref": 1, "is_alternative": False},
            {"position_no": "001", "description_short": "Türelement", "quantity": "1", "unit_price": "16984.29", "line_total": "16984.29", "page_ref": 1, "is_alternative": False},
            {"position_no": "008", "description_short": "AZ - Glasauschnitt", "quantity": "1", "unit_price": "180.00", "line_total": "180.00", "page_ref": 2, "is_alternative": False},
        ],
        images=[],
    )

    assert validation["status"] == "auto_accept"
    assert validation["totals"]["component_included_line_item_sum"] == Decimal("16984.29")
    assert validation["line_item_summary"]["warning_count"] == 0


def test_alu_one_az_item_is_not_treated_as_visual_image_requirement() -> None:
    line_items = [
        {
            "position_no": "001",
            "description_short": "Türelement",
            "quantity": "1",
            "unit_price": "180.00",
            "line_total": "180.00",
            "page_ref": 1,
            "is_alternative": False,
            "image_ids": [77],
        },
        {
            "position_no": "008",
            "description_short": "AZ - Glasauschnitt",
            "quantity": "1",
            "unit_price": "180.00",
            "line_total": "180.00",
            "page_ref": 2,
            "is_alternative": False,
            "image_ids": [],
        },
    ]
    validation = build_document_validation(
        document={
            "supplier_name": "alu-one Metallbaupartner GmbH",
            "document_type": "angebot",
            "document_number": "C2509283TB",
            "document_date": "2025-11-10",
            "project_ref": "Kinderhotel Felben",
            "currency": "EUR",
            "net_total": "180.00",
            "vat_total": "36.00",
            "gross_total": "216.00",
            "parse_confidence": "0.99",
            "raw_text_path": None,
        },
        amount_lines=[],
        line_items=line_items,
        images=[{"id": 77, "page_ref": 1}],
    )

    az_item = line_items[1]
    az_issue_codes = [issue.get("code") for issue in (az_item.get("validation_issues") or [])]

    assert "missing_image_assignment" not in az_issue_codes
    assert az_item["validation_status"] == "auto_accept"


def test_entholzer_system_header_is_informational() -> None:
    validation = build_document_validation(
        document={
            "supplier_name": "Entholzer",
            "document_type": "angebot",
            "document_number": "12600422.00",
            "document_date": "2026-02-03",
            "project_ref": "Bernsteiner",
            "currency": "EUR",
            "net_total": "751.44",
            "vat_total": "150.29",
            "gross_total": "901.73",
            "parse_confidence": "0.99",
            "raw_text_path": None,
        },
        amount_lines=[],
        line_items=[
            {"position_no": "1", "lv_pos": "System", "description_short": "AluClip 90 (Serie Smart)", "quantity": "1", "unit_price": None, "line_total": None, "page_ref": 1, "is_alternative": False},
            {"position_no": "2", "lv_pos": "HG", "description_short": "dreh-kipp mit Festverglasung", "quantity": "1", "unit_price": "751.44", "line_total": "751.44", "page_ref": 2, "is_alternative": False},
        ],
        images=[],
    )

    assert validation["status"] == "auto_accept"
    assert validation["line_item_summary"]["error_count"] == 0
    assert validation["line_item_summary"]["warning_count"] == 0


def test_newo_zero_value_note_positions_are_informational() -> None:
    validation = build_document_validation(
        document={
            "supplier_name": "NeWo",
            "document_type": "angebot",
            "document_number": "25002995",
            "document_date": "2025-09-04",
            "project_ref": "BVH Projekt 353 Achhorner",
            "currency": "EUR",
            "net_total": "9959.30",
            "vat_total": "1991.86",
            "gross_total": "11951.16",
            "parse_confidence": "0.99",
            "raw_text_path": None,
        },
        amount_lines=[],
        line_items=[
            {"position_no": "100", "description_short": "NeWo Raffstore Lite, i80", "quantity": "1", "unit_price": "9959.30", "line_total": "9959.30", "page_ref": 1, "is_alternative": False},
            {"position_no": "110", "description_short": "Diese Position stellt keine", "quantity": "1", "unit_price": "0.00", "line_total": "0.00", "page_ref": 2, "is_alternative": False},
        ],
        images=[],
    )

    assert validation["status"] == "auto_accept"
    assert validation["line_item_summary"]["warning_count"] == 0


def test_complex_pricing_providers_use_heuristic_component_check() -> None:
    validation = build_document_validation(
        document={
            "supplier_name": "Rekord Vomp GmbH",
            "document_type": "angebot",
            "document_number": "VAX60326",
            "document_date": "2026-02-02",
            "project_ref": "Kom. Hagsteiner L. - Daniela Feldes",
            "currency": "EUR",
            "net_total": "22473.45",
            "vat_total": "4494.69",
            "gross_total": "26968.14",
            "parse_confidence": "0.99",
            "raw_text_path": None,
        },
        amount_lines=[
            {"line_type": "net_total", "label_raw": "Summe der Positionen 43.343,19 Händlerrabatt -39,00 % Zusatzrabatt -15,00 % Summe Netto 22.473,45", "amount": "22473.45"},
            {"line_type": "vat", "label_raw": "MwSt 20,00 % 4.494,69", "amount": "4494.69"},
            {"line_type": "total", "label_raw": "Summe Brutto 26.968,14", "amount": "26968.14"},
        ],
        line_items=[
            {"position_no": "1", "description_short": "2tlg. Element", "quantity": "1", "unit_price": "43343.19", "line_total": "43343.19", "page_ref": 1, "is_alternative": False},
            {"position_no": "12", "lv_pos": "Umfang", "description_short": "Umfang", "quantity": "1", "unit_price": "0.00", "line_total": "0.00", "page_ref": 10, "is_alternative": False},
        ],
        images=[],
    )

    assert validation["status"] == "auto_accept"
    assert validation["totals"]["component_check_mode"] == "heuristic"
    assert validation["line_item_summary"]["warning_count"] == 0


def test_ab_requires_offer_reference() -> None:
    validation = build_document_validation(
        document={
            "supplier_name": "Rieder",
            "document_type": "auftragsbestaetigung",
            "document_number": "131584-2",
            "document_date": "2025-06-11",
            "project_ref": "Sevignani",
            "currency": "EUR",
            "net_total": "100.00",
            "vat_total": "20.00",
            "gross_total": "120.00",
            "parse_confidence": "0.99",
            "raw_text_path": None,
            "offer_reference": None,
        },
        amount_lines=[],
        line_items=[
            {
                "position_no": "1",
                "description_short": "Fenster",
                "quantity": "1",
                "unit_price": "100.00",
                "line_total": "100.00",
                "page_ref": 1,
                "is_alternative": False,
            },
        ],
        images=[],
    )

    assert validation["status"] == "reject"
    assert any(issue.get("field") == "offer_reference" for issue in validation["document_issues"])


def test_manual_review_resolves_warning_but_keeps_item_marked() -> None:
    line_items = [
        {
            "position_no": "001",
            "description_short": "Türelement",
            "quantity": "1",
            "unit_price": "100.00",
            "line_total": "100.00",
            "page_ref": 1,
            "is_alternative": False,
            "image_ids": [],
            "metadata_json": {
                "review_checked": True,
                "review_checked_at": "2026-03-25T13:22:09Z",
                "review_checked_reason": "ui_manual_review",
            },
        },
    ]
    validation = build_document_validation(
        document={
            "supplier_name": "alu-one Metallbaupartner GmbH",
            "document_type": "angebot",
            "document_number": "C2509283TB",
            "document_date": "2025-11-10",
            "project_ref": "Kinderhotel Felben",
            "currency": "EUR",
            "net_total": "100.00",
            "vat_total": "20.00",
            "gross_total": "120.00",
            "parse_confidence": "0.99",
            "raw_text_path": None,
        },
        amount_lines=[],
        line_items=line_items,
        images=[{"id": 7, "page_ref": 1}],
    )

    assert validation["status"] == "manual_checked"
    assert validation["warning_count"] == 0
    assert validation["line_item_summary"]["resolved_warning_count"] == 1
    assert line_items[0]["validation_status"] == "manual_checked"


def test_manual_review_does_not_resolve_errors() -> None:
    line_items = [
        {
            "position_no": "001",
            "description_short": "Türelement",
            "quantity": "1",
            "unit_price": "100.00",
            "line_total": None,
            "page_ref": 1,
            "is_alternative": False,
            "image_ids": [],
            "metadata_json": {
                "review_checked": True,
                "review_checked_at": "2026-03-25T13:22:09Z",
                "review_checked_reason": "ui_manual_review",
            },
        },
    ]
    validation = build_document_validation(
        document={
            "supplier_name": "alu-one Metallbaupartner GmbH",
            "document_type": "angebot",
            "document_number": "C2509283TB",
            "document_date": "2025-11-10",
            "project_ref": "Kinderhotel Felben",
            "currency": "EUR",
            "net_total": "100.00",
            "vat_total": "20.00",
            "gross_total": "120.00",
            "parse_confidence": "0.99",
            "raw_text_path": None,
        },
        amount_lines=[],
        line_items=line_items,
        images=[{"id": 7, "page_ref": 1}],
    )

    assert validation["status"] == "reject"
    assert validation["error_count"] > 0
    assert line_items[0]["validation_status"] == "reject"


def test_document_approval_summary_is_exposed_for_approved_document() -> None:
    validation = build_document_validation(
        document={
            "supplier_name": "alu-one Metallbaupartner GmbH",
            "document_type": "angebot",
            "document_number": "C2509283TB",
            "document_date": "2025-11-10",
            "project_ref": "Kinderhotel Felben",
            "currency": "EUR",
            "net_total": "100.00",
            "vat_total": "20.00",
            "gross_total": "120.00",
            "parse_confidence": "0.99",
            "raw_text_path": None,
            "approval_status": "approved",
            "reviewed_by": "Daniela",
            "reviewed_at": "2026-03-26T09:15:00Z",
            "approval_note": "OK fuer Export",
        },
        amount_lines=[],
        line_items=[
            {
                "position_no": "001",
                "description_short": "Türelement",
                "quantity": "1",
                "unit_price": "100.00",
                "line_total": "100.00",
                "page_ref": 1,
                "is_alternative": False,
                "image_ids": [7],
            },
        ],
        images=[{"id": 7, "page_ref": 1}],
    )

    assert validation["status"] == "auto_accept"
    assert validation["approval"]["approved"] is True
    assert validation["approval"]["eligible"] is True
    assert validation["approval"]["reviewed_by"] == "Daniela"
    assert validation["approval"]["approval_note"] == "OK fuer Export"


def test_document_approval_summary_stays_pending_when_validation_blocks_release() -> None:
    validation = build_document_validation(
        document={
            "supplier_name": "Rieder",
            "document_type": "auftragsbestaetigung",
            "document_number": "131584-2",
            "document_date": "2025-06-11",
            "project_ref": "Sevignani",
            "currency": "EUR",
            "net_total": "100.00",
            "vat_total": "20.00",
            "gross_total": "120.00",
            "parse_confidence": "0.99",
            "raw_text_path": None,
            "approval_status": "pending",
        },
        amount_lines=[],
        line_items=[
            {
                "position_no": "1",
                "description_short": "Fenster",
                "quantity": "1",
                "unit_price": "100.00",
                "line_total": "100.00",
                "page_ref": 1,
                "is_alternative": False,
            },
        ],
        images=[],
    )

    assert validation["status"] == "reject"
    assert validation["approval"]["approved"] is False
    assert validation["approval"]["eligible"] is False
    assert validation["approval"]["status"] == "pending"
