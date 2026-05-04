import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from db import _document_reference_key, _find_linked_offer_document_id
from main import _resolve_process_mode


def test_process_mode_accepts_parser_only() -> None:
    assert _resolve_process_mode(process_mode=None, use_ai=False, ai_override=False) == "parser_only"
    assert _resolve_process_mode(process_mode="parser_only", use_ai=False, ai_override=False) == "parser_only"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"process_mode": "hybrid_fill", "use_ai": False, "ai_override": False},
        {"process_mode": "llm_only", "use_ai": False, "ai_override": False},
        {"process_mode": "parser_only", "use_ai": True, "ai_override": False},
        {"process_mode": "parser_only", "use_ai": False, "ai_override": True},
    ],
)
def test_process_mode_rejects_ai_paths(kwargs: dict[str, object]) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _resolve_process_mode(**kwargs)

    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AN-2026-005", "AN2026005"),
        (" VAX 60326 ", "VAX60326"),
        ("angebot: 130 629", "ANGEBOT130629"),
        (None, None),
        ("", None),
    ],
)
def test_document_reference_key_normalizes_offer_numbers(raw: object, expected: str | None) -> None:
    assert _document_reference_key(raw) == expected


class _FakeCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.last_params: tuple[object, ...] | None = None

    def execute(self, _sql: str, params: tuple[object, ...]) -> _FakeCursor:
        self.last_params = params
        return _FakeCursor(self.rows)


def test_find_linked_offer_document_id_matches_normalized_reference() -> None:
    conn = _FakeConnection(
        [
            {"id": 10, "document_number": "AN-2025-001"},
            {"id": 11, "document_number": "VAX 60326"},
        ]
    )

    linked_id = _find_linked_offer_document_id(
        conn,  # type: ignore[arg-type]
        source_document_id=99,
        supplier_name="Rekord Vomp GmbH",
        offer_reference="VAX60326",
    )

    assert linked_id == 11
    assert conn.last_params == (99, "Rekord Vomp GmbH")
