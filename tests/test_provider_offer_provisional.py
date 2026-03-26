import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from parser import parse_document_text
from structured_parser import extract_line_items


def test_schuchter_offer_like_text_detects_provider_and_headers() -> None:
    text = """
SCHUCHTER Fenster GmbH
ANGEBOT AN-26020
Datum: 07.02.2026
Bauvorhaben: SR/KH-Felben-1.AK

Pos.
1 2 Stck 2-flg.Fenster, D/DK-Stulp
B/H: 1800 x 2300
1.234,50 2.469,00

Summe Netto 2.469,00
MwSt 493,80
Summe Brutto 2.962,80
""".strip()

    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "schuchter"
    assert parsed["document_type"] == "angebot"
    assert parsed["document_number"] == "AN-26020"
    assert parsed["document_date"] == "07.02.2026"
    assert parsed["project_ref"] == "SR/KH-Felben-1.AK"
    assert len(items) == 1
    assert items[0]["description_short"] == "2-flg.Fenster, D/DK-Stulp"


def test_schlotterer_offer_like_text_detects_provider_and_headers() -> None:
    text = """
Schlotterer Sonnenschutz Systeme GmbH
Angebot: 260015417 vom 27.02.2026
Kommission: Libiseller

1 A1 2 Panzer Rollladen 100,00 200,00
Breite: 1200mm
Höhe: 1400mm

Gesamt Nettosumme 200,00
MwSt 40,00
Gesamtsumme 240,00
""".strip()

    parsed = parse_document_text(text)
    items = extract_line_items(text, parsed["template"])

    assert parsed["template"] == "schlotterer"
    assert parsed["document_type"] == "angebot"
    assert parsed["document_number"] == "260015417"
    assert parsed["document_date"] == "27.02.2026"
    assert parsed["project_ref"] == "Libiseller"
    assert len(items) == 1
    assert items[0]["description_short"] == "Panzer Rollladen"
