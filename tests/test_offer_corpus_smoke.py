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


GREEN_OFFER_CASES = [
    {
        "path": "samples/pdfs/regression/offers/alu_one/Angebot A2602224MC.pdf",
        "template": "alu_one",
        "supplier_name": "alu-one Metallbaupartner GmbH",
        "document_number": "A2602224MC",
        "document_date": "06.03.2026",
        "position_count": 9,
    },
    {
        "path": "samples/pdfs/regression/offers/alu_one/Angebot C2509283TB.pdf",
        "template": "alu_one",
        "supplier_name": "alu-one Metallbaupartner GmbH",
        "document_number": "C2509283TB",
        "document_date": "10.11.2025",
        "position_count": 9,
    },
    {
        "path": "samples/pdfs/candidates/offers/alu_one/Angebot 2400061DL-1_i.pdf",
        "template": "alu_one",
        "supplier_name": "alu-one Metallbaupartner GmbH",
        "document_number": "2400061DL-1",
        "document_date": "05.02.2024",
        "position_count": 27,
    },
    {
        "path": "samples/pdfs/candidates/offers/alu_one/Angebot A2506340MC-1.pdf",
        "template": "alu_one",
        "supplier_name": "alu-one Metallbaupartner GmbH",
        "document_number": "A2506340MC-1",
        "document_date": "20.08.2025",
        "position_count": 7,
    },
    {
        "path": "samples/pdfs/candidates/offers/alu_one/Angebot C2308329MK.pdf",
        "template": "alu_one",
        "supplier_name": "alu-one Metallbaupartner GmbH",
        "document_number": "C2308329MK",
        "document_date": "22.09.2023",
        "position_count": 13,
    },
    {
        "path": "samples/pdfs/regression/offers/koch/1050685_Angebot.pdf",
        "template": "koch",
        "supplier_name": "Koch Türen GmbH",
        "document_number": "1050685",
        "document_date": "21.01.2026",
        "project_ref": "Krigovszky Martin",
        "position_count": 1,
    },
    {
        "path": "samples/pdfs/candidates/offers/koch/1050211_Angebot.pdf",
        "template": "koch",
        "supplier_name": "Koch Türen GmbH",
        "document_number": "1050211",
        "document_date": "25.11.2025",
        "project_ref": "Kinderkrippe Langkampfen",
        "position_count": 5,
    },
    {
        "path": "samples/pdfs/candidates/offers/koch/1050824_Angebot.pdf",
        "template": "koch",
        "supplier_name": "Koch Türen GmbH",
        "document_number": "1050824",
        "document_date": "28.01.2026",
        "project_ref": "Burtscher Atelier",
        "position_count": 6,
    },
    {
        "path": "samples/pdfs/regression/offers/entholzer/AN Enth neu 12502888-00_20250909_Email.pdf",
        "template": "entholzer",
        "supplier_name": "Entholzer",
        "document_number": "12502888.00",
        "document_date": "09.09.2025",
        "position_count": 22,
    },
    {
        "path": "samples/pdfs/regression/offers/entholzer/Angebot 12503098.01 Gastl.pdf",
        "template": "entholzer",
        "supplier_name": "Entholzer",
        "document_number": "12503098.01",
        "document_date": "29.09.2025",
        "position_count": 13,
    },
    {
        "path": "samples/pdfs/regression/offers/entholzer/Angebot 12600422.00 Bernsteiner.pdf",
        "template": "entholzer",
        "supplier_name": "Entholzer",
        "document_number": "12600422.00",
        "document_date": "03.02.2026",
        "position_count": 18,
    },
    {
        "path": "samples/pdfs/regression/offers/newo/AN BV Gruber NEWO.pdf",
        "template": "newo",
        "supplier_name": "NeWo",
        "document_number": "25004174",
        "document_date": "17.12.2025",
        "position_count": 7,
    },
    {
        "path": "samples/pdfs/regression/offers/newo/AN NEWO BVH Projekt 353 Achhorner.pdf",
        "template": "newo",
        "supplier_name": "NeWo",
        "document_number": "25002995",
        "document_date": "04.09.2025",
        "position_count": 8,
    },
    {
        "path": "samples/pdfs/regression/offers/newo/Angebot BV Praschberger NEWO.pdf",
        "template": "newo",
        "supplier_name": "NeWo",
        "document_number": "25004051",
        "document_date": "02.12.2025",
        "position_count": 40,
    },
    {
        "path": "samples/pdfs/regression/offers/rekord_vomp/Angebot_VAX53456.pdf",
        "template": "rekord_vomp",
        "supplier_name": "Rekord Vomp GmbH",
        "document_number": "VAX53456",
        "document_date": "21.11.2025",
        "position_count": 22,
    },
    {
        "path": "samples/pdfs/regression/offers/rekord_vomp/Angebot_VAX60326.pdf",
        "template": "rekord_vomp",
        "supplier_name": "Rekord Vomp GmbH",
        "document_number": "VAX60326",
        "document_date": "02.02.2026",
        "position_count": 14,
    },
    {
        "path": "samples/pdfs/regression/offers/rekord_vomp/VAX30295.pdf",
        "template": "rekord_vomp",
        "supplier_name": "Rekord Vomp GmbH",
        "document_number": "VAX30295",
        "document_date": "06.10.2025",
        "position_count": 26,
    },
    {
        "path": "samples/pdfs/regression/offers/rieder/20252270 BV Pichlmaier Angebot.pdf",
        "template": "rieder",
        "supplier_name": "Rieder",
        "document_number": "20252270",
        "document_date": "24.09.2025",
        "position_count": 22,
    },
    {
        "path": "samples/pdfs/regression/offers/rieder/AN Rieder F 20252082 BV Achhorner.pdf",
        "template": "rieder",
        "supplier_name": "Rieder",
        "document_number": "20252082",
        "document_date": "05.09.2025",
        "position_count": 5,
    },
    {
        "path": "samples/pdfs/regression/offers/rieder/Angebot BV Gruber Josef neu 16.2. Rieder.pdf",
        "template": "rieder",
        "supplier_name": "Rieder",
        "document_number": "20252974",
        "document_date": "18.02.2026",
        "position_count": 5,
    },
    {
        "path": "samples/pdfs/regression/offers/sr_schauraum/Angebotsnr AN-2025-113 - SR Schauraum GmbH (2).pdf",
        "template": "sr_schauraum",
        "supplier_name": "Lupre AI Solutions",
        "document_number": "AN-2025-113",
        "document_date": "08.12.2025",
        "position_count": 3,
    },
    {
        "path": "samples/pdfs/candidates/offers/entholzer/Angebot 12600512-00_20260209_Email.pdf",
        "template": "entholzer",
        "supplier_name": "Entholzer",
        "document_number": "12600512.00",
        "document_date": "09.02.2026",
        "position_count": 11,
    },
    {
        "path": "samples/pdfs/candidates/offers/entholzer/Angebot 12600930.00 Sagun, Kirchberg in Tirol.pdf",
        "template": "entholzer",
        "supplier_name": "Entholzer",
        "document_number": "12600930.00",
        "document_date": "10.03.2026",
        "position_count": 16,
    },
    {
        "path": "samples/pdfs/candidates/offers/newo/BV Sagun.pdf",
        "template": "newo",
        "supplier_name": "NeWo",
        "document_number": "26000804",
        "document_date": "09.03.2026",
        "position_count": 10,
    },
    {
        "path": "samples/pdfs/candidates/offers/muigg/AN 250947.pdf",
        "template": "muigg",
        "supplier_name": "Muigg",
        "document_number": "250947",
        "document_date": "18.08.2025",
        "project_ref": "BV Pure Kramsach",
        "position_count": 3,
    },
    {
        "path": "samples/pdfs/candidates/offers/muigg/AN 251073.pdf",
        "template": "muigg",
        "supplier_name": "Muigg",
        "document_number": "251073",
        "document_date": "16.09.2025",
        "project_ref": "BV RiederBau Bergresort Buchenstein",
        "position_count": 7,
    },
    {
        "path": "samples/pdfs/regression/offers/muigg/AN 251409.pdf",
        "template": "muigg",
        "supplier_name": "Muigg",
        "document_number": "251409",
        "document_date": "15.12.2025",
        "project_ref": "BV WH Kilian Schwaz",
        "position_count": 9,
    },
    {
        "path": "samples/pdfs/candidates/offers/rieder/20260420 SR. Schauraum BV Baumgartner.pdf",
        "template": "rieder",
        "supplier_name": "Rieder",
        "document_number": "20260420",
        "document_date": "11.02.2026",
        "position_count": 8,
    },
    {
        "path": "samples/pdfs/candidates/offers/schachermayer/SCH Offert 225009480.PDF",
        "template": "schachermayer",
        "supplier_name": "Schachermayer GmbH",
        "document_number": "225009480",
        "document_date": "22.08.2023",
        "project_ref": "Haaser- Zoglauer",
        "position_count": 5,
    },
    {
        "path": "samples/pdfs/regression/offers/schachermayer/SCH Offert 225217709.PDF",
        "template": "schachermayer",
        "supplier_name": "Schachermayer GmbH",
        "document_number": "225217709",
        "document_date": "11.03.2024",
        "project_ref": "01 INNENTÜRELEMENT BIS MST 170",
        "position_count": 4,
    },
]


