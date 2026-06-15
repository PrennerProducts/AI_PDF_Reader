import json
import sys
import subprocess
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from parser import parse_document_text
from structured_parser import extract_amount_lines, extract_line_items
from template_common import extract_first_description
from main import _build_amount_line_rows, _build_line_item_rows
from validation import build_document_validation


def _read_text_fixture(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_pdf_text(path: Path) -> str:
    try:
        from extractor import extract_pdf_text
    except ModuleNotFoundError:
        return subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True)
    return extract_pdf_text(path)


def _assert_totals(parsed: dict, expected: tuple[str, str, str]) -> None:
    totals = parsed.get("totals") or {}
    assert totals.get("net_total") == expected[0]
    assert totals.get("vat_total") == expected[1]
    assert totals.get("gross_total") == expected[2]


def test_first_description_strips_trailing_currency_price() -> None:
    assert (
        extract_first_description(
            ["Fixfenster 1flg € 5.404,00 €"],
            skip_prefixes=(),
            preferred_words=("fixfenster",),
        )
        == "Fixfenster 1flg"
    )


def test_rieder_regression() -> None:
    text = _read_text_fixture(ROOT / "samples/text/AN_Rieder_F_20252082_BV_Achhorner.txt")
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    item_by_pos = {item["position_no"]: item for item in items}

    assert parsed["template"] == "rieder"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "Rieder"
    assert parsed["document_number"] == "20252082"
    assert parsed["project_ref"] == "Achhorner"
    _assert_totals(parsed, ("€ 6.315,71", "€ 1.263,14", "€ 7.578,85"))
    assert len(items) == 5
    assert items[0]["description_short"] == "Balkontüre 2flg DKL DRS BS37mm"
    assert item_by_pos["1"]["is_alternative"] is False
    assert item_by_pos["2"]["is_alternative"] is True
    assert item_by_pos["3"]["is_alternative"] is False
    assert item_by_pos["4"]["is_alternative"] is False
    assert item_by_pos["5"]["is_alternative"] is False


def test_rieder_processing_adds_delivery_position_and_applies_sequential_discounts() -> None:
    text = _read_text_fixture(ROOT / "samples/text/AN_Rieder_F_20252082_BV_Achhorner.txt")
    parsed = parse_document_text(text)
    amount_rows = _build_amount_line_rows(text, parsed["totals"])
    rows = _build_line_item_rows(text, parsed["template"], amount_line_rows=amount_rows)

    delivery_rows = [row for row in rows if row["description_short"] == "Baustellenanlieferung / Frachtkosten"]
    assert len(rows) == 6
    assert len(delivery_rows) == 1
    assert delivery_rows[0]["position_no"] == "6"
    assert delivery_rows[0]["line_total"] == Decimal("200.00")
    assert delivery_rows[0]["unit_price"] == Decimal("200.00")
    assert rows[1]["is_alternative"] is True
    assert rows[1]["line_total"] == Decimal("1761.01")

    normal_without_delivery = [
        row
        for row in rows
        if not row["is_alternative"] and row["description_short"] != "Baustellenanlieferung / Frachtkosten"
    ]
    assert sum(row["line_total"] for row in normal_without_delivery) == Decimal("6111.71")
    assert sum(row["line_total"] for row in rows if not row["is_alternative"]) == Decimal("6311.71")

    baustellen_amount_rows = [row for row in amount_rows if "Baustellenanlieferung" in row["label_raw"]]
    assert baustellen_amount_rows[0]["line_type"] == "surcharge"

    validation = build_document_validation(
        document={
            "supplier_name": "Rieder",
            "document_type": "angebot",
            "document_number": parsed["document_number"],
            "document_date": "2025-09-05",
            "project_ref": parsed["project_ref"],
            "currency": "EUR",
            "net_total": "6315.71",
            "vat_total": "1263.14",
            "gross_total": "7578.85",
        },
        amount_lines=amount_rows,
        line_items=rows,
        images=[],
    )
    assert validation["totals"]["component_check_mode"] == "rieder_sequence"
    assert validation["totals"]["component_sum_matches_net"] is True


