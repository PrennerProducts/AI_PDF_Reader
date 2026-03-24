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
    assert parsed["supplier_name"] == "Lupre AI Solutions"
    assert parsed["document_number"] == "AN-2025-113"
    assert parsed["document_date"] == "08.12.2025"
    assert parsed["project_ref"] == "KI-PDF-Reader Version ON-PREM (Physischer Server beim Kunden vor Ort)"
    _assert_totals(parsed, ("4.600,00", "920,00", "EUR 5.520,00"))
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


def test_alu_one_a2602224mc_regression() -> None:
    pdf_path = ROOT / "samples/pdfs/regression/offers/alu_one/Angebot A2602224MC.pdf"
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_lines = extract_amount_lines(text)

    assert parsed["template"] == "alu_one"
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
    assert parsed["document_number"] == "C2509283TB"
    assert parsed["document_date"] == "10.11.2025"
    assert parsed["project_ref"] == "Kinderhotel Felben"
    _assert_totals(parsed, ("€ 16.984,29", "€ 3.396,86", "€ 20.381,15"))
    assert len(items) == 2
    assert items[1]["description_short"] == "Türelement 2650 mm x 2700 mm"
