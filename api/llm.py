import json
import os
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _emit_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    payload: dict[str, Any],
) -> None:
    if callback is None:
        return
    try:
        callback(payload)
    except Exception:
        # Progress reporting must never break extraction.
        return


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


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _normalize_amount_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("amount_lines")
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for idx, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        amount = _clean_text(row.get("amount"))
        if amount is None:
            continue
        line_type = _clean_text(row.get("line_type")) or "other"
        sort_order = _to_int(row.get("sort_order"))
        out.append(
            {
                "line_type": line_type,
                "label_raw": _clean_text(row.get("label_raw")) or line_type,
                "percent_raw": _clean_text(row.get("percent")),
                "base_amount_raw": _clean_text(row.get("base_amount")),
                "amount_raw": amount,
                "sort_order": sort_order if sort_order is not None else idx,
            }
        )

    out.sort(key=lambda item: (item.get("sort_order", 0), item.get("line_type", "")))
    for idx, row in enumerate(out):
        row["sort_order"] = idx
    return out


def _normalize_line_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("line_items")
    if not isinstance(raw, list):
        return []

    out: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        confidence_raw = _to_float(row.get("confidence"))
        if confidence_raw is not None:
            confidence_raw = max(0.0, min(1.0, confidence_raw))
        page_ref = _to_int(row.get("page_ref"))
        if page_ref is not None and page_ref <= 0:
            page_ref = None
        out.append(
            {
                "position_no": _clean_text(row.get("position_no")),
                "lv_pos": _clean_text(row.get("lv_pos")),
                "is_alternative": _to_bool(row.get("is_alternative"), default=False),
                "quantity_raw": _clean_text(row.get("quantity_raw")),
                "unit": _clean_text(row.get("unit")),
                "width_raw": _clean_text(row.get("width_raw")),
                "height_raw": _clean_text(row.get("height_raw")),
                "description_short": _clean_text(row.get("description_short")),
                "description_long": _clean_text(row.get("description_long")),
                "unit_price_raw": _clean_text(row.get("unit_price_raw")),
                "line_total_raw": _clean_text(row.get("line_total_raw")),
                "page_ref": page_ref,
                "confidence": confidence_raw,
            }
        )
    return out


def _split_pages(extracted_text: str) -> list[str]:
    if not extracted_text:
        return []
    text = extracted_text.replace("\r\n", "\n").replace("\r", "\n")
    if "\f" in text:
        parts = text.split("\f")
    else:
        parts = text.split("[PAGE_BREAK]")
    return [part.strip() for part in parts]


