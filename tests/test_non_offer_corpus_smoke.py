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
        "path": "samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schuchter/26020.pdf",
        "template": "schuchter",
        "supplier_name": "SCHUCHTER Fenster GmbH",
        "document_number": "26020",
        "document_date": "07.02.2026",
        "project_ref": "SR/KH-Felben-1.AK",
        "position_count": 49,
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
        "position_count": 34,
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
    assert parsed["supplier_name"] == case["supplier_name"]
    assert parsed["document_number"] == case["document_number"]
    assert parsed["document_date"] == case["document_date"]
    assert parsed["project_ref"] == case["project_ref"]
    assert len(items) == case["position_count"]
    assert items[0]["description_short"] == case["first_description"]
    assert len(amount_lines) >= 3
    assert totals.get("net_total") == case["net_total"]
    assert totals.get("vat_total") == case["vat_total"]
    assert totals.get("gross_total") == case["gross_total"]
