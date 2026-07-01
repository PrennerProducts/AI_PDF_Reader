import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import template_alu_one


HEADER = "Pos.      Menge Einh.   Artikel                                       EP        GP\n"


def test_order_confirmation_reads_amount_before_currency():
    # alu-one Auftragsbestaetigung: Betrag steht VOR der Waehrung ("1.818,39 €").
    text = (
        HEADER
        + "001          1,00  Stk   Fensterelement 3260 mm x 1990 mm"
        + "                           1.818,39 €      1.818,39 €\n"
    )
    items = template_alu_one.extract_line_items(text)
    assert len(items) == 1
    assert items[0]["position_no"] == "001"
    assert items[0]["unit_price_raw"] == "1.818,39"
    assert items[0]["line_total_raw"] == "1.818,39"
    # Der Preis darf NICHT mehr in der Kurzbeschreibung landen.
    assert items[0]["description_short"] == "Fensterelement 3260 mm x 1990 mm"


def test_offer_still_reads_currency_before_amount():
    # alu-one Angebot: Waehrung steht VOR dem Betrag ("EUR 2.500,00") - darf nicht brechen.
    text = (
        HEADER
        + "001          1,00  Stk   Fensterelement"
        + "                                      EUR 2.500,00   EUR 2.500,00\n"
    )
    items = template_alu_one.extract_line_items(text)
    assert len(items) == 1
    assert items[0]["unit_price_raw"] == "2.500,00"
    assert items[0]["line_total_raw"] == "2.500,00"