def test_rieder_validation_can_skip_sequential_discounts() -> None:
    text = _read_text_fixture(ROOT / "samples/text/AN_Rieder_F_20252082_BV_Achhorner.txt")
    parsed = parse_document_text(text)
    amount_rows = _build_amount_line_rows(text, parsed["totals"])
    rows = _build_line_item_rows(text, parsed["template"], amount_line_rows=amount_rows)
    basis_rows = []
    for row in rows:
        basis_row = dict(row)
        metadata = json.loads(row.get("metadata_json") or "{}")
        if metadata.get("rieder_original_line_total") is not None:
            basis_row["line_total"] = Decimal(str(metadata["rieder_original_line_total"]))
        if metadata.get("rieder_original_unit_price") is not None:
            basis_row["unit_price"] = Decimal(str(metadata["rieder_original_unit_price"]))
        basis_rows.append(basis_row)

    validation = build_document_validation(
        document={
            "supplier_name": "Rieder",
            "document_type": "angebot",
            "document_number": parsed["document_number"],
            "document_date": "2025-09-05",
            "project_ref": parsed["project_ref"],
            "currency": "EUR",
            "net_total": "6315.71",
            "vat_total": "1263.14",
            "gross_total": "7578.85",
            "apply_pricing_adjustments": False,
        },
        amount_lines=amount_rows,
        line_items=basis_rows,
        images=[],
    )

    assert validation["totals"]["apply_pricing_adjustments"] is False
    assert validation["totals"]["component_check_mode"] == "rieder_adjustments_disabled"
    assert validation["totals"]["component_sum_matches_net"] is False
    assert "rieder_pricing_sequence" not in validation["totals"]
    assert {
        issue["code"]
        for issue in validation["document_issues"]
    }.isdisjoint({"rieder_pricing_sequence_mismatch", "net_component_mismatch"})


def test_rieder_multiline_inline_kommission_regression() -> None:
    text = """
Rieder GmbH
www.rieder-zillertal.at
Ried, am 09.06.2026
Kommission: BV Bauernhaus
Hochschwarzwald
Angebot: 20260679
Position: 1
1 Stück B/H: 1000,0 x 1000,0
Fenster 1flg                                                             € 1.000,00       € 1.000,00
EP: 1 000,00 GP: € 1.000,00
""".strip()

    parsed = parse_document_text(text)

    assert parsed["template"] == "rieder"
    assert parsed["document_number"] == "20260679"
    assert parsed["project_ref"] == "BV Bauernhaus\nHochschwarzwald"


def test_rieder_main_price_ignores_embedded_alternative_prices() -> None:
    text = """
Rieder GmbH
Angebot: 20252202
Kommission: Test
Position: 2
Ku.Pos.: Pos. 2
1 Stück
Fenster 1flg DKL                                                    € 527,00
Beschlagsdetails und Profiltext
Alternativ: Holzart: Douglas 3-schicht verleimt EP: € 57,97 GP: € 57,97
Alternativ: Holzart: Lärche 3-schicht verleimt EP: € 87,97 GP: € 87,97
Position: 3
1 Stück
Fixfenster 1flg                                                     € 100,00
""".strip()

    items = extract_line_items(text, "rieder")

    assert items[0]["position_no"] == "2"
    assert items[0]["is_alternative"] is False
    assert items[0]["description_short"] == "Fenster 1flg DKL"
    assert "Ku.Pos." not in items[0]["description_long"]
    assert items[0]["unit_price_raw"] == "€ 527,00"
    assert items[0]["line_total_raw"] == "€ 527,00"


def test_entholzer_regression() -> None:
    text = _read_text_fixture(ROOT / "samples/text/AN_Enth_neu_12502888-00_20250909_Email.txt")
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "entholzer"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "Entholzer"
    assert parsed["document_number"] == "12502888.00"
    assert parsed["project_ref"] == "Hotel Explorer, Bayrischzell"
    _assert_totals(parsed, ("179 114,17", "35 822,83", "214 937,00"))
    assert len(items) == 22
    assert items[0]["description_short"] == "AluClip 90 (SERIE SMART)"
    assert items[0]["lv_pos"] == "System"
    assert items[0].get("image_required", True) is True
    assert "EP: GP:" not in items[0]["description_long"]
    assert "(Symbolfoto)" not in items[0]["description_long"]
    assert all("EP: GP:" not in item["description_long"] for item in items)


def test_entholzer_empty_montage_line_does_not_steal_net_total() -> None:
    text = """
Summe ohne Montagekosten                                      18 439,42 €
abzüglich 10%    Sonderrabatt aus     18 439,42                1 843,94 €
Zwischensumme                                                 16 595,48 €
zuzüglich Montage/Zustellung gesamt               ______________________
Nettosumme                                                    16 595,48 €
zuzüglich 20% Mehrwertsteuer                                   3 319,10 €
Angebotssumme                                                 19 914,58 €
""".strip()

    amount_lines = extract_amount_lines(text)

    assert [line["line_type"] for line in amount_lines] == [
        "subtotal",
        "discount",
        "subtotal",
        "net_total",
        "vat",
        "total",
    ]
    assert all("Montage/Zustellung" not in line["label_raw"] for line in amount_lines)


