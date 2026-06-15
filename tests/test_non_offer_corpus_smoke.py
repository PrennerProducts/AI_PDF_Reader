import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from parser import parse_document_text
from structured_parser import extract_amount_lines, extract_line_items


def _read_pdf_text(path: Path) -> str:
    return subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True)


NON_OFFER_CASES = [
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/koch/48406_Auftragsbestätigung.pdf",
        "template": "koch",
        "supplier_name": "Koch Türen GmbH",
        "document_number": "48406",
        "document_date": "12.12.2025",
        "project_ref": "Spögler Christian",
        "offer_reference": None,
        "position_count": 5,
        "first_description": "Stockelement Niveau",
        "net_total": "€ 2.921,60",
        "vat_total": "€ 584,31",
        "gross_total": "€ 3.505,91",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/koch/49440_Auftragsbestätigung.pdf",
        "template": "koch",
        "supplier_name": "Koch Türen GmbH",
        "document_number": "49440",
        "document_date": "28.01.2026",
        "project_ref": "Tikovsky Maria",
        "offer_reference": None,
        "position_count": 10,
        "first_description": "Pfostenstockelement",
        "net_total": "€ 6.731,89",
        "vat_total": "€ 1.346,38",
        "gross_total": "€ 8.078,27",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/koch/Auftragsbestätigung_KOCH.pdf",
        "template": "koch",
        "supplier_name": "Koch Türen GmbH",
        "document_number": "50309",
        "document_date": "19.03.2026",
        "project_ref": "Kinderkrippe Grinzens",
        "offer_reference": None,
        "position_count": 2,
        "first_description": "Pfostenstockelement, beidseitig flächenbündig",
        "net_total": "€ 5.356,56",
        "vat_total": "€ 1.071,31",
        "gross_total": "€ 6.427,87",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schachermayer/SCH Auftragsbestätigung 39160014.PDF",
        "template": "schachermayer",
        "supplier_name": "Schachermayer GmbH",
        "document_number": "39160014",
        "document_date": "11.11.2025",
        "project_ref": None,
        "position_count": 4,
        "first_description": "Donau CPL Standard Zarge, Eiche Premium",
        "net_total": "741,60",
        "vat_total": "148,32",
        "gross_total": "889,92",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/newo/Auftragbest_Newo.pdf",
        "template": "newo",
        "supplier_name": "NeWo",
        "document_number": "AU2602082",
        "document_date": "16.03.2026",
        "project_ref": "Danzl IGI/Erharter",
        "offer_reference": "26001808",
        "position_count": 2,
        "first_description": "NeWo Insektenschutz Rollo mit Kasten und",
        "net_total": "263,70",
        "vat_total": "52,74",
        "gross_total": "316,44",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/newo/Auftragbest_Newo2.pdf",
        "template": "newo",
        "supplier_name": "NeWo",
        "document_number": "AU2602041",
        "document_date": "13.03.2026",
        "project_ref": "Buzdug / Mario",
        "offer_reference": "26001757",
        "position_count": 3,
        "first_description": 'NeWo Insektenschutz Schieberahmen "SA1',
        "net_total": "541,66",
        "vat_total": "108,33",
        "gross_total": "649,99",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/newo/Auftragsbestätiugn_Newo.pdf",
        "template": "newo",
        "supplier_name": "NeWo",
        "document_number": "AU2602324",
        "document_date": "20.03.2026",
        "project_ref": "Hörfarter Thomas",
        "offer_reference": "26002054",
        "position_count": 3,
        "first_description": 'NeWo Insektenschutz Drehtür "DT6SR',
        "net_total": "801,38",
        "vat_total": "160,28",
        "gross_total": "961,66",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schuchter/26020.pdf",
        "template": "schuchter",
        "supplier_name": "SCHUCHTER Fenster GmbH",
        "document_number": "26020",
        "document_date": "07.02.2026",
        "project_ref": "SR/KH-Felben-1.AK",
        "position_count": 50,
        "first_description": "2-flg.Fenster, D/DK-Stulp",
        "net_total": "€ 21.467,85",
        "vat_total": "€ 4.293,55",
        "gross_total": "€ 25.761,40",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schuchter/26021.pdf",
        "template": "schuchter",
        "supplier_name": "SCHUCHTER Fenster GmbH",
        "document_number": "26021",
        "document_date": "05.02.2026",
        "project_ref": "SR/KH-Felben-2.AK",
        "position_count": 35,
        "first_description": "1-flg.Fenster, DK-Rechts",
        "net_total": "€ 13.693,85",
        "vat_total": "€ 2.738,75",
        "gross_total": "€ 16.432,60",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schuchter/26028.pdf",
        "template": "schuchter",
        "supplier_name": "SCHUCHTER Fenster GmbH",
        "document_number": "26028",
        "document_date": "07.02.2026",
        "project_ref": "SR/KH-Felben-3.AK",
        "position_count": 31,
        "first_description": "1-flg.Fenster, KD-Rechts",
        "net_total": "€ 17.916,75",
        "vat_total": "€ 3.583,35",
        "gross_total": "€ 21.500,10",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/muigg/muigg__auftragsbestaetigung__1240238.pdf",
        "template": "muigg",
        "supplier_name": "Muigg",
        "document_number": "1240238",
        "document_date": "31.07.2024",
        "project_ref": "BV 24022/MKO SR RECON homebase FL03 - PR-FASSADE",
        "position_count": 2,
        "first_description": "PR Fassade 36-tlg. (CE) 5607 x 13810",
        "net_total": "28.521,35",
        "vat_total": "5.704,27",
        "gross_total": "34.225,62",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/muigg/muigg__auftragsbestaetigung__1250158.pdf",
        "template": "muigg",
        "supplier_name": "Muigg",
        "document_number": "1250158",
        "document_date": "22.05.2025",
        "project_ref": "BV 25022/MKO IB KARLPASSAGE",
        "position_count": 7,
        "first_description": "EI30 Fenster (CE) 1370 x 1338",
        "net_total": "14.413,29",
        "vat_total": "2.882,66",
        "gross_total": "17.295,95",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/muigg/muigg__auftragsbestaetigung__1250190.pdf",
        "template": "muigg",
        "supplier_name": "Muigg",
        "document_number": "1250190",
        "document_date": "18.06.2025",
        "project_ref": "BV 25022_RK Moonlight",
        "position_count": 3,
        "first_description": "EI30 Fenster (CE) 1170 x 1138",
        "net_total": "3.224,44",
        "vat_total": "644,89",
        "gross_total": "3.869,33",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/muigg/muigg__auftragsbestaetigung__1250439.pdf",
        "template": "muigg",
        "supplier_name": "Muigg",
        "document_number": "1250439",
        "document_date": "01.12.2025",
        "project_ref": "BV 25022/MKO SR IB KARLPASSAGE",
        "position_count": 1,
        "first_description": "RWA-Tasterzentrale",
        "net_total": "941,79",
        "vat_total": "188,36",
        "gross_total": "1.130,15",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schlotterer/Auftragsbestaetigung_260012068_Kreisern_Version_1.pdf",
        "template": "schlotterer",
        "supplier_name": "Schlotterer Sonnenschutz Systeme GmbH",
        "document_number": "260012068",
        "document_date": "19.02.2026",
        "project_ref": "Kreisern",
        "position_count": 6,
        "first_description": "IGI Schieberahmen",
        "net_total": "EUR 641,62",
        "vat_total": "EUR 120,64",
        "gross_total": "EUR 762,26",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schlotterer/Auftragsbestaetigung_260014367_Rendl Franz_Version_1.pdf",
        "template": "schlotterer",
        "supplier_name": "Schlotterer Sonnenschutz Systeme GmbH",
        "document_number": "260014367",
        "document_date": "25.02.2026",
        "project_ref": "Rendl Franz",
        "position_count": 12,
        "first_description": "Voro Raff",
        "net_total": "EUR 7 082,06",
        "vat_total": "EUR 1.331,46",
        "gross_total": "EUR 8 413,52",
    },
    {
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schlotterer/Auftragsbestaetigung_260015417_Libiseller_Version_1.pdf",
        "template": "schlotterer",
        "supplier_name": "Schlotterer Sonnenschutz Systeme GmbH",
        "document_number": "260015417",
        "document_date": "27.02.2026",
        "project_ref": "Libiseller",
        "position_count": 17,
        "first_description": "Panzer Rollladen",
        "net_total": "EUR 2 384,15",
        "vat_total": "EUR 448,28",
        "gross_total": "EUR 2 832,43",
    },
]


@pytest.mark.parametrize("case", NON_OFFER_CASES, ids=[Path(case["path"]).name for case in NON_OFFER_CASES])
def test_non_offer_corpus(case: dict[str, object]) -> None:
    pdf_path = ROOT / str(case["path"])
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_lines = extract_amount_lines(text)
    totals = parsed.get("totals") or {}

    assert parsed["template"] == case["template"]
    assert parsed["document_type"] == case.get("document_type", "auftragsbestaetigung")
    assert parsed["supplier_name"] == case["supplier_name"]
    assert parsed["document_number"] == case["document_number"]
    assert parsed["document_date"] == case["document_date"]
    assert parsed["project_ref"] == case["project_ref"]
    if "offer_reference" in case:
        assert parsed["offer_reference"] == case["offer_reference"]
    assert len(items) == case["position_count"]
    assert items[0]["description_short"] == case["first_description"]
    assert len(amount_lines) >= 3
    assert totals.get("net_total") == case["net_total"]
    assert totals.get("vat_total") == case["vat_total"]
    assert totals.get("gross_total") == case["gross_total"]
