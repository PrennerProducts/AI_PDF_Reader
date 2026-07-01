import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

import main
from main import DocumentLinkedOfferRequest, set_document_linked_offer_endpoint


class _FakeRequest:
    """Minimal stand-in; the endpoint only forwards it to _audit."""


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    monkeypatch.setattr(main, "_audit", lambda *args, **kwargs: None)


def _install_documents(monkeypatch, documents: dict[int, dict], captured: dict):
    monkeypatch.setattr(main, "get_document", lambda doc_id: documents.get(doc_id))

    def _fake_set(document_id, *, linked_offer_document_id, offer_reference):
        captured["document_id"] = document_id
        captured["linked_offer_document_id"] = linked_offer_document_id
        captured["offer_reference"] = offer_reference
        return {
            "id": document_id,
            "offer_reference": offer_reference,
            "linked_offer_document_id": linked_offer_document_id,
            "updated_at": "2026-07-01T00:00:00+00:00",
        }

    monkeypatch.setattr(main, "set_document_linked_offer", _fake_set)


def test_links_offer_and_mirrors_document_number(monkeypatch):
    captured: dict = {}
    documents = {
        48: {"id": 48, "document_type": "auftragsbestaetigung", "supplier_name": "NeWo"},
        49: {"id": 49, "document_type": "angebot", "supplier_name": "NeWo", "document_number": "AN-2026-500"},
    }
    _install_documents(monkeypatch, documents, captured)

    result = set_document_linked_offer_endpoint(
        48, DocumentLinkedOfferRequest(linked_offer_document_id=49), _FakeRequest()
    )

    assert result["ok"] is True
    assert result["linked_offer_document_id"] == 49
    # offer_reference wird auf die Angebotsnummer gespiegelt (refresh-konsistent).
    assert captured["offer_reference"] == "AN-2026-500"
    assert captured["linked_offer_document_id"] == 49


def test_clearing_link_passes_none(monkeypatch):
    captured: dict = {}
    documents = {
        48: {"id": 48, "document_type": "auftragsbestaetigung", "supplier_name": "NeWo"},
    }
    _install_documents(monkeypatch, documents, captured)

    result = set_document_linked_offer_endpoint(
        48, DocumentLinkedOfferRequest(linked_offer_document_id=None), _FakeRequest()
    )

    assert result["linked_offer_document_id"] is None
    assert captured["linked_offer_document_id"] is None
    # Kein Angebot gewaehlt -> offer_reference bleibt unangetastet (None -> COALESCE).
    assert captured["offer_reference"] is None


def test_rejects_offer_from_other_supplier(monkeypatch):
    captured: dict = {}
    documents = {
        48: {"id": 48, "document_type": "auftragsbestaetigung", "supplier_name": "NeWo"},
        49: {"id": 49, "document_type": "angebot", "supplier_name": "Schlotterer", "document_number": "AN-9"},
    }
    _install_documents(monkeypatch, documents, captured)

    with pytest.raises(HTTPException) as exc_info:
        set_document_linked_offer_endpoint(
            48, DocumentLinkedOfferRequest(linked_offer_document_id=49), _FakeRequest()
        )

    assert exc_info.value.status_code == 400
    assert "Lieferant" in exc_info.value.detail
    assert "linked_offer_document_id" not in captured


def test_rejects_non_offer_target(monkeypatch):
    captured: dict = {}
    documents = {
        48: {"id": 48, "document_type": "auftragsbestaetigung", "supplier_name": "NeWo"},
        50: {"id": 50, "document_type": "auftragsbestaetigung", "supplier_name": "NeWo", "document_number": "AB-2"},
    }
    _install_documents(monkeypatch, documents, captured)

    with pytest.raises(HTTPException) as exc_info:
        set_document_linked_offer_endpoint(
            48, DocumentLinkedOfferRequest(linked_offer_document_id=50), _FakeRequest()
        )

    assert exc_info.value.status_code == 400
    assert "kein Angebot" in exc_info.value.detail


def test_missing_target_offer_is_rejected(monkeypatch):
    captured: dict = {}
    documents = {
        48: {"id": 48, "document_type": "auftragsbestaetigung", "supplier_name": "NeWo"},
    }
    _install_documents(monkeypatch, documents, captured)

    with pytest.raises(HTTPException) as exc_info:
        set_document_linked_offer_endpoint(
            48, DocumentLinkedOfferRequest(linked_offer_document_id=999), _FakeRequest()
        )

    assert exc_info.value.status_code == 400