def test_entholzer_processing_applies_sonderrabatt_to_positions() -> None:
    text = _read_pdf_text(ROOT / "samples/pdfs/regression/offers/entholzer/Angebot 12600422.00 Bernsteiner.pdf")
    parsed = parse_document_text(text)
    amount_rows = _build_amount_line_rows(text, parsed["totals"])
    rows = _build_line_item_rows(text, parsed["template"], amount_line_rows=amount_rows)
    rows_by_pos = {row["position_no"]: row for row in rows}
    position_two = rows_by_pos["2"]
    metadata = json.loads(position_two["metadata_json"])

    assert "751,44 €" not in position_two["description_long"]
    assert "EP:" not in position_two["description_long"]
    assert "GP:" not in position_two["description_long"]
    assert position_two["unit_price"] == Decimal("676.30")
    assert position_two["line_total"] == Decimal("676.30")
    assert metadata["entholzer_original_unit_price"] == "751.44"
    assert metadata["entholzer_original_line_total"] == "751.44"
    assert metadata["entholzer_pricing_operations"][0]["percent"] == "10"
    assert sum((row.get("line_total") or Decimal("0.00") for row in rows if not row.get("is_alternative")), Decimal("0.00")) == Decimal("19635.78")

    validation = build_document_validation(
        document={
            "supplier_name": parsed["supplier_name"],
            "document_type": parsed["document_type"],
            "document_number": parsed["document_number"],
            "document_date": parsed["document_date"],
            "project_ref": parsed["project_ref"],
            "currency": "EUR",
            "net_total": parsed["totals"]["net_total"],
            "vat_total": parsed["totals"]["vat_total"],
            "gross_total": parsed["totals"]["gross_total"],
            "apply_pricing_adjustments": True,
        },
        amount_lines=amount_rows,
        line_items=rows,
        images=[],
    )

    assert validation["status"] == "auto_accept"
    assert validation["totals"]["component_check_mode"] == "entholzer_adjusted_positions"
    assert validation["totals"]["component_sum_matches_net"] is True


def test_newo_regression() -> None:
    text = _read_text_fixture(ROOT / "samples/text/AN_NEWO_BVH_Projekt_353_Achhorner.txt")
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_lines = extract_amount_lines(text)

    assert parsed["template"] == "newo"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "NeWo"
    assert parsed["document_number"] == "25002995"
    assert parsed["project_ref"] == "BVH Projekt 353 Achhorner"
    _assert_totals(parsed, ("9.959,30", "1.991,86", "11.951,16"))
    assert len(items) == 8
    assert items[0]["description_short"] == "NeWo Raffstore Lite, i80"
    assert items[0]["description_long"].splitlines()[0] == "NeWo Raffstore Lite, i80"
    assert "100 4,00 Stk" not in items[0]["description_long"]
    assert "640,12" not in items[0]["description_long"]
    assert "2.560,48" not in items[0]["description_long"]
    item_by_pos = {item["position_no"]: item for item in items}
    assert "110 4,00 Stk" not in item_by_pos["110"]["description_long"]
    assert "Wolfgang Neumeyer" not in item_by_pos["110"]["description_long"]
    assert item_by_pos["140"]["image_required"] is False
    assert item_by_pos["160"]["referenced_lv_pos"] == "57.05.21.A"
    assert item_by_pos["160"]["image_required"] is False
    assert item_by_pos["170"]["image_required"] is True
    assert len(amount_lines) == 3


def test_schuchter_accessory_position_is_not_image_required() -> None:
    text = """
Schuchter Fenster GmbH
Angebot A260396 vom 03.04.2026
Pos.
13 1 Stk. 511203 D
.
Az auf Pos.10
RWA Beschlag Silber
E-Motor mit Zusatzverriegelung
fertig am Fenster montiert
.
E-Anschluss BAUSEITS
Zentrale+Taster BAUSEITS
.
1.980,00 1.980,00
"""
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "schuchter"
    assert len(items) == 1
    assert items[0]["position_no"] == "13"
    assert items[0]["image_required"] is False