@pytest.mark.parametrize("case", GREEN_OFFER_CASES, ids=[Path(case["path"]).name for case in GREEN_OFFER_CASES])
def test_green_offer_corpus(case: dict[str, object]) -> None:
    pdf_path = ROOT / str(case["path"])
    text = _read_pdf_text(pdf_path)
    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])
    amount_lines = extract_amount_lines(text)
    totals = parsed.get("totals") or {}

    assert parsed["template"] == case["template"]
    assert parsed["supplier_name"] == case["supplier_name"]
    assert parsed["document_date"] == case["document_date"]
    assert parsed["project_ref"]
    assert len(items) == case["position_count"]
    assert len(amount_lines) >= 3
    assert totals.get("net_total")
    assert totals.get("vat_total")
    assert totals.get("gross_total")

    expected_document_number = case["document_number"]
    if expected_document_number is not None:
        assert parsed["document_number"] == expected_document_number

    expected_project_ref = case.get("project_ref")
    if expected_project_ref is not None:
        assert parsed["project_ref"] == expected_project_ref


def test_rekord_vomp_regression_folder() -> None:
    variant_paths = sorted((ROOT / "samples/pdfs/regression/offers/rekord_vomp").glob("*.pdf"))

    assert [path.name for path in variant_paths] == [
        "Angebot_VAX53456.pdf",
        "Angebot_VAX60326.pdf",
        "VAX30295.pdf",
    ]
