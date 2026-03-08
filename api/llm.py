import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    if not raw_text:
        return None
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start < 0 or end <= start:
        return None
    payload = raw_text[start : end + 1]
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _build_focus_text(extracted_text: str, max_chars: int) -> str:
    lines = [line.strip() for line in extracted_text.splitlines()]
    selected: list[str] = []
    seen: set[str] = set()

    def _add_line(line: str) -> None:
        text = line.strip()
        if not text or text in seen:
            return
        seen.add(text)
        selected.append(text)

    # Keep start of document where header fields usually appear.
    for line in lines[:140]:
        _add_line(line)

    keywords = (
        "angebot",
        "angebotsnummer",
        "kommission",
        "datum",
        "belegdatum",
        "netto",
        "mehrwertsteuer",
        "mwst",
        "angebotssumme",
        "gesamtsumme",
        "summe",
        "projekt",
    )
    for line in lines:
        lower = line.lower()
        if any(keyword in lower for keyword in keywords):
            _add_line(line)

    result = "\n".join(selected)
    return result[:max_chars]


def _post_json(url: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Unexpected non-object JSON response from LLM endpoint.")
    return parsed


def _normalize_llm_fields(payload: dict[str, Any]) -> dict[str, Any]:
    totals = payload.get("totals")
    totals = totals if isinstance(totals, dict) else {}
    return {
        "document_number": _clean_text(payload.get("document_number")),
        "document_date": _clean_text(payload.get("document_date")),
        "project_ref": _clean_text(payload.get("project_ref")),
        "currency": _clean_text(payload.get("currency")),
        "supplier_name": _clean_text(payload.get("supplier_name")),
        "totals": {
            "net_total": _clean_text(totals.get("net_total")),
            "vat_total": _clean_text(totals.get("vat_total")),
            "gross_total": _clean_text(totals.get("gross_total")),
        },
    }


def _has_any_non_null_field(fields: dict[str, Any]) -> bool:
    if any(fields.get(key) for key in ("document_number", "document_date", "project_ref", "currency", "supplier_name")):
        return True
    totals = fields.get("totals")
    if isinstance(totals, dict) and any(totals.get(key) for key in ("net_total", "vat_total", "gross_total")):
        return True
    return False


def enrich_document_fields_with_ollama(
    *,
    extracted_text: str,
    parser_snapshot: dict[str, Any],
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    max_chars_raw = os.getenv("LLM_MAX_TEXT_CHARS", "8000").strip()
    try:
        max_chars = max(2000, int(max_chars_raw))
    except ValueError:
        max_chars = 8000

    text_for_llm = _build_focus_text(extracted_text, max_chars)
    prompt = (
        "You extract fields from a German offer document.\n"
        "Return ONLY valid JSON with this exact schema:\n"
        "{\n"
        '  "document_number": string|null,\n'
        '  "document_date": "DD.MM.YYYY"|null,\n'
        '  "project_ref": string|null,\n'
        '  "currency": string|null,\n'
        '  "supplier_name": string|null,\n'
        '  "totals": {"net_total": string|null, "vat_total": string|null, "gross_total": string|null}\n'
        "}\n"
        "Rules:\n"
        "- Use null for unknown values.\n"
        "- Keep decimal values in German format with comma, e.g. 7.578,85.\n"
        "- Do not add explanations.\n"
        "- Do not add keys outside the schema.\n"
        "- Do not summarize the document.\n\n"
        f"Current parser snapshot (can be corrected if needed):\n{json.dumps(parser_snapshot, ensure_ascii=True)}\n\n"
        f"Document text:\n{text_for_llm}\n"
    )
    payload = {
        "model": model,
        "system": "Return valid JSON only. No prose.",
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }

    try:
        response = _post_json(f"{base_url}/api/generate", payload, timeout_seconds)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "status": "error",
            "model": model,
            "error": str(exc),
            "raw_text": None,
            "fields": {},
        }

    raw_text = str(response.get("response") or "")
    parsed_obj = _extract_json_object(raw_text)
    if parsed_obj is None:
        return {
            "ok": False,
            "status": "invalid_json",
            "model": model,
            "error": "Could not parse JSON object from LLM response.",
            "raw_text": raw_text[:2000],
            "fields": {},
        }

    fields = _normalize_llm_fields(parsed_obj)
    if not _has_any_non_null_field(fields):
        return {
            "ok": False,
            "status": "empty_fields",
            "model": model,
            "error": "LLM response did not contain usable extraction fields.",
            "raw_text": raw_text[:2000],
            "fields": fields,
        }

    return {
        "ok": True,
        "status": "ok",
        "model": model,
        "error": None,
        "raw_text": raw_text[:2000],
        "fields": fields,
    }