def test_schuchter_composite_parent_position_is_not_image_required() -> None:
    text = """
Schuchter Fenster GmbH
Angebot A260344 vom 25.03.2026
Pos.
1 2 Stk. 430100
Kopplungselement bestehend aus:
Pos. 1a, Pos. 1b und Pos. 1c
.
3.000,00 6.000,00
"""
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "schuchter"
    assert len(items) == 1
    assert items[0]["position_no"] == "1"
    assert items[0]["image_required"] is False


def test_sr_schauraum_regression() -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/sr_schauraum/Angebotsnr AN-2025-113 - SR Schauraum GmbH (2).pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_lines = extract_amount_lines(text)

    assert parsed["template"] == "sr_schauraum"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "Lupre AI Solutions"
    assert parsed["document_number"] == "AN-2025-113"
    assert parsed["document_date"] == "08.12.2025"
    assert parsed["project_ref"] == "KI-PDF-Reader Version ON-PREM (Physischer Server beim Kunden vor Ort)"
    _assert_totals(parsed, ("€ 4.600,00", "€ 920,00", "€ 5.520,00"))
    assert len(items) == 3
    assert items[0]["description_short"] == "MODUL 1 – ON-PREM KI-PDF-READER & SQL-EXPORT"
    assert items[2]["is_alternative"] is True
    assert [row["line_type"] for row in amount_lines] == ["subtotal", "vat", "total"]


def test_rekord_vomp_regression() -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/rekord_vomp/Angebot_VAX60326.pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_lines = extract_amount_lines(text)

    assert parsed["template"] == "rekord_vomp"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "Rekord Vomp GmbH"
    assert parsed["document_number"] == "VAX60326"
    assert parsed["document_date"] == "02.02.2026"
    assert parsed["project_ref"] == "Kom. Hagsteiner L. - Daniela Feldes"
    _assert_totals(parsed, ("22.473,45", "4.494,69", "26.968,14"))
    assert len(items) == 14
    assert items[0]["description_short"] == "2tlg. Element bestehend aus:"
    assert items[1]["quantity_raw"] == "2"
    item_by_pos = {item["position_no"]: item for item in items}
    assert (item_by_pos["1"]["width_raw"], item_by_pos["1"]["height_raw"]) == ("3000", "2300")
    assert (item_by_pos["2"]["width_raw"], item_by_pos["2"]["height_raw"]) == ("1000", "2300")
    assert (item_by_pos["3"]["width_raw"], item_by_pos["3"]["height_raw"]) == ("1000", "2300")
    assert (item_by_pos["3.1"]["width_raw"], item_by_pos["3.1"]["height_raw"]) == ("1000", "2300")
    assert (item_by_pos["5"]["width_raw"], item_by_pos["5"]["height_raw"]) == ("1000", "2300")
    assert (item_by_pos["6"]["width_raw"], item_by_pos["6"]["height_raw"]) == ("1000", "2300")
    assert item_by_pos["8"]["page_ref"] == 7
    assert item_by_pos["8"]["page_end_ref"] == 8
    assert item_by_pos["8"]["spans_page_break"] is True
    assert item_by_pos["8"]["item_top_ratio"] > 0.7
    assert item_by_pos["8"]["next_position_page_ref"] == 8
    assert 0.45 < item_by_pos["8"]["next_position_top_ratio"] < 0.55
    assert item_by_pos["9"]["item_top_ratio"] == item_by_pos["8"]["next_position_top_ratio"]
    assert item_by_pos["11"]["page_ref"] == 9
    assert item_by_pos["11"]["page_end_ref"] == 10
    assert item_by_pos["11"]["spans_page_break"] is True
    assert items[-1]["lv_pos"] == "Lieferung"
    assert items[-1]["line_total_raw"] == "578,59"
    assert [row["line_type"] for row in amount_lines[-3:]] == ["net_total", "vat", "total"]


