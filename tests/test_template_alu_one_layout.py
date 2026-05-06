import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import template_alu_one


class _FakePage:
    def __init__(self, height: float, blocks: list[dict]):
        self.rect = type("Rect", (), {"height": height})()
        self._blocks = blocks

    def get_text(self, mode: str):
        assert mode == "dict"
        return {"blocks": self._blocks}


class _FakeDoc:
    def __init__(self, pages: list[_FakePage]):
        self._pages = pages
        self.page_count = len(pages)

    def load_page(self, idx: int):
        return self._pages[idx]

    def close(self):
        return None


def _line(text: str, x0: float, y0: float) -> dict:
    return {
        "bbox": [x0, y0, x0 + 100.0, y0 + 10.0],
        "spans": [{"text": text}],
    }


def test_extract_line_item_layout_hints_groups_split_header_row(monkeypatch) -> None:
    fake_pages = [
        _FakePage(
            1000.0,
            [
                {
                    "type": 0,
                    "lines": [
                        _line("007", 48.0, 507.6),
                        _line("1,00 Stk", 92.0, 507.6),
                        _line("Türelement 2500 mm x 2135 mm 1.7", 150.0, 507.6),
                        _line("€ 1.725,57", 500.0, 507.6),
                        _line("€ 1.725,57", 610.0, 507.6),
                        _line("Pos 007", 48.0, 530.0),
                    ],
                }
            ],
        )
    ]

    monkeypatch.setattr(template_alu_one.fitz, "open", lambda _: _FakeDoc(fake_pages))

    hints = template_alu_one.extract_line_item_layout_hints(Path("/tmp/fake.pdf"))

    assert hints == [
        {
            "position_no": "007",
            "page_ref": 1,
            "item_top_ratio": 0.5076,
        }
    ]


def test_extract_line_items_accepts_dash_subpositions() -> None:
    text = """
Angebot: 2400061DL-1 Seite: 19
 014-1       3,00 Stk   Fensterelemente 2010 mm x 1010 mm 1.15                   € 304,94      € 914,82
                      Pos 014-1
 014-2       3,00 Stk   Fensterelemente 2010 mm x 1010 mm 1.15                   € 290,56      € 871,68
                      Pos 014-2
 015         3,00 Stk   Fensterelemente 1010 mm x 1010 mm 1.16                   € 220,14      € 660,42
"""

    items = template_alu_one.extract_line_items(text)

    assert [item["position_no"] for item in items] == ["014-1", "014-2", "015"]
