import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from parser import parse_document_text
from structured_parser import extract_amount_lines, extract_line_items


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


def test_rieder_regression() -> None:
    text = _read_text_fixture(ROOT / "samples/text/AN_Rieder_F_20252082_BV_Achhorner.txt")
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "rieder"
    assert parsed["document_type"] == "angebot"
    assert parsed["supplier_name"] == "Rieder"
    assert parsed["document_number"] == "20252082"
    assert parsed["project_ref"] == "Achhorner"
    _assert_totals(parsed, ("€ 6.315,71", "€ 1.263,14", "€ 7.578,85"))
    assert len(items) == 5
    assert items[0]["description_short"] == "Balkontüre 2flg DKL DRS BS37mm"
    assert any(item["is_alternative"] for item in items)


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
    assert len(amount_lines) == 3


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
    _assert_totals(parsed, ("4.600,00", "920,00", "5.520,00"))
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
    assert items[-1]["lv_pos"] == "Lieferung"
    assert items[-1]["line_total_raw"] == "578,59"
    assert [row["line_type"] for row in amount_lines[-3:]] == ["net_total", "vat", "total"]


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
    _assert_totals(parsed, ("4.600,00", "920,00", "5.520,00"))
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
    assert items[1]["position_no"] == "001.1"
    assert items[1]["description_short"] == 'Az "2-farbig RAL/RAL"'
    assert items[-1]["position_no"] == "Z01"
    assert items[-1]["line_total_raw"] == "75,00"
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