def test_rekord_vomp_processing_applies_discounts_and_delivery_rules() -> None:
    cases = [
        ("Angebot_VAX53456.pdf", Decimal("16174.15"), "1000", Decimal("300.00")),
        ("Angebot_VAX60326.pdf", Decimal("22473.45"), "13", Decimal("300.01")),
        ("VAX30295.pdf", Decimal("18015.46"), "100", Decimal("300.00")),
    ]

    for filename, expected_net, delivery_position, expected_delivery_total in cases:
        pdf_path = ROOT / "samples/pdfs/regression/offers/rekord_vomp" / filename
        text = _read_pdf_text(pdf_path)
        parsed = parse_document_text(text)
        amount_rows = _build_amount_line_rows(text, parsed["totals"])
        rows = _build_line_item_rows(text, parsed["template"], source_path=pdf_path, amount_line_rows=amount_rows)
        normal_sum = sum(
            (row.get("line_total") or Decimal("0.00") for row in rows if not row.get("is_alternative")),
            Decimal("0.00"),
        )
        delivery_row = next(row for row in rows if row["position_no"] == delivery_position)
        metadata = json.loads(rows[0]["metadata_json"])

        assert normal_sum == expected_net
        assert delivery_row["line_total"] == expected_delivery_total
        assert metadata["rekord_vomp_original_line_total"] is not None
        assert metadata["rekord_vomp_pricing_operations"][0]["percent"] == "39.00"

        validation = build_document_validation(
            document={
                "supplier_name": parsed["supplier_name"],
                "document_type": parsed["document_type"],
                "document_number": parsed["document_number"],
                "document_date": parsed["document_date"],
                "project_ref": parsed["project_ref"],
                "currency": "EUR",
                "net_total": parsed["totals"]["net_total"],
                "vat_total": parsed["totals"]["vat_total"],
                "gross_total": parsed["totals"]["gross_total"],
                "apply_pricing_adjustments": True,
            },
            amount_lines=amount_rows,
            line_items=rows,
            images=[],
        )

        assert validation["status"] == "auto_accept"
        assert validation["totals"]["component_check_mode"] == "rekord_vomp_adjusted_positions"
        assert validation["totals"]["component_sum_matches_net"] is True


def test_sr_schauraum_compact_extractor_regression() -> None:
    text = """
Lupre AI Solutions FlexCo
SR. Schauraum GmbH
Angebot
Angebotsnummer AN-2025-113
Datum 08.12.2025
Projekt KI-PDF-Reader Version ON-PREM (Physischer Server beim Kunden vor Ort)
Beschreibung Menge Einheit Preis Betrag
MODUL 1 – ON-PREM KI-PDF-READER & SQL-EXPORT
- Automatische Verarbeitung von PDF-Dokumenten
22 Stunde(n) 100,00 € 2.200,00 €
MODUL 2 – DOCKER- & PRODUKTIV-SETUP
16 Stunde(n) 100,00 € 1.600,00 €
OPTIONAL: ON-PREM-INBETRIEBNAHME & ÜBERGABE VOR
ORT
1 pauschal 800,00 € 800,00 €
Zwischensumme ohne USt. 4.600,00 €
USt. 20 % von 4.600,00 € 920,00 €
Gesamt EUR 5.520,00 €
""".strip()
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "sr_schauraum"
    assert parsed["document_type"] == "angebot"
    assert parsed["document_number"] == "AN-2025-113"
    _assert_totals(parsed, ("€ 4.600,00", "€ 920,00", "€ 5.520,00"))
    assert len(items) == 3
    assert items[0]["description_short"] == "MODUL 1 – ON-PREM KI-PDF-READER & SQL-EXPORT"
    assert items[1]["line_total_raw"] == "1.600,00"
    assert items[2]["description_short"] == "OPTIONAL: ON-PREM-INBETRIEBNAHME & ÜBERGABE VOR ORT"
    assert items[2]["is_alternative"] is True


def test_rekord_vomp_compact_extractor_regression() -> None:
    text = """
REKORD Vomp GmbH
Rekord Vomp GmbH-Au 48-AT-6134VompFirmaSR. Schauraum GmbH Bauvorhaben:Kom. Hagsteiner L. -Daniela Feldes
Angebot: VAX60326Vorgang : VV2600196
Belegdatum: 02.02.2026Seite: 1von 12
Pos. 1 1 Stück
2tlg. Element bestehend aus:Serie: 88MD1tlg.Kunststoff Fenster 881tlg.Kunststoff Balkontüre 88RAM: 3000 mm x 2300 mm
1 Stück2.364,00 Gesamt 1 Stück4.028,95Pos. 2 2 Stück
1tlg.Kunststoff FensterSerie: 88MDRAM: 1000 mm x 2300 mm
1 Stück1.076,49 Gesamt 2 Stück2.152,98
Summe der Positionen 43.343,19Händlerrabatt -39,00 %-16.903,84Zusatzrabatt -15,00 %-3.965,90Summe Netto 22.473,45MwSt 20,00 %4.494,69Summe Brutto 26.968,14
""".strip()
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "rekord_vomp"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "Rekord Vomp GmbH"
    assert parsed["document_number"] == "VAX60326"
    assert parsed["document_date"] == "02.02.2026"
    assert parsed["project_ref"] == "Kom. Hagsteiner L. -Daniela Feldes"
    _assert_totals(parsed, ("22.473,45", "4.494,69", "26.968,14"))
    assert len(items) == 2
    assert items[0]["description_short"].startswith("2tlg. Element")
    assert items[0]["line_total_raw"] == "4.028,95"
    assert items[1]["line_total_raw"] == "2.152,98"


