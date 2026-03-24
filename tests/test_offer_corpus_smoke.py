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
        "path": "samples/pdfs/candidates/offers/entholzer/Angebot 12402032-10_20250415_Email.pdf",
        "template": "entholzer",
        "supplier_name": "Entholzer",
        "document_number": "12402032.10",
        "document_date": "10.04.2025",
        "project_ref": "Neue Heimat - Südtiroler Siedlung Kufstein",
        "position_count": 17,
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
        "path": "samples/pdfs/candidates/offers/rieder/131584_Sevignani, zu 130629_3.pdf",
        "template": "rieder",
        "supplier_name": "Rieder",
        "document_number": "131584-2",
        "document_date": "11.06.2025",
        "project_ref": "Sevignani, zu 130629",
        "position_count": 5,
    },
    {
        "path": "samples/pdfs/candidates/offers/rieder/132047_IB-Karlpassage_3.pdf",
        "template": "rieder",
        "supplier_name": "Rieder",
        "document_number": "132047-3",
        "document_date": "23.05.2025",
        "project_ref": "IB-Karlpassage",
        "position_count": 9,
    },
    {
        "path": "samples/pdfs/candidates/offers/rieder/132475_Moonlight - Söll, zu 132207 + 132476_3.pdf",
        "template": "rieder",
        "supplier_name": "Rieder",
        "document_number": "132475-4",
        "document_date": "15.07.2025",
        "project_ref": "Moonlight - Söll, zu 132207 + 132476",
        "position_count": 17,
    },
    {
        "path": "samples/pdfs/candidates/offers/rieder/20260420 SR. Schauraum BV Baumgartner.pdf",
        "template": "rieder",
        "supplier_name": "Rieder",
        "document_number": "20260420",
        "document_date": "11.02.2026",
        "position_count": 8,
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
