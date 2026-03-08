import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from db import (
    apply_migrations,
    get_document,
    get_document_image,
    get_document_result,
    insert_document,
    list_documents,
    replace_document_images,
    replace_document_amount_lines,
    replace_line_items,
    update_document_parse_result,
    update_document_status,
)
from extractor import extract_pdf_images, extract_pdf_text
from exporter import build_export_content
from image_matcher import rank_line_item_candidates_with_vlm
from llm import enrich_document_fields_with_ollama
from parser import parse_document_text
from structured_parser import extract_amount_lines, extract_line_items

app = FastAPI(title="KI PDF Reader PoC API")

UPLOAD_DIR = Path("/data/uploads")
EXPORT_DIR = Path("/data/exports")
TEXT_DUMP_DIR = Path("/data/logs/extracted_text")
IMAGE_DUMP_DIR = Path("/data/logs/extracted_images")
LLM_DUMP_DIR = Path("/data/logs/llm")
UI_DIR = Path(__file__).resolve().parent / "ui"
UI_INDEX_PATH = UI_DIR / "index.html"
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
SUPPLIER_BY_TEMPLATE = {
    "rieder": "Rieder",
    "entholzer": "Entholzer",
    "newo": "NeWo",
}
PROCESS_MODES = ("parser_only", "hybrid_fill", "llm_override", "llm_only")
COMPARE_FIELDS = (
    "supplier_name",
    "document_number",
    "document_date",
    "project_ref",
    "currency",
    "totals.net_total",
    "totals.vat_total",
    "totals.gross_total",
)


class ParseTextRequest(BaseModel):
    text: str = Field(min_length=1, description="Raw text content extracted from a PDF.")


def _safe_filename(filename: str) -> str:
    base_name = Path(filename).name.strip()
    if not base_name:
        return "upload.pdf"
    sanitized = SAFE_FILENAME_RE.sub("_", base_name).strip("._")
    if not sanitized:
        return "upload.pdf"
    return sanitized


def _parse_eu_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = value.upper().replace("EUR", "").replace("\u20ac", "")
    cleaned = cleaned.replace("−", "-").replace("–", "-")
    cleaned = re.sub(r"[^0-9,.\-]", "", cleaned)
    if not cleaned or cleaned in {"-", "--"}:
        return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_date(date_text: str | None):
    if not date_text:
        return None
    try:
        return datetime.strptime(date_text, "%d.%m.%Y").date()
    except ValueError:
        return None