def test_rekord_vomp_interleaved_ram_dimensions_regression() -> None:
    text = """
REKORD Vomp GmbH
Angebot: VAX60326
Belegdatum: 02.02.2026
Bauvorhaben: Kom. Hagsteiner L. - Daniela Feldes
Pos. 2 2 Stück
1tlg.Kunststoff Fenster
2300 RAM:Element1000außenmmRALx 2300laut mmKollektion 2550
Gesamt 2 Stück 2.152,98
Pos. 3 3 Stück
1tlg.Kunststoff Balkontüre
2300 StocklichteRAM: 1000 Höhe:mm x 2141.02300 mmmm 2550
Gesamt 3 Stück 4.852,89
Summe Netto 22.473,45
MwSt 20,00 %4.494,69
Summe Brutto 26.968,14
""".strip()
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    item_by_pos = {item["position_no"]: item for item in items}

    assert parsed["template"] == "rekord_vomp"
    assert (item_by_pos["2"]["width_raw"], item_by_pos["2"]["height_raw"]) == ("1000", "2300")
    assert (item_by_pos["3"]["width_raw"], item_by_pos["3"]["height_raw"]) == ("1000", "2300")


def test_alu_one_a2602224mc_regression() -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/alu_one/Angebot A2602224MC.pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_lines = extract_amount_lines(text)

    assert parsed["template"] == "alu_one"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "alu-one Metallbaupartner GmbH"
    assert parsed["document_number"] == "A2602224MC"
    assert parsed["document_date"] == "06.03.2026"
    assert parsed["project_ref"] == "Alte Sennerei Söll"
    _assert_totals(parsed, ("€ 11.807,99", "€ 2.361,60", "€ 14.169,59"))
    assert len(items) == 9
    assert items[0]["description_short"] == "Türelement 1850 mm x 2450 mm 43.51.11 W"
    assert "001 1,00 Stk" not in items[0]["description_long"]
    assert "€ 3.334,05" not in items[0]["description_long"]
    assert items[4]["description_short"].startswith("Aufpreis von 3-fach verriegelndes")
    assert items[5]["is_alternative"] is True
    assert items[-1]["position_no"] == "008"
    assert [row["line_type"] for row in amount_lines[-3:]] == ["net_total", "vat", "total"]


def test_alu_one_c2509283tb_regression() -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/alu_one/Angebot C2509283TB.pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_lines = extract_amount_lines(text)

    assert parsed["template"] == "alu_one"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "alu-one Metallbaupartner GmbH"
    assert parsed["document_number"] == "C2509283TB"
    assert parsed["document_date"] == "10.11.2025"
    assert parsed["project_ref"] == "Kinderhotel Felben"
    _assert_totals(parsed, ("€ 16.984,29", "€ 3.396,86", "€ 20.381,15"))
    assert len(items) == 9
    assert items[0]["description_short"] == "Vorbemerkungen"
    assert "000 1,00 Stk" not in items[0]["description_long"]
    assert "€ 0,00" not in items[0]["description_long"]
    assert "Gerichtsstand" not in items[1]["description_long"]
    assert items[1]["width_raw"] == "2650"
    assert items[1]["height_raw"] == "2700"
    assert items[-1]["description_short"] == "AZ - Glasauschnitt"
    assert items[-1]["is_alternative"] is True
    assert [row["line_type"] for row in amount_lines[-3:]] == ["net_total", "vat", "total"]