def _dedupe_line_items(line_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, int | None, str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in line_items:
        if not isinstance(row, dict):
            continue
        key = (
            (_clean_text(row.get("position_no")) or "").lower(),
            (_clean_text(row.get("lv_pos")) or "").lower(),
            _to_int(row.get("page_ref")),
            (_clean_text(row.get("description_short")) or "").lower(),
            (_clean_text(row.get("description_long")) or "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _likely_line_item_page(page_text: str) -> bool:
    lower = page_text.lower()
    keywords = (
        "pos.",
        "position",
        "lv-pos",
        "b/h",
        "ep:",
        "gp:",
        "stk",
        "stk.",
        "stück",
        "angebot nr",
    )
    return any(keyword in lower for keyword in keywords)


def _extract_fields_and_amount_lines_with_ollama(
    *,
    extracted_text: str,
    base_url: str,
    model: str,
    timeout_seconds: float,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    max_chars_raw = os.getenv("LLM_ONLY_FOCUS_MAX_TEXT_CHARS", "16000").strip()
    try:
        max_chars = max(4000, int(max_chars_raw))
    except ValueError:
        max_chars = 16000

    timeout_raw = os.getenv("LLM_ONLY_FOCUS_TIMEOUT_SECONDS", str(timeout_seconds)).strip()
    try:
        focus_timeout_seconds = max(10.0, float(timeout_raw))
    except ValueError:
        focus_timeout_seconds = timeout_seconds

    text_for_llm = _build_focus_text(extracted_text, max_chars)
    prompt = (
        "You extract document fields and amount lines from a German offer document.\n"
        "Return ONLY valid JSON with this exact schema:\n"
        "{\n"
        '  "document_number": string|null,\n'
        '  "document_date": "DD.MM.YYYY"|null,\n'
        '  "project_ref": string|null,\n'
        '  "currency": string|null,\n'
        '  "supplier_name": string|null,\n'
        '  "totals": {"net_total": string|null, "vat_total": string|null, "gross_total": string|null},\n'
        '  "amount_lines": [\n'
        '    {"line_type": string, "label_raw": string, "percent": string|null, "base_amount": string|null, "amount": string, "sort_order": int}\n'
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- Use null for unknown values.\n"
        "- Keep decimal values in German format with comma, e.g. 7.578,85.\n"
        "- Do not add keys outside schema.\n"
        "- Do not add explanations.\n\n"
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
    _emit_progress(
        progress_callback,
        {
            "stage": "llm_fields_amount",
            "message": "LLM extrahiert Felder und Betragszeilen.",
            "step": 1,
            "total": 1,
        },
    )

    try:
        response = _post_json(f"{base_url}/api/generate", payload, focus_timeout_seconds)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "status": "error",
            "error": str(exc),
            "fields": {},
            "amount_lines": [],
            "raw_text": None,
        }

    raw_text = str(response.get("response") or "")
    parsed_obj = _extract_json_object(raw_text)
    if parsed_obj is None:
        return {
            "ok": False,
            "status": "invalid_json",
            "error": "Could not parse JSON object from LLM response.",
            "fields": {},
            "amount_lines": [],
            "raw_text": raw_text[:3000],
        }

    return {
        "ok": True,
        "status": "ok",
        "error": None,
        "fields": _normalize_llm_fields(parsed_obj),
        "amount_lines": _normalize_amount_lines(parsed_obj),
        "raw_text": raw_text[:3000],
    }


def _extract_line_items_pagewise_with_ollama(
    *,
    extracted_text: str,
    base_url: str,
    model: str,
    timeout_seconds: float,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    pages = _split_pages(extracted_text)
    if not pages:
        return {
            "ok": False,
            "status": "no_pages",
            "error": "No text pages available for LLM line-item extraction.",
            "line_items": [],
            "page_errors": [],
        }

    max_pages_raw = os.getenv("LLM_ONLY_MAX_PAGES", "64").strip()
    try:
        max_pages = max(1, int(max_pages_raw))
    except ValueError:
        max_pages = 64
    pages = pages[:max_pages]

    max_chars_raw = os.getenv("LLM_ONLY_PAGE_MAX_TEXT_CHARS", "7000").strip()
    try:
        max_chars = max(1200, int(max_chars_raw))
    except ValueError:
        max_chars = 7000

    timeout_raw = os.getenv("LLM_ONLY_PAGE_TIMEOUT_SECONDS", "50").strip()
    try:
        page_timeout_seconds = max(10.0, float(timeout_raw))
    except ValueError:
        page_timeout_seconds = min(timeout_seconds, 50.0)

    max_page_calls_raw = os.getenv("LLM_ONLY_MAX_PAGE_CALLS", "18").strip()
    try:
        max_page_calls = max(1, int(max_page_calls_raw))
    except ValueError:
        max_page_calls = 18

    line_items_all: list[dict[str, Any]] = []
    page_errors: list[dict[str, Any]] = []
    page_calls = 0

    for page_index, page_text in enumerate(pages, start=1):
        if not page_text or not _likely_line_item_page(page_text):
            continue
        if page_calls >= max_page_calls:
            break
        page_calls += 1
        _emit_progress(
            progress_callback,
            {
                "stage": "llm_page_extract",
                "message": f"LLM extrahiert Positionen aus Seite {page_index}.",
                "page_ref": page_index,
                "step": page_calls,
                "total": max_page_calls,
            },
        )
        snippet = page_text[:max_chars]
        prompt = (
            "You extract offer line items from ONE page of a German document.\n"
            "Return ONLY valid JSON with this exact schema:\n"
            "{\n"
            '  "line_items": [\n'
            '    {"position_no": string|null, "lv_pos": string|null, "is_alternative": boolean, "quantity_raw": string|null, "unit": string|null, "width_raw": string|null, "height_raw": string|null, "description_short": string|null, "description_long": string|null, "unit_price_raw": string|null, "line_total_raw": string|null, "page_ref": int|null, "confidence": number|null}\n'
            "  ]\n"
            "}\n"
            "Rules:\n"
            "- Use null for unknown values.\n"
            "- Include only line items visible in this page text.\n"
            f"- page_ref should be {page_index} for extracted rows from this page.\n"
            "- Do not add any text outside JSON.\n\n"
            f"Page number: {page_index}\n"
            f"Page text:\n{snippet}\n"
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
            response = _post_json(f"{base_url}/api/generate", payload, page_timeout_seconds)
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            page_errors.append({"page_ref": page_index, "status": "error", "error": str(exc)})
            continue

        raw_text = str(response.get("response") or "")
        parsed_obj = _extract_json_object(raw_text)
        if parsed_obj is None:
            page_errors.append(
                {"page_ref": page_index, "status": "invalid_json", "error": "Could not parse JSON object from response."}
            )
            continue

        normalized = _normalize_line_items(parsed_obj)
        for row in normalized:
            page_ref = _to_int(row.get("page_ref"))
            if page_ref is None or page_ref <= 0:
                row["page_ref"] = page_index
        line_items_all.extend(normalized)

    line_items_all = _dedupe_line_items(line_items_all)
    return {
        "ok": bool(line_items_all),
        "status": "ok" if line_items_all else "empty_fields",
        "error": None if line_items_all else "No line items extracted from per-page LLM calls.",
        "line_items": line_items_all,
        "page_errors": page_errors,
        "pages_processed": len(pages),
        "page_calls": page_calls,
    }


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


def extract_document_full_with_ollama(
    *,
    extracted_text: str,
    timeout_seconds: float = 120.0,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    max_chars_raw = os.getenv("LLM_ONLY_MAX_TEXT_CHARS", "20000").strip()
    try:
        max_chars = max(6000, int(max_chars_raw))
    except ValueError:
        max_chars = 20000

    text_for_llm = extracted_text.replace("\f", "\n[PAGE_BREAK]\n")[:max_chars]
    prompt = (
        "You extract a full structured result from a German offer document.\n"
        "Return ONLY valid JSON with this exact schema:\n"
        "{\n"
        '  "document_number": string|null,\n'
        '  "document_date": "DD.MM.YYYY"|null,\n'
        '  "project_ref": string|null,\n'
        '  "currency": string|null,\n'
        '  "supplier_name": string|null,\n'
        '  "totals": {"net_total": string|null, "vat_total": string|null, "gross_total": string|null},\n'
        '  "amount_lines": [\n'
        '    {"line_type": string, "label_raw": string, "percent": string|null, "base_amount": string|null, "amount": string, "sort_order": int}\n'
        "  ],\n"
        '  "line_items": [\n'
        '    {"position_no": string|null, "lv_pos": string|null, "is_alternative": boolean, "quantity_raw": string|null, "unit": string|null, "width_raw": string|null, "height_raw": string|null, "description_short": string|null, "description_long": string|null, "unit_price_raw": string|null, "line_total_raw": string|null, "page_ref": int|null, "confidence": number|null}\n'
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- Use null for unknown values.\n"
        "- Keep decimal values in German format with comma, e.g. 7.578,85.\n"
        "- Do not add explanations.\n"
        "- Do not add keys outside the schema.\n"
        "- line_items must represent all detected positions.\n"
        "- page_ref is 1-based page index and should align with [PAGE_BREAK] markers when possible.\n\n"
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

    full_pass_error: str | None = None
    full_pass_raw_text: str | None = None
    full_pass_timeout_raw = os.getenv("LLM_ONLY_FULL_PASS_TIMEOUT_SECONDS", "75").strip()
    try:
        full_pass_timeout_seconds = max(10.0, float(full_pass_timeout_raw))
    except ValueError:
        full_pass_timeout_seconds = 75.0
    full_pass_timeout_seconds = min(timeout_seconds, full_pass_timeout_seconds)

    try:
        full_pass_enabled = len(text_for_llm) <= 14000
        if full_pass_enabled:
            _emit_progress(
                progress_callback,
                {
                    "stage": "llm_full_pass",
                    "message": "LLM full-pass Extraktion gestartet.",
                    "step": 1,
                    "total": 1,
                },
            )
            response = _post_json(f"{base_url}/api/generate", payload, full_pass_timeout_seconds)
            full_pass_raw_text = str(response.get("response") or "")
            parsed_obj = _extract_json_object(full_pass_raw_text)
            if parsed_obj is not None:
                fields = _normalize_llm_fields(parsed_obj)
                amount_lines = _normalize_amount_lines(parsed_obj)
                line_items = _normalize_line_items(parsed_obj)
                if _has_any_non_null_field(fields) or line_items:
                    return {
                        "ok": True,
                        "status": "ok",
                        "model": model,
                        "error": None,
                        "raw_text": full_pass_raw_text[:4000],
                        "fields": fields,
                        "amount_lines": amount_lines,
                        "line_items": line_items,
                    }
                full_pass_error = "LLM full pass returned no usable fields or line items."
            else:
                full_pass_error = "Could not parse JSON object from LLM full pass."
        else:
            full_pass_error = "LLM full pass skipped for large document."
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        full_pass_error = str(exc)

    # Fallback for large documents: separate extraction for fields/totals and per-page line-items.
    fields_amount_result = _extract_fields_and_amount_lines_with_ollama(
        extracted_text=extracted_text,
        base_url=base_url,
        model=model,
        timeout_seconds=timeout_seconds,
        progress_callback=progress_callback,
    )
    line_items_result = _extract_line_items_pagewise_with_ollama(
        extracted_text=extracted_text,
        base_url=base_url,
        model=model,
        timeout_seconds=timeout_seconds,
        progress_callback=progress_callback,
    )

    fields = fields_amount_result.get("fields")
    fields = fields if isinstance(fields, dict) else {}
    amount_lines = fields_amount_result.get("amount_lines")
    amount_lines = amount_lines if isinstance(amount_lines, list) else []
    line_items = line_items_result.get("line_items")
    line_items = line_items if isinstance(line_items, list) else []
    page_errors = line_items_result.get("page_errors")
    page_errors = page_errors if isinstance(page_errors, list) else []

    if _has_any_non_null_field(fields) or line_items:
        return {
            "ok": True,
            "status": "ok_fallback_pagewise",
            "model": model,
            "error": full_pass_error,
            "raw_text": full_pass_raw_text[:4000] if full_pass_raw_text else None,
            "fields": fields,
            "amount_lines": amount_lines,
            "line_items": line_items,
            "fallback": {
                "fields_status": fields_amount_result.get("status"),
                "line_items_status": line_items_result.get("status"),
                "pages_processed": line_items_result.get("pages_processed"),
                "page_calls": line_items_result.get("page_calls"),
                "page_errors": page_errors[:20],
            },
        }

    fallback_error = [
        full_pass_error,
        fields_amount_result.get("error"),
        line_items_result.get("error"),
    ]
    fallback_error = [part for part in fallback_error if isinstance(part, str) and part.strip()]
    return {
        "ok": False,
        "status": "error",
        "model": model,
        "error": " | ".join(fallback_error)[:1500] if fallback_error else "LLM extraction failed.",
        "raw_text": full_pass_raw_text[:4000] if full_pass_raw_text else None,
        "fields": fields,
        "amount_lines": amount_lines,
        "line_items": line_items,
        "fallback": {
            "fields_status": fields_amount_result.get("status"),
            "line_items_status": line_items_result.get("status"),
            "pages_processed": line_items_result.get("pages_processed"),
            "page_calls": line_items_result.get("page_calls"),
            "page_errors": page_errors[:20],
        },
    }