def _compute_confidence(template: str, position_count: int, has_totals: bool) -> Decimal:
    base = Decimal("0.60")
    if template != "generic":
        base += Decimal("0.20")
    if position_count > 0:
        base += Decimal("0.10")
    if has_totals:
        base += Decimal("0.10")
    return min(base, Decimal("0.99"))


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _clean_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_truthy(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _merge_parser_with_llm_fields(
    parsed: dict[str, Any],
    llm_fields: dict[str, Any],
    *,
    override: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    merged = dict(parsed)
    changes: list[dict[str, Any]] = []

    def _apply_field(field_name: str) -> None:
        parser_value = _clean_optional_str(merged.get(field_name))
        llm_value = _clean_optional_str(llm_fields.get(field_name))
        if llm_value is None:
            return
        if override or parser_value is None:
            if parser_value != llm_value:
                changes.append({"field": field_name, "old": parser_value, "new": llm_value, "applied": True})
            merged[field_name] = llm_value
            return
        if parser_value != llm_value:
            changes.append({"field": field_name, "old": parser_value, "new": llm_value, "applied": False})

    for field in ("document_number", "document_date", "project_ref", "currency"):
        _apply_field(field)

    merged_totals = dict(merged.get("totals") or {})
    llm_totals = llm_fields.get("totals")
    llm_totals = llm_totals if isinstance(llm_totals, dict) else {}
    for field in ("net_total", "vat_total", "gross_total"):
        parser_value = _clean_optional_str(merged_totals.get(field))
        llm_value = _clean_optional_str(llm_totals.get(field))
        if llm_value is None:
            continue
        if override or parser_value is None:
            if parser_value != llm_value:
                changes.append({"field": f"totals.{field}", "old": parser_value, "new": llm_value, "applied": True})
            merged_totals[field] = llm_value
            continue
        if parser_value != llm_value:
            changes.append({"field": f"totals.{field}", "old": parser_value, "new": llm_value, "applied": False})
    merged["totals"] = merged_totals
    return merged, changes


def _build_llm_only_fields(
    parsed: dict[str, Any],
    llm_fields: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    merged = dict(parsed)
    changes: list[dict[str, Any]] = []

    def _set_field(field_name: str) -> None:
        parser_value = _clean_optional_str(parsed.get(field_name))
        llm_value = _clean_optional_str(llm_fields.get(field_name))
        merged[field_name] = llm_value
        if parser_value != llm_value:
            changes.append({"field": field_name, "old": parser_value, "new": llm_value, "applied": True})

    for field in ("document_number", "document_date", "project_ref", "currency"):
        _set_field(field)

    parser_totals = parsed.get("totals")
    parser_totals = parser_totals if isinstance(parser_totals, dict) else {}
    llm_totals = llm_fields.get("totals")
    llm_totals = llm_totals if isinstance(llm_totals, dict) else {}
    merged_totals: dict[str, str | None] = {}
    for field in ("net_total", "vat_total", "gross_total"):
        parser_value = _clean_optional_str(parser_totals.get(field))
        llm_value = _clean_optional_str(llm_totals.get(field))
        merged_totals[field] = llm_value
        if parser_value != llm_value:
            changes.append({"field": f"totals.{field}", "old": parser_value, "new": llm_value, "applied": True})
    merged["totals"] = merged_totals
    return merged, changes


def _document_field_snapshot(parsed: dict[str, Any]) -> dict[str, Any]:
    totals = parsed.get("totals")
    totals = totals if isinstance(totals, dict) else {}
    return {
        "template": _clean_optional_str(parsed.get("template")) or "generic",
        "document_number": _clean_optional_str(parsed.get("document_number")),
        "document_date": _clean_optional_str(parsed.get("document_date")),
        "project_ref": _clean_optional_str(parsed.get("project_ref")),
        "currency": _clean_optional_str(parsed.get("currency")),
        "supplier_name": _clean_optional_str(parsed.get("supplier_name")),
        "totals": {
            "net_total": _clean_optional_str(totals.get("net_total")),
            "vat_total": _clean_optional_str(totals.get("vat_total")),
            "gross_total": _clean_optional_str(totals.get("gross_total")),
        },
    }


def _resolve_process_mode(
    *,
    process_mode: Literal["parser_only", "hybrid_fill", "llm_override", "llm_only"] | None,
    use_llm: bool,
    llm_override: bool,
) -> Literal["parser_only", "hybrid_fill", "llm_override", "llm_only"]:
    if process_mode in PROCESS_MODES:
        return process_mode
    if not use_llm:
        return "parser_only"
    if llm_override:
        return "llm_override"
    return "hybrid_fill"


def _llm_dump_file_path(document_id: int, run_id: str) -> Path:
    return LLM_DUMP_DIR / f"document_{document_id}_{run_id}.json"


def _llm_latest_file_path(document_id: int) -> Path:
    return LLM_DUMP_DIR / f"document_{document_id}.json"


def _extract_run_id_from_filename(document_id: int, file_name: str) -> str | None:
    prefix = f"document_{document_id}_"
    suffix = ".json"
    if not file_name.startswith(prefix) or not file_name.endswith(suffix):
        return None
    run_id = file_name[len(prefix) : -len(suffix)]
    return run_id or None


def _list_llm_dump_files(document_id: int) -> list[Path]:
    pattern = f"document_{document_id}_*.json"
    return sorted(LLM_DUMP_DIR.glob(pattern), key=lambda item: item.name, reverse=True)


def _read_json_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return payload


def _build_llm_run_list_entry(document_id: int, payload: dict[str, Any], path: Path) -> dict[str, Any]:
    result = payload.get("result")
    result = result if isinstance(result, dict) else {}
    changes_raw = payload.get("changes")
    changes = changes_raw if isinstance(changes_raw, list) else []
    applied_count = len([item for item in changes if isinstance(item, dict) and item.get("applied")])
    run_id = _clean_optional_str(payload.get("run_id")) or _extract_run_id_from_filename(document_id, path.name)
    return {
        "run_id": run_id,
        "created_at_utc": payload.get("created_at_utc"),
        "process_mode_requested": payload.get("process_mode_requested"),
        "process_mode_effective": payload.get("process_mode_effective"),
        "llm_requested": payload.get("requested"),
        "llm_enabled_env": payload.get("enabled_env"),
        "llm_enabled_effective": payload.get("enabled_effective"),
        "llm_status": result.get("status"),
        "llm_model": result.get("model"),
        "llm_used": bool(payload.get("enabled_effective") and result.get("ok")),
        "llm_change_count": applied_count,
        "llm_change_total": len(changes),
        "file_name": path.name,
    }


def _get_path_value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current.get(part)
    return current


def _normalize_compare_value(field: str, value: Any) -> str | None:
    text = _clean_optional_str(value)
    if text is None:
        return None
    if field == "document_date":
        parsed_date = _parse_date(text)
        if parsed_date is not None:
            return parsed_date.isoformat()
        return text
    if field == "currency":
        return text.upper()
    if field in {"supplier_name", "project_ref"}:
        collapsed = re.sub(r"\s+", " ", text).strip()
        return collapsed.casefold()
    if field == "document_number":
        return re.sub(r"\s+", "", text)
    if field.startswith("totals."):
        parsed_decimal = _parse_eu_decimal(text)
        if parsed_decimal is not None:
            return str(parsed_decimal)
    return text


def _build_compare_items(parser_snapshot: dict[str, Any], llm_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for field in COMPARE_FIELDS:
        parser_value = _clean_optional_str(_get_path_value(parser_snapshot, field))
        llm_value = _clean_optional_str(_get_path_value(llm_snapshot, field))
        parser_norm = _normalize_compare_value(field, parser_value)
        llm_norm = _normalize_compare_value(field, llm_value)

        if parser_norm is None and llm_norm is None:
            status = "missing_both"
            equal = True
        elif parser_norm is None:
            status = "missing_in_parser"
            equal = False
        elif llm_norm is None:
            status = "missing_in_llm"
            equal = False
        elif parser_norm == llm_norm:
            status = "same"
            equal = True
        else:
            status = "different"
            equal = False

        items.append(
            {
                "field": field,
                "parser_value": parser_value,
                "llm_value": llm_value,
                "parser_normalized": parser_norm,
                "llm_normalized": llm_norm,
                "status": status,
                "equal": equal,
            }
        )
    return items


def _build_compare_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": len(items),
        "same": 0,
        "different": 0,
        "missing_in_parser": 0,
        "missing_in_llm": 0,
        "missing_both": 0,
    }
    for item in items:
        status = item.get("status")
        if status in summary:
            summary[status] += 1
    return summary


def _to_int_safe(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float_safe(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe_int_list(values: list[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _candidate_images_for_item(
    item: dict[str, Any],
    image_by_id: dict[int, dict[str, Any]],
    *,
    max_candidates: int,
) -> list[dict[str, Any]]:
    candidate_ids: list[int] = []
    for key in ("image_ids", "image_ids_page_all"):
        raw = item.get(key)
        if not isinstance(raw, list):
            continue
        for value in raw:
            parsed = _to_int_safe(value)
            if parsed is not None:
                candidate_ids.append(parsed)
    candidate_ids = _dedupe_int_list(candidate_ids)
    if not candidate_ids:
        return []

    page_ref = _to_int_safe(item.get("page_ref"))
    primary_ids_raw = item.get("image_ids_primary")
    primary_ids = {
        parsed
        for parsed in (_to_int_safe(val) for val in (primary_ids_raw if isinstance(primary_ids_raw, list) else []))
        if parsed is not None
    }

    scored: list[tuple[float, dict[str, Any]]] = []
    for image_id in candidate_ids:
        image = image_by_id.get(image_id)
        if image is None:
            continue
        image_page = _to_int_safe(image.get("page_ref"))
        width = _to_int_safe(image.get("width")) or 0
        height = _to_int_safe(image.get("height")) or 0
        area = width * height
        decorative_penalty = -0.80 if image.get("is_probably_decorative") else 0.0
        repeated_penalty = -0.25 if image.get("is_repeated_across_pages") else 0.0
        page_bonus = 0.0
        if page_ref is not None and image_page is not None:
            if page_ref == image_page:
                page_bonus = 0.80
            elif abs(page_ref - image_page) == 1:
                page_bonus = 0.20
        area_bonus = min(0.60, area / 420_000.0) if area > 0 else 0.0
        primary_bonus = 0.20 if image_id in primary_ids else 0.0
        score = page_bonus + area_bonus + primary_bonus + decorative_penalty + repeated_penalty
        scored.append((score, image))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [image for _, image in scored[:max_candidates]]


def _heuristic_match_for_item(
    item: dict[str, Any],
    candidate_images: list[dict[str, Any]],
    *,
    allow_multiple: bool,
) -> dict[str, Any]:
    page_ref = _to_int_safe(item.get("page_ref"))
    primary_ids_raw = item.get("image_ids_primary")
    primary_ids = {
        parsed
        for parsed in (_to_int_safe(val) for val in (primary_ids_raw if isinstance(primary_ids_raw, list) else []))
        if parsed is not None
    }

    score_rows: list[dict[str, Any]] = []
    for image in candidate_images:
        image_id = _to_int_safe(image.get("id"))
        if image_id is None:
            continue
        image_page = _to_int_safe(image.get("page_ref"))
        width = _to_int_safe(image.get("width")) or 0
        height = _to_int_safe(image.get("height")) or 0
        area = width * height
        score = 0.0
        if page_ref is not None and image_page is not None:
            if page_ref == image_page:
                score += 0.85
            elif abs(page_ref - image_page) == 1:
                score += 0.25
        score += min(0.55, area / 420_000.0) if area > 0 else 0.0
        if image_id in primary_ids:
            score += 0.20
        if image.get("is_probably_decorative"):
            score -= 0.75
        if image.get("is_repeated_across_pages"):
            score -= 0.20
        score_rows.append(
            {
                "image_id": image_id,
                "score": round(score, 4),
                "reason": "heuristic(page+area+decorative+primary)",
            }
        )

    score_rows.sort(key=lambda row: row["score"], reverse=True)
    selected_image_ids: list[int] = []
    if score_rows:
        selected_image_ids = [score_rows[0]["image_id"]]
        if allow_multiple and len(score_rows) > 1:
            top = score_rows[0]["score"]
            second = score_rows[1]["score"]
            if second >= top - 0.10 and second >= 0.25:
                selected_image_ids.append(score_rows[1]["image_id"])
    selected_image_ids = _dedupe_int_list(selected_image_ids)

    return {
        "selected_image_ids": selected_image_ids,
        "scores": score_rows,
    }


def _build_amount_line_rows(extracted_text: str, totals: dict[str, str | None]) -> list[dict]:
    rows: list[dict] = []
    for item in extract_amount_lines(extracted_text):
        amount = _parse_eu_decimal(item.get("amount_raw"))
        if amount is None:
            continue
        rows.append(
            {
                "line_type": item.get("line_type", "other"),
                "label_raw": item.get("label_raw", ""),
                "percent": _parse_eu_decimal(item.get("percent_raw")),
                "base_amount": _parse_eu_decimal(item.get("base_amount_raw")),
                "amount": amount,
                "sort_order": item.get("sort_order", 0),
            }
        )

    def _upsert_total_line(
        *,
        line_type: str,
        amount_raw: str | None,
        fallback_label: str,
        percent: Decimal | None = None,
    ) -> None:
        amount = _parse_eu_decimal(amount_raw)
        if amount is None:
            return
        for row in rows:
            if row["line_type"] == line_type:
                row["amount"] = amount
                row["base_amount"] = None
                if percent is not None:
                    row["percent"] = percent
                return
        rows.append(
            {
                "line_type": line_type,
                "label_raw": fallback_label,
                "percent": percent,
                "base_amount": None,
                "amount": amount,
                "sort_order": len(rows),
            }
        )

    _upsert_total_line(line_type="net_total", amount_raw=totals.get("net_total"), fallback_label="Nettosumme")
    _upsert_total_line(
        line_type="vat",
        amount_raw=totals.get("vat_total"),
        fallback_label="Mehrwertsteuer",
        percent=Decimal("20.00"),
    )
    _upsert_total_line(line_type="total", amount_raw=totals.get("gross_total"), fallback_label="Angebotssumme")

    rows = sorted(rows, key=lambda row: (row.get("sort_order", 0), row.get("line_type", "")))
    for idx, row in enumerate(rows):
        row["sort_order"] = idx
    return rows


def _build_line_item_rows(extracted_text: str, template: str) -> list[dict]:
    rows: list[dict] = []
    for item in extract_line_items(extracted_text, template):
        quantity = _parse_eu_decimal(item.get("quantity_raw"))
        width_mm = _parse_eu_decimal(item.get("width_raw"))
        height_mm = _parse_eu_decimal(item.get("height_raw"))
        unit_price = _parse_eu_decimal(item.get("unit_price_raw"))
        line_total = _parse_eu_decimal(item.get("line_total_raw"))
        metadata = {
            "quantity_raw": item.get("quantity_raw"),
            "width_raw": item.get("width_raw"),
            "height_raw": item.get("height_raw"),
            "unit_price_raw": item.get("unit_price_raw"),
            "line_total_raw": item.get("line_total_raw"),
        }
        confidence = Decimal("0.85") if line_total is not None else Decimal("0.70")
        rows.append(
            {
                "position_no": item.get("position_no"),
                "lv_pos": item.get("lv_pos"),
                "is_alternative": bool(item.get("is_alternative", False)),
                "quantity": quantity,
                "unit": item.get("unit"),
                "width_mm": width_mm,
                "height_mm": height_mm,
                "description_short": item.get("description_short"),
                "description_long": item.get("description_long"),
                "unit_price": unit_price,
                "line_total": line_total,
                "page_ref": item.get("page_ref"),
                "confidence": confidence,
                "metadata_json": json.dumps(metadata, ensure_ascii=True),
            }
        )
    return rows


@app.on_event("startup")
def startup() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    LLM_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    applied = apply_migrations()
    if applied:
        print(f"Applied DB migrations: {', '.join(applied)}")


def _write_export_file(document_id: int, extension: str, content: str) -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"document_{document_id}_{timestamp}.{extension}"
    path = EXPORT_DIR / filename
    path.write_text(content, encoding="utf-8")
    return path


@app.get("/health")
def health():
    return {"ok": True, "service": "pdr-api"}


@app.get("/")
def root():
    return {
        "name": "KI-PDF-Reader On-Prem PoC",
        "status": "running",
        "next": [
            "Upload endpoint ready",
            "Extend parser pipeline",
            "Implement JSON/CSV/SQL export",
        ],
    }


@app.get("/ui", response_class=HTMLResponse)
def ui_page():
    if not UI_INDEX_PATH.exists():
        raise HTTPException(status_code=500, detail=f"UI file missing: {UI_INDEX_PATH}")
    return HTMLResponse(
        content=UI_INDEX_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@app.get("/document/{document_id}/file")
def document_file(document_id: int):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    source_path = Path(document["source_file"])
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail=f"Source file not found: {source_path}")
    filename = _safe_filename(document.get("original_filename") or source_path.name)
    headers = {
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": "no-store",
    }
    return FileResponse(source_path, media_type="application/pdf", headers=headers)


@app.get("/document/{document_id}/image/{image_id}")
def document_image(document_id: int, image_id: int):
    image = get_document_image(document_id, image_id)
    if not image:
        raise HTTPException(status_code=404, detail=f"Image {image_id} for document {document_id} not found.")
    image_path = Path(image["storage_path"])
    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail=f"Image file not found: {image_path}")
    media_type = image.get("mime_type") or "application/octet-stream"
    headers = {
        "Content-Disposition": f'inline; filename="{image_path.name}"',
        "Cache-Control": "no-store",
    }
    return FileResponse(image_path, media_type=media_type, headers=headers)


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename.")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    safe_name = _safe_filename(file.filename)
    stored_name = f"{uuid4().hex}_{safe_name}"
    destination = UPLOAD_DIR / stored_name
    size_bytes = 0

    try:
        with destination.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                size_bytes += len(chunk)
    finally:
        await file.close()

    if size_bytes == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    source_file = f"/data/uploads/{stored_name}"
    try:
        doc_row = insert_document(
            source_file=source_file,
            original_filename=file.filename,
            file_size_bytes=size_bytes,
            content_type=file.content_type,
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return {
        "document_id": doc_row["id"],
        "status": doc_row["status"],
        "source_file": doc_row["source_file"],
        "original_filename": doc_row["original_filename"],
        "file_size_bytes": doc_row["file_size_bytes"],
        "content_type": doc_row["content_type"],
        "created_at": doc_row["created_at"],
    }


@app.get("/documents")
def documents(limit: int = Query(default=20, ge=1, le=200)):
    items = list_documents(limit=limit)
    return {"items": items, "count": len(items), "limit": limit}


@app.get("/result/{document_id}")
def result(document_id: int):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    return _json_safe(result_data)


@app.get("/llm-runs/{document_id}")
def list_llm_runs(document_id: int, limit: int = Query(default=20, ge=1, le=200)):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    items: list[dict[str, Any]] = []
    for path in _list_llm_dump_files(document_id)[:limit]:
        try:
            payload = _read_json_file(path)
        except Exception:
            continue
        items.append(_build_llm_run_list_entry(document_id, payload, path))

    return {"document_id": document_id, "items": items, "count": len(items), "limit": limit}


@app.get("/llm-runs/{document_id}/latest")
def latest_llm_run(document_id: int):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    latest_files = _list_llm_dump_files(document_id)
    if latest_files:
        try:
            return _json_safe(_read_json_file(latest_files[0]))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read latest LLM run: {exc}") from exc

    legacy_path = _llm_latest_file_path(document_id)
    if legacy_path.exists():
        try:
            return _json_safe(_read_json_file(legacy_path))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read legacy LLM run: {exc}") from exc

    raise HTTPException(status_code=404, detail=f"No LLM runs found for document {document_id}.")


@app.get("/llm-runs/{document_id}/run/{run_id}")
def llm_run_by_id(document_id: int, run_id: str):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    if not re.match(r"^[A-Za-z0-9._-]+$", run_id):
        raise HTTPException(status_code=400, detail="Invalid run_id format.")

    path = _llm_dump_file_path(document_id, run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"LLM run {run_id} for document {document_id} not found.")

    try:
        return _json_safe(_read_json_file(path))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read LLM run {run_id}: {exc}") from exc


@app.get("/compare/{document_id}")
def compare_document(document_id: int):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    source_path = Path(document["source_file"])
    if not source_path.exists():
        raise HTTPException(status_code=400, detail=f"Source file does not exist: {source_path}")

    llm_enabled_env = _is_truthy(os.getenv("LLM_ENABLED"), default=True)
    llm_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")

    try:
        extracted_text = extract_pdf_text(source_path)
        parsed_base = parse_document_text(extracted_text)
        template = _clean_optional_str(parsed_base.get("template")) or "generic"
        parser_snapshot = _document_field_snapshot(parsed_base)
        parser_supplier = SUPPLIER_BY_TEMPLATE.get(template)
        if parser_snapshot.get("supplier_name") is None and parser_supplier:
            parser_snapshot["supplier_name"] = parser_supplier

        if llm_enabled_env:
            timeout_raw = os.getenv("LLM_TIMEOUT_SECONDS", "120").strip()
            try:
                timeout_seconds = max(5.0, float(timeout_raw))
            except ValueError:
                timeout_seconds = 120.0
            llm_result = enrich_document_fields_with_ollama(
                extracted_text=extracted_text,
                parser_snapshot={
                    "template": parser_snapshot.get("template"),
                    "document_number": parser_snapshot.get("document_number"),
                    "document_date": parser_snapshot.get("document_date"),
                    "project_ref": parser_snapshot.get("project_ref"),
                    "currency": parser_snapshot.get("currency"),
                    "totals": parser_snapshot.get("totals"),
                },
                timeout_seconds=timeout_seconds,
            )
        else:
            llm_result = {
                "ok": False,
                "status": "disabled_env",
                "model": llm_model,
                "error": "LLM disabled via LLM_ENABLED=false.",
                "raw_text": None,
                "fields": {},
            }

        llm_fields = llm_result.get("fields")
        llm_fields = llm_fields if isinstance(llm_fields, dict) else {}
        llm_totals = llm_fields.get("totals")
        llm_totals = llm_totals if isinstance(llm_totals, dict) else {}
        llm_snapshot = {
            "template": template,
            "supplier_name": _clean_optional_str(llm_fields.get("supplier_name")),
            "document_number": _clean_optional_str(llm_fields.get("document_number")),
            "document_date": _clean_optional_str(llm_fields.get("document_date")),
            "project_ref": _clean_optional_str(llm_fields.get("project_ref")),
            "currency": _clean_optional_str(llm_fields.get("currency")),
            "totals": {
                "net_total": _clean_optional_str(llm_totals.get("net_total")),
                "vat_total": _clean_optional_str(llm_totals.get("vat_total")),
                "gross_total": _clean_optional_str(llm_totals.get("gross_total")),
            },
        }

        comparison_items = _build_compare_items(parser_snapshot, llm_snapshot)
        comparison_summary = _build_compare_summary(comparison_items)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Compare failed: {exc}") from exc

    return {
        "document_id": document_id,
        "template": template,
        "llm_enabled_env": llm_enabled_env,
        "llm_used": bool(llm_enabled_env and llm_result.get("ok")),
        "llm_status": llm_result.get("status"),
        "llm_model": llm_result.get("model"),
        "llm_error": llm_result.get("error"),
        "parser_snapshot": parser_snapshot,
        "llm_snapshot": llm_snapshot,
        "comparison": comparison_items,
        "summary": comparison_summary,
    }


@app.post("/match-images/{document_id}")
def match_images(
    document_id: int,
    strategy: Literal["heuristic", "vlm", "hybrid"] = Query(default="hybrid"),
    max_candidates: int = Query(default=4, ge=1, le=10),
    max_items: int = Query(default=60, ge=1, le=500),
    allow_multiple: bool = Query(default=True),
    vlm_min_confidence: float = Query(default=0.55, ge=0.0, le=1.0),
):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Result for document {document_id} not found.")

    line_items_raw = result_data.get("line_items")
    image_rows_raw = result_data.get("images")
    line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []
    image_rows = list(image_rows_raw) if isinstance(image_rows_raw, list) else []

    image_by_id: dict[int, dict[str, Any]] = {}
    for image in image_rows:
        image_id = _to_int_safe(image.get("id"))
        if image_id is not None:
            image_by_id[image_id] = image

    llm_requested = strategy in {"vlm", "hybrid"}
    vlm_enabled_env = _is_truthy(os.getenv("VLM_ENABLED"), default=False)
    vlm_model = os.getenv("OLLAMA_VLM_MODEL", "qwen2.5vl:7b")
    timeout_raw = os.getenv("VLM_TIMEOUT_SECONDS", "90").strip()
    try:
        vlm_timeout_seconds = max(5.0, float(timeout_raw))
    except ValueError:
        vlm_timeout_seconds = 90.0

    items_out: list[dict[str, Any]] = []
    for item in line_items[:max_items]:
        candidates = _candidate_images_for_item(item, image_by_id, max_candidates=max_candidates)
        heuristic = _heuristic_match_for_item(item, candidates, allow_multiple=allow_multiple)
        heuristic_selected = list(heuristic.get("selected_image_ids") or [])

        vlm_result: dict[str, Any] | None = None
        final_selected = heuristic_selected
        final_source = "heuristic"
        final_reason = "heuristic_default"

        if llm_requested and not vlm_enabled_env:
            final_source = "heuristic_fallback_disabled"
            final_reason = "vlm_disabled_env"
        elif strategy in {"vlm", "hybrid"} and candidates:
            vlm_result = rank_line_item_candidates_with_vlm(
                line_item=item,
                candidate_images=candidates,
                timeout_seconds=vlm_timeout_seconds,
            )
            vlm_selected_raw = vlm_result.get("selected_image_ids")
            vlm_selected = list(vlm_selected_raw) if isinstance(vlm_selected_raw, list) else []
            vlm_selected = [image_id for image_id in vlm_selected if _to_int_safe(image_id) is not None]
            vlm_conf = _to_float_safe(vlm_result.get("confidence"))
            vlm_ok = bool(vlm_result.get("ok")) and bool(vlm_selected)

            if strategy == "vlm":
                if vlm_ok:
                    final_selected = vlm_selected
                    final_source = "vlm"
                    final_reason = "vlm_selected"
                else:
                    final_source = "heuristic_fallback"
                    final_reason = "vlm_no_selection"
            elif strategy == "hybrid":
                if vlm_ok and (vlm_conf is None or vlm_conf >= vlm_min_confidence):
                    final_selected = vlm_selected
                    final_source = "vlm"
                    final_reason = "hybrid_vlm_confident"
                elif vlm_ok:
                    final_source = "heuristic"
                    final_reason = "hybrid_vlm_low_confidence"
                else:
                    final_source = "heuristic"
                    final_reason = "hybrid_vlm_no_selection"

        if not allow_multiple and len(final_selected) > 1:
            final_selected = final_selected[:1]
        final_selected = _dedupe_int_list([_to_int_safe(image_id) for image_id in final_selected if _to_int_safe(image_id) is not None])

        candidate_summaries = [
            {
                "image_id": _to_int_safe(image.get("id")),
                "page_ref": _to_int_safe(image.get("page_ref")),
                "mime_type": image.get("mime_type"),
                "width": _to_int_safe(image.get("width")),
                "height": _to_int_safe(image.get("height")),
                "bytes_size": _to_int_safe(image.get("bytes_size")),
                "is_probably_decorative": bool(image.get("is_probably_decorative")),
                "is_repeated_across_pages": bool(image.get("is_repeated_across_pages")),
            }
            for image in candidates
        ]

        items_out.append(
            {
                "line_item_id": _to_int_safe(item.get("id")),
                "position_no": item.get("position_no"),
                "lv_pos": item.get("lv_pos"),
                "page_ref": _to_int_safe(item.get("page_ref")),
                "description_short": item.get("description_short"),
                "candidate_image_ids": [
                    image_id for image_id in (_to_int_safe(image.get("id")) for image in candidates) if image_id is not None
                ],
                "candidate_images": candidate_summaries,
                "heuristic": heuristic,
                "vlm": vlm_result,
                "selected_image_ids": final_selected,
                "selected_primary_image_id": final_selected[0] if final_selected else None,
                "selection_source": final_source,
                "selection_reason": final_reason,
            }
        )

    matched_items = len([item for item in items_out if item.get("selected_image_ids")])
    single_matches = len([item for item in items_out if len(item.get("selected_image_ids") or []) == 1])
    multi_matches = len([item for item in items_out if len(item.get("selected_image_ids") or []) > 1])
    vlm_selected_items = len([item for item in items_out if item.get("selection_source") == "vlm"])
    heuristic_selected_items = len([item for item in items_out if item.get("selection_source", "").startswith("heuristic")])

    return _json_safe(
        {
            "document_id": document_id,
            "strategy_requested": strategy,
            "llm_requested": llm_requested,
            "vlm_enabled_env": vlm_enabled_env,
            "vlm_model": vlm_model,
            "vlm_timeout_seconds": vlm_timeout_seconds,
            "max_candidates": max_candidates,
            "max_items": max_items,
            "allow_multiple": allow_multiple,
            "vlm_min_confidence": vlm_min_confidence,
            "summary": {
                "line_items_processed": len(items_out),
                "line_items_total": len(line_items),
                "matched_items": matched_items,
                "unmatched_items": len(items_out) - matched_items,
                "single_matches": single_matches,
                "multi_matches": multi_matches,
                "vlm_selected_items": vlm_selected_items,
                "heuristic_selected_items": heuristic_selected_items,
            },
            "items": items_out,
        }
    )


@app.get("/preview/{document_id}")
def preview_document(
    document_id: int,
    preview_format: Literal["json", "csv"] = Query(default="json", alias="format"),
):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    _, media_type, content = build_export_content(result_data, preview_format)
    return Response(content=content, media_type=media_type)


@app.get("/export/{document_id}")
def export_document(
    document_id: int,
    export_format: Literal["json", "csv", "sql"] = Query(default="json", alias="format"),
    include_images_base64: bool = Query(default=False),
):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    extension, media_type, content = build_export_content(
        result_data,
        export_format,
        include_images_base64=include_images_base64,
    )
    export_path = _write_export_file(document_id, extension, content)
    headers = {
        "Content-Disposition": f'attachment; filename="{export_path.name}"',
        "X-Export-Path": str(export_path),
    }
    return Response(content=content, media_type=media_type, headers=headers)


@app.post("/process/{document_id}")
def process_document(
    document_id: int,
    process_mode: Literal["parser_only", "hybrid_fill", "llm_override", "llm_only"] | None = Query(default=None),
    use_llm: bool = Query(default=True),
    llm_override: bool = Query(default=False),
):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    source_path = Path(document["source_file"])
    if not source_path.exists():
        update_document_status(document_id, status="failed", error_message=f"File missing: {source_path}")
        raise HTTPException(status_code=400, detail=f"Source file does not exist: {source_path}")

    update_document_status(document_id, status="processing", error_message=None)

    requested_mode = _resolve_process_mode(process_mode=process_mode, use_llm=use_llm, llm_override=llm_override)
    llm_requested = requested_mode != "parser_only"
    llm_enabled_env = _is_truthy(os.getenv("LLM_ENABLED"), default=True)
    llm_enabled = llm_requested and llm_enabled_env
    llm_override_effective = requested_mode == "llm_override"
    llm_result: dict[str, Any] | None = None
    llm_changes: list[dict[str, Any]] = []
    llm_dump_path: str | None = None
    llm_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    llm_run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    llm_run_created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    process_mode_effective = "parser_only"
    template = "generic"
    position_count = 0
    line_item_rows: list[dict[str, Any]] = []
    amount_line_rows: list[dict[str, Any]] = []

    try:
        extracted_text = extract_pdf_text(source_path)
        text_dump_path = TEXT_DUMP_DIR / f"document_{document_id}.txt"
        text_dump_path.write_text(extracted_text, encoding="utf-8")
        image_rows = extract_pdf_images(source_path, IMAGE_DUMP_DIR / f"document_{document_id}")

        parsed_base = parse_document_text(extracted_text)
        parsed = dict(parsed_base)
        template = _clean_optional_str(parsed.get("template")) or "generic"

        if llm_requested and not llm_enabled_env:
            llm_result = {
                "ok": False,
                "status": "disabled_env",
                "model": llm_model,
                "error": "LLM disabled via LLM_ENABLED=false.",
                "raw_text": None,
                "fields": {},
            }
        elif llm_enabled:
            timeout_raw = os.getenv("LLM_TIMEOUT_SECONDS", "120").strip()
            try:
                timeout_seconds = max(5.0, float(timeout_raw))
            except ValueError:
                timeout_seconds = 120.0
            llm_result = enrich_document_fields_with_ollama(
                extracted_text=extracted_text,
                parser_snapshot={
                    "template": parsed_base.get("template"),
                    "document_number": parsed_base.get("document_number"),
                    "document_date": parsed_base.get("document_date"),
                    "project_ref": parsed_base.get("project_ref"),
                    "currency": parsed_base.get("currency"),
                    "totals": parsed_base.get("totals"),
                },
                timeout_seconds=timeout_seconds,
            )
        else:
            llm_result = {
                "ok": False,
                "status": "not_requested",
                "model": llm_model,
                "error": None,
                "raw_text": None,
                "fields": {},
            }

        llm_changes = []
        if llm_enabled and llm_result and llm_result.get("ok"):
            llm_fields = llm_result.get("fields")
            llm_fields = llm_fields if isinstance(llm_fields, dict) else {}
            if requested_mode == "llm_only":
                parsed, llm_changes = _build_llm_only_fields(parsed_base, llm_fields)
            elif requested_mode == "llm_override":
                parsed, llm_changes = _merge_parser_with_llm_fields(parsed_base, llm_fields, override=True)
            else:
                parsed, llm_changes = _merge_parser_with_llm_fields(parsed_base, llm_fields, override=False)

        llm_applied = bool(llm_enabled and llm_result and llm_result.get("ok"))
        if requested_mode == "parser_only":
            process_mode_effective = "parser_only"
        elif llm_applied:
            process_mode_effective = requested_mode
        else:
            process_mode_effective = "parser_only_fallback"

        llm_dump_payload = {
            "run_id": llm_run_id,
            "created_at_utc": llm_run_created_at,
            "document_id": document_id,
            "process_mode_requested": requested_mode,
            "process_mode_effective": process_mode_effective,
            "requested": llm_requested,
            "enabled_env": llm_enabled_env,
            "enabled_effective": llm_enabled,
            "override": llm_override_effective,
            "llm_only": requested_mode == "llm_only",
            "result": llm_result,
            "parser_snapshot_before": _document_field_snapshot(parsed_base),
            "parser_snapshot_after": _document_field_snapshot(parsed),
            "changes": llm_changes,
        }
        llm_dump_file = _llm_dump_file_path(document_id, llm_run_id)
        llm_dump_latest_file = _llm_latest_file_path(document_id)
        try:
            llm_dump_file.write_text(json.dumps(llm_dump_payload, ensure_ascii=True, indent=2), encoding="utf-8")
            llm_dump_latest_file.write_text(json.dumps(llm_dump_payload, ensure_ascii=True, indent=2), encoding="utf-8")
            llm_dump_path = str(llm_dump_file)
        except Exception:
            llm_dump_path = None

        totals = parsed.get("totals")
        totals = totals if isinstance(totals, dict) else {}
        net_total = _parse_eu_decimal(totals.get("net_total"))
        vat_total = _parse_eu_decimal(totals.get("vat_total"))
        gross_total = _parse_eu_decimal(totals.get("gross_total"))
        date_value = _parse_date(parsed.get("document_date"))
        supplier_name = SUPPLIER_BY_TEMPLATE.get(template)
        llm_supplier = _clean_optional_str((llm_result or {}).get("fields", {}).get("supplier_name"))
        if requested_mode == "llm_only":
            supplier_name = llm_supplier
        elif llm_supplier and (supplier_name is None or llm_override_effective):
            supplier_name = llm_supplier
        amount_line_rows = _build_amount_line_rows(extracted_text, totals)
        line_item_rows = _build_line_item_rows(extracted_text, template)
        replace_document_amount_lines(document_id, amount_line_rows)
        replace_line_items(document_id, line_item_rows)
        replace_document_images(document_id, image_rows)

        position_count = len(line_item_rows) if line_item_rows else int(parsed.get("position_count", 0) or 0)
        confidence = _compute_confidence(
            template=template,
            position_count=position_count,
            has_totals=any(v is not None for v in (net_total, vat_total, gross_total)),
        )

        updated = update_document_parse_result(
            document_id,
            supplier_name=supplier_name,
            document_number=parsed.get("document_number"),
            document_date=date_value,
            project_ref=parsed.get("project_ref"),
            currency=parsed.get("currency") or "EUR",
            net_total=net_total,
            vat_total=vat_total,
            gross_total=gross_total,
            parse_confidence=confidence,
            raw_text_path=str(text_dump_path),
            status="processed",
        )
    except HTTPException:
        raise
    except Exception as exc:
        update_document_status(document_id, status="failed", error_message=str(exc)[:1000])
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc

    return {
        "document_id": updated["id"],
        "status": updated["status"],
        "template": template,
        "position_count": position_count,
        "line_item_count": len(line_item_rows),
        "amount_line_count": len(amount_line_rows),
        "image_count": len(image_rows),
        "supplier_name": updated["supplier_name"],
        "document_number": updated["document_number"],
        "document_date": str(updated["document_date"]) if updated["document_date"] else None,
        "project_ref": updated["project_ref"],
        "currency": updated["currency"],
        "net_total": str(updated["net_total"]) if updated["net_total"] is not None else None,
        "vat_total": str(updated["vat_total"]) if updated["vat_total"] is not None else None,
        "gross_total": str(updated["gross_total"]) if updated["gross_total"] is not None else None,
        "parse_confidence": str(updated["parse_confidence"]) if updated["parse_confidence"] is not None else None,
        "raw_text_path": updated["raw_text_path"],
        "process_mode_requested": requested_mode,
        "process_mode_effective": process_mode_effective,
        "llm_requested": llm_requested,
        "llm_enabled_env": llm_enabled_env,
        "llm_used": bool(llm_enabled and llm_result and llm_result.get("ok")),
        "llm_override": llm_override_effective,
        "llm_status": (llm_result or {}).get("status"),
        "llm_model": (llm_result or {}).get("model"),
        "llm_error": (llm_result or {}).get("error"),
        "llm_run_id": llm_run_id,
        "llm_change_count": len([item for item in llm_changes if item.get("applied")]),
        "llm_change_total": len(llm_changes),
        "llm_dump_path": llm_dump_path,
        "updated_at": updated["updated_at"],
    }


@app.post("/dev/parse-text")
def parse_text(request: ParseTextRequest):
    return parse_document_text(request.text)