def test_alu_one_compact_header_regression() -> None:
    text = """
10.11.2025
alu-one Metallbaupartner GmbH
Heroalstraße 1 - 4870 Vöcklamarkt
SR. Schauraum GmbH
C2509283TB
Nummer:
Druckdatum:
Anfrage vom:
Kommission:
Bearbeiter:
31.10.2025
Kinderhotel Felben
Tobias Bachmann
Frau Feldes Erstellung am: 10.11.2025
ANGEBOT
000  1,00 Stk Vorbemerkungen € 0,00 € 0,00
001  1,00 Stk Türelement 2650 mm x 2700 mm € 3.778,68 € 3.778,68
Nettowert € 16.984,29
zuzüglich 20,0 % MwSt. € 3.396,86
Bruttobetrag € 20.381,15
""".strip()
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "alu_one"
    assert parsed["document_type"] == "angebot"
    assert parsed["document_number"] == "C2509283TB"
    assert parsed["document_date"] == "10.11.2025"
    assert parsed["project_ref"] == "Kinderhotel Felben"
    _assert_totals(parsed, ("€ 16.984,29", "€ 3.396,86", "€ 20.381,15"))
    assert len(items) == 2
    assert items[1]["description_short"] == "Türelement 2650 mm x 2700 mm"


def test_alu_one_candidate_2400061_positions_and_amount_lines() -> None:
    pdf_path = ROOT / "samples/pdfs/candidates/offers/alu_one/Angebot 2400061DL-1_i.pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_rows = _build_amount_line_rows(text, parsed["totals"], template=parsed["template"])
    line_rows = _build_line_item_rows(text, parsed["template"], source_path=pdf_path, amount_line_rows=amount_rows)
    item_by_pos = {item["position_no"]: item for item in items}
    row_by_pos = {row["position_no"]: row for row in line_rows}

    assert parsed["document_number"] == "2400061DL-1"
    assert len(items) == 32
    assert item_by_pos["014-1"]["is_alternative"] is False
    assert item_by_pos["013A"]["is_alternative"] is True
    assert item_by_pos["990c-202"]["description_short"] == "Anlieferungspauschale Brandschutzglas < 20 m²"
    assert row_by_pos["990c-202"]["line_total"] == Decimal("64.00")
    assert [row["line_type"] for row in amount_rows] == ["net_total", "vat", "total"]
    assert sum((row.get("line_total") or Decimal("0.00") for row in line_rows if not row.get("is_alternative")), Decimal("0.00")) == Decimal("128994.39")
    assert "990c-202 1,00 Stk" not in item_by_pos["990c-202"]["description_long"]
    assert "€ 64,00" not in item_by_pos["990c-202"]["description_long"]


def test_alu_one_candidate_a2506340_keeps_surcharge_positions_out_of_amount_lines() -> None:
    pdf_path = ROOT / "samples/pdfs/candidates/offers/alu_one/Angebot A2506340MC-1.pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_rows = _build_amount_line_rows(text, parsed["totals"], template=parsed["template"])
    line_rows = _build_line_item_rows(text, parsed["template"], source_path=pdf_path, amount_line_rows=amount_rows)
    item_by_pos = {item["position_no"]: item for item in items}

    assert parsed["document_number"] == "A2506340MC-1"
    assert len(items) == 9
    assert item_by_pos["991-2024"]["description_short"] == "Farbmindermengenzuschlag pro Farbe"
    assert item_by_pos["993-2025"]["description_short"] == "Mindermengenzuschlag Brandschutzglas < 20 m²"
    assert [row["line_type"] for row in amount_rows] == ["net_total", "vat", "total"]
    assert sum((row.get("line_total") or Decimal("0.00") for row in line_rows if not row.get("is_alternative")), Decimal("0.00")) == Decimal("24127.54")


def test_alu_one_candidate_c2308329_falls_back_from_empty_price_header() -> None:
    pdf_path = ROOT / "samples/pdfs/candidates/offers/alu_one/Angebot C2308329MK.pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    item_by_pos = {item["position_no"]: item for item in items}

    assert parsed["document_number"] == "C2308329MK"
    assert item_by_pos["013"]["description_short"] == "HER 6022 39 Winkelprofil 20x30x2 RAL 6000 mm"
    assert "€ 11.010,23" not in item_by_pos["013"]["description_short"]
    assert "€ 11.010,23" not in item_by_pos["013"]["description_long"]


def test_koch_regression() -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/koch/1050685_Angebot.pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "koch"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "Koch Türen GmbH"
    assert parsed["document_number"] == "1050685"
    assert parsed["document_date"] == "21.01.2026"
    assert parsed["project_ref"] == "Krigovszky Martin"
    _assert_totals(parsed, ("€ 1.520,64", "€ 304,13", "€ 1.824,77"))
    assert len(items) == 1
    assert items[0]["description_short"] == "Stockelement Niveau, Schiebetür in die Wand laufend"
    assert items[0]["width_raw"] == "1210"
    assert items[0]["height_raw"] == "2480"
    assert items[0]["line_total_raw"] == "2.304,00"


def test_muigg_regression() -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/muigg/AN 251409.pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_lines = extract_amount_lines(text)

    assert parsed["template"] == "muigg"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "Muigg"
    assert parsed["document_number"] == "251409"
    assert parsed["document_date"] == "15.12.2025"
    assert parsed["project_ref"] == "BV WH Kilian Schwaz"
    _assert_totals(parsed, ("18.280,31", "3.656,06", "21.936,37"))
    assert len(items) == 9
    assert items[0]["description_short"] == "Portal 4501 x 2500"
    assert items[0]["width_raw"] == "4501"
    assert items[0]["height_raw"] == "2500"
    assert items[0]["image_required"] is True
    assert items[1]["position_no"] == "001.1"
    assert items[1]["description_short"] == 'Az "2-farbig RAL/RAL"'
    assert items[1]["image_required"] is False
    assert items[-1]["position_no"] == "Z01"
    assert items[-1]["line_total_raw"] == "75,00"
    assert items[-1]["image_required"] is False
    assert [row["line_type"] for row in amount_lines[-3:]] == ["net_total", "vat", "total"]


def test_schachermayer_regression() -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/schachermayer/SCH Offert 225217709.PDF"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_lines = extract_amount_lines(text)

    assert parsed["template"] == "schachermayer"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "Schachermayer GmbH"
    assert parsed["document_number"] == "225217709"
    assert parsed["document_date"] == "11.03.2024"
    assert parsed["project_ref"] == "01 INNENTÜRELEMENT BIS MST 170"
    _assert_totals(parsed, ("5.928,04", "1.185,61", "7.113,65"))
    assert len(items) == 4
    assert items[0]["description_short"] == "Kunex Tür"
    assert items[0]["lv_pos"] == "01 INNENTÜRELEMENT BIS MST 170"
    assert items[2]["lv_pos"] == "02 ZARGE BIS MST 295"
    assert items[3]["description_short"] == "Rosettenlochbohrung (Önorm, 7,5 mm)"
    assert [row["line_type"] for row in amount_lines[-3:]] == ["net_total", "vat", "total"]


def test_schlotterer_regression() -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/schlotterer/Angebot_Schlotterer.pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_lines = extract_amount_lines(text)

    assert parsed["template"] == "schlotterer"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "Schlotterer Sonnenschutz Systeme GmbH"
    assert parsed["document_number"] == "826004412"
    assert parsed["document_date"] == "18.03.2026"
    assert parsed["project_ref"] == "LV MS Fieberbrunn"
    _assert_totals(parsed, ("EUR 57 790,35", "EUR 11 558,07", "EUR 69 348,42"))
    assert len(items) == 25
    assert items[0]["description_short"] == "Raff S"
    assert items[0]["lv_pos"] == "75.50.02 B"
    assert items[-1]["description_short"] == "Verpackungsbeitrag"
    assert [row["line_type"] for row in amount_lines[-3:]] == ["net_total", "vat", "total"]


def test_rieder_ab_reference_regression() -> None:
    pdf_path = ROOT / "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/rieder/131584_Sevignani, zu 130629_3.pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "rieder"
    assert parsed["document_type"] == "auftragsbestaetigung"
    assert parsed["supplier_name"] == "Rieder"
    assert parsed["document_number"] == "131584-2"
    assert parsed["document_date"] == "11.06.2025"
    assert parsed["project_ref"] == "Sevignani, zu 130629"
    assert parsed["offer_reference"] == "130629"
    assert len(items) >= 1
    assert items[0]["position_no"] == "1"


def test_rieder_ab_multiline_header_regression() -> None:
    text = """
Firma
SR.Schauraum GmbH
www.rieder-zillertal.at
11.06.2025
Technisch: Wechselberger Claudia
Kaufmännisch: Löffler Simone
Ried, am
Kommission:
Ihre UID-Nr.:
Kontaktperson:
Sevignani, zu 130629
ATU73878137
Mario Fuchs
Auftragsbestätigung: 131584-2
Position: 1
1 Stück B/H: 2125,0 x 2302,0
HS Schema A nach links € 5.965,00 € 5.965,00
""".strip()
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "rieder"
    assert parsed["document_type"] == "auftragsbestaetigung"
    assert parsed["document_number"] == "131584-2"
    assert parsed["document_date"] == "11.06.2025"
    assert parsed["project_ref"] == "Sevignani, zu 130629"
    assert parsed["offer_reference"] == "130629"
    assert len(items) == 1
