import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import shutil
from threading import Lock
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from db import (
    apply_migrations,
    get_document,
    get_document_image,
    get_document_result,
    get_latest_vendoc_export_job,
    insert_document,
    insert_vendoc_export_job,
    list_documents,
    list_vendoc_export_jobs,
    reset_document_results,
    update_line_item_image_assignments,
    update_line_item_review_state,
    replace_document_images,
    replace_document_amount_lines,
    replace_line_items,
    update_document_approval_state,
    update_document_parse_result,
    update_document_status,
)
from extractor import extract_pdf_images, extract_pdf_text
from exporter import build_export_content
from image_assignment import (
    is_non_visual_line_item,
    is_viable_auto_assignment_image,
    page_candidate_rank,
    rebalance_unique_primary_image_assignments,
)
from image_preview import browser_preview_for_image
from image_matcher import rank_line_item_candidates_with_vlm
from llm import enrich_document_fields_with_ollama, extract_document_full_with_ollama
from parser import parse_document_text, supplier_name_for_template
from structured_parser import extract_amount_lines, extract_line_items
from vendoc_exporter import build_vendoc_payload

app = FastAPI(title="KI PDF Reader PoC API")

UPLOAD_DIR = Path("/data/uploads")
EXPORT_DIR = Path("/data/exports")
TEXT_DUMP_DIR = Path("/data/logs/extracted_text")
IMAGE_DUMP_DIR = Path("/data/logs/extracted_images")
LLM_DUMP_DIR = Path("/data/logs/llm")
UI_DIR = Path(__file__).resolve().parent / "ui"
UI_INDEX_PATH = UI_DIR / "index.html"
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
PROCESS_MODES = ("parser_only", "hybrid_fill", "llm_override", "llm_only")
COMPARE_FIELDS = (
    "supplier_name",
    "document_type",
    "offer_reference",
    "document_number",
    "document_date",
    "project_ref",
    "currency",
    "totals.net_total",
    "totals.vat_total",
    "totals.gross_total",
)

PROCESS_PROGRESS: dict[int, dict[str, Any]] = {}
PROCESS_PROGRESS_LOCK = Lock()


class ParseTextRequest(BaseModel):
    text: str = Field(min_length=1, description="Raw text content extracted from a PDF.")


class AssignImageRequest(BaseModel):
    image_id: int = Field(gt=0, description="Final image id to assign to the line item.")


class DocumentApprovalRequest(BaseModel):
    reviewer_name: str | None = Field(default=None, max_length=160, description="Optional reviewer name.")
    note: str | None = Field(default=None, max_length=1000, description="Optional approval note.")


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
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _set_process_progress(
    document_id: int,
    *,
    stage: str,
    message: str,
    mode: str | None = None,
    step: int | None = None,
    total: int | None = None,
    page_ref: int | None = None,
    status: str = "processing",
    error: str | None = None,
) -> None:
    payload = {
        "document_id": document_id,
        "status": status,
        "mode": mode,
        "stage": stage,
        "message": message,
        "step": step,
        "total": total,
        "page_ref": page_ref,
        "error": error,
        "updated_at": _utc_now_iso(),
    }
    with PROCESS_PROGRESS_LOCK:
        previous = PROCESS_PROGRESS.get(document_id) or {}
        if payload["mode"] is None:
            payload["mode"] = previous.get("mode")
        PROCESS_PROGRESS[document_id] = payload


def _get_process_progress(document_id: int) -> dict[str, Any] | None:
    with PROCESS_PROGRESS_LOCK:
        payload = PROCESS_PROGRESS.get(document_id)
        if not payload:
            return None
        return dict(payload)


def _clear_process_progress(document_id: int) -> None:
    with PROCESS_PROGRESS_LOCK:
        PROCESS_PROGRESS.pop(document_id, None)


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

    for field in ("document_type", "offer_reference", "document_number", "document_date", "project_ref", "currency"):
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

    for field in ("document_type", "offer_reference", "document_number", "document_date", "project_ref", "currency"):
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
        "document_type": _clean_optional_str(parsed.get("document_type")) or "angebot",
        "offer_reference": _clean_optional_str(parsed.get("offer_reference")),
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


def _remove_file(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    path.unlink(missing_ok=True)
    return True


def _remove_dir(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    file_count = sum(1 for item in path.rglob("*") if item.is_file())
    shutil.rmtree(path, ignore_errors=True)
    return file_count


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
    if field == "document_type":
        return text.strip().lower()
    if field == "offer_reference":
        return re.sub(r"\s+", " ", text).strip().casefold()
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


def _image_assignment_source(item: dict[str, Any]) -> str:
    return str(item.get("image_assignment_source") or "").strip().lower()


def _item_for_image_matching(item: dict[str, Any]) -> dict[str, Any]:
    if _image_assignment_source(item) == "manual":
        return item

    # Automatic assignments are recalculated on every match run. Otherwise a
    # previous bad heuristic result can become "final" input for the next run.
    clone = dict(item)
    clone["image_assignment_is_final"] = False
    clone["image_ids"] = []
    clone["image_ids_primary"] = []
    return clone


def _candidate_rank_bonus(candidate_index: int, *, image_assignment_is_final: bool) -> float:
    if image_assignment_is_final:
        return max(0.0, 0.24 - (candidate_index * 0.12))
    return max(0.0, 0.56 - (candidate_index * 0.22))


def _candidate_area_bonus(area: int, *, image_assignment_is_final: bool) -> float:
    if area <= 0:
        return 0.0
    cap = 0.55 if image_assignment_is_final else 0.22
    return min(cap, area / 420_000.0)


def _candidate_images_for_item(
    item: dict[str, Any],
    image_by_id: dict[int, dict[str, Any]],
    *,
    max_candidates: int,
) -> list[dict[str, Any]]:
    if is_non_visual_line_item(item):
        return []

    def _ids_from_item(key: str) -> list[int]:
        raw = item.get(key)
        if not isinstance(raw, list):
            return []
        current_ids: list[int] = []
        for value in raw:
            parsed = _to_int_safe(value)
            if parsed is not None:
                current_ids.append(parsed)
        return _dedupe_int_list(current_ids)

    image_assignment_is_final = bool(item.get("image_assignment_is_final"))
    candidate_ids: list[int] = []
    if image_assignment_is_final:
        for key in ("image_candidate_ids", "image_ids", "image_ids_page_all"):
            current_ids = _ids_from_item(key)
            if current_ids:
                candidate_ids = current_ids
                break
    else:
        primary_ids_for_matching = _dedupe_int_list(
            _ids_from_item("image_candidate_ids") + _ids_from_item("image_ids")
        )
        page_ref_for_matching = _to_int_safe(item.get("page_ref"))
        has_same_page_viable_primary = any(
            (
                _to_int_safe(image_by_id.get(image_id, {}).get("page_ref")) == page_ref_for_matching
                and is_viable_auto_assignment_image(image_by_id.get(image_id, {}))
            )
            for image_id in primary_ids_for_matching
        )
        page_all_ids = _ids_from_item("image_ids_page_all")
        candidate_ids = primary_ids_for_matching
        if not candidate_ids or (page_all_ids and not has_same_page_viable_primary):
            candidate_ids = _dedupe_int_list(candidate_ids + page_all_ids)
    if not candidate_ids:
        return []

    page_ref = _to_int_safe(item.get("page_ref"))
    next_page_allowed = bool(item.get("image_next_page_allowed"))
    prefers_next_page = bool(item.get("image_prefers_next_page"))
    primary_ids_raw = item.get("image_ids_primary")
    primary_ids = set()
    if image_assignment_is_final:
        primary_ids = {
            parsed
            for parsed in (_to_int_safe(val) for val in (primary_ids_raw if isinstance(primary_ids_raw, list) else []))
            if parsed is not None
        }

    same_page_viable_exists = any(
        (
            _to_int_safe(image_by_id.get(image_id, {}).get("page_ref")) == page_ref
            and is_viable_auto_assignment_image(image_by_id.get(image_id, {}))
        )
        for image_id in candidate_ids
    )

    scored: list[tuple[float, dict[str, Any]]] = []
    for candidate_index, image_id in enumerate(candidate_ids):
        image = image_by_id.get(image_id)
        if image is None:
            continue
        image_page = _to_int_safe(image.get("page_ref"))
        if (
            not image_assignment_is_final
            and page_ref is not None
            and image_page is not None
        ):
            same_page = image_page == page_ref
            next_page_carryover = (
                image_page == page_ref + 1
                and next_page_allowed
                and (prefers_next_page or not same_page_viable_exists)
                and is_viable_auto_assignment_image(image)
            )
            if not same_page and not next_page_carryover:
                continue
        width = _to_int_safe(image.get("width")) or 0
        height = _to_int_safe(image.get("height")) or 0
        area = width * height
        decorative_penalty = -0.80 if image.get("is_probably_decorative") else 0.0
        repeated_penalty = -0.25 if image.get("is_repeated_across_pages") else 0.0
        page_bonus = 0.0
        if page_ref is not None and image_page is not None:
            page_diff = image_page - page_ref
            if page_diff == 0:
                page_bonus = 0.80
            elif page_diff == 1:
                page_bonus = 0.28
            if prefers_next_page:
                if page_diff == 1:
                    page_bonus += 0.72
                elif page_diff == 0:
                    page_bonus -= 0.22
        area_bonus = _candidate_area_bonus(area, image_assignment_is_final=image_assignment_is_final)
        primary_bonus = 0.20 if image_id in primary_ids else 0.0
        rank_bonus = _candidate_rank_bonus(candidate_index, image_assignment_is_final=image_assignment_is_final)
        score = page_bonus + area_bonus + primary_bonus + rank_bonus + decorative_penalty + repeated_penalty
        scored.append((score, page_candidate_rank(page_ref, image_page), image))

    scored.sort(key=lambda pair: (-pair[0], pair[1], _to_int_safe(pair[2].get("id")) or 0))
    return [image for _, _, image in scored[:max_candidates]]


def _heuristic_match_for_item(
    item: dict[str, Any],
    candidate_images: list[dict[str, Any]],
    *,
    allow_multiple: bool,
) -> dict[str, Any]:
    if is_non_visual_line_item(item):
        return {
            "selected_image_ids": [],
            "scores": [],
        }
    page_ref = _to_int_safe(item.get("page_ref"))
    next_page_allowed = bool(item.get("image_next_page_allowed"))
    prefers_next_page = bool(item.get("image_prefers_next_page"))
    primary_ids_raw = item.get("image_ids_primary")
    image_assignment_is_final = bool(item.get("image_assignment_is_final"))
    primary_ids = set()
    if image_assignment_is_final:
        primary_ids = {
            parsed
            for parsed in (_to_int_safe(val) for val in (primary_ids_raw if isinstance(primary_ids_raw, list) else []))
            if parsed is not None
        }

    same_page_viable_exists = any(
        (
            _to_int_safe(image.get("page_ref")) == page_ref
            and is_viable_auto_assignment_image(image)
        )
        for image in candidate_images
    )

    score_rows: list[dict[str, Any]] = []
    for candidate_index, image in enumerate(candidate_images):
        image_id = _to_int_safe(image.get("id"))
        if image_id is None:
            continue
        image_page = _to_int_safe(image.get("page_ref"))
        if (
            not image_assignment_is_final
            and page_ref is not None
            and image_page is not None
        ):
            same_page = image_page == page_ref
            next_page_carryover = (
                image_page == page_ref + 1
                and next_page_allowed
                and (prefers_next_page or not same_page_viable_exists)
                and is_viable_auto_assignment_image(image)
            )
            if not same_page and not next_page_carryover:
                continue
        width = _to_int_safe(image.get("width")) or 0
        height = _to_int_safe(image.get("height")) or 0
        area = width * height
        score = 0.0
        if page_ref is not None and image_page is not None:
            page_diff = image_page - page_ref
            if page_diff == 0:
                score += 0.85
            elif page_diff == 1:
                score += 0.30
            if prefers_next_page:
                if page_diff == 1:
                    score += 0.74
                elif page_diff == 0:
                    score -= 0.22
        score += _candidate_area_bonus(area, image_assignment_is_final=image_assignment_is_final)
        score += _candidate_rank_bonus(candidate_index, image_assignment_is_final=image_assignment_is_final)
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
                "reason": "heuristic(page+layout_rank+area+decorative+primary)",
                "_page_rank": page_candidate_rank(page_ref, image_page),
            }
        )

    score_rows.sort(key=lambda row: (-row["score"], row["_page_rank"], row["image_id"]))
    selected_image_ids: list[int] = []
    minimum_assignment_score = 0.25
    auto_match_allowed = item.get("image_auto_match_allowed") is not False
    if auto_match_allowed and score_rows and score_rows[0]["score"] >= minimum_assignment_score:
        selected_image_ids = [score_rows[0]["image_id"]]
        if allow_multiple and len(score_rows) > 1:
            top = score_rows[0]["score"]
            second = score_rows[1]["score"]
            if second >= top - 0.10 and second >= minimum_assignment_score:
                selected_image_ids.append(score_rows[1]["image_id"])
    selected_image_ids = _dedupe_int_list(selected_image_ids)

    for row in score_rows:
        row.pop("_page_rank", None)

    return {
        "selected_image_ids": selected_image_ids,
        "scores": score_rows,
        "auto_match_allowed": auto_match_allowed,
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
        page_end_ref = _to_int_safe(item.get("page_end_ref"))
        if page_end_ref is not None:
            metadata["page_end_ref"] = page_end_ref
            metadata["spans_page_break"] = bool(item.get("spans_page_break"))
        if "image_required" in item:
            metadata["image_required"] = bool(item.get("image_required"))
        referenced_lv_pos = _clean_optional_str(item.get("referenced_lv_pos"))
        if referenced_lv_pos:
            metadata["referenced_lv_pos"] = referenced_lv_pos
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


def _build_amount_line_rows_from_llm(
    llm_amount_lines: list[dict[str, Any]],
    totals: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in llm_amount_lines:
        if not isinstance(item, dict):
            continue
        amount = _parse_eu_decimal(item.get("amount_raw"))
        if amount is None:
            continue
        sort_order = _to_int_safe(item.get("sort_order"))
        rows.append(
            {
                "line_type": _clean_optional_str(item.get("line_type")) or "other",
                "label_raw": _clean_optional_str(item.get("label_raw")) or "LLM amount line",
                "percent": _parse_eu_decimal(item.get("percent_raw")),
                "base_amount": _parse_eu_decimal(item.get("base_amount_raw")),
                "amount": amount,
                "sort_order": sort_order if sort_order is not None else len(rows),
            }
        )

    def _upsert_total_line(line_type: str, amount_raw: Any, fallback_label: str, percent: Decimal | None = None) -> None:
        raw_text = amount_raw if isinstance(amount_raw, str) else _clean_optional_str(amount_raw)
        amount = _parse_eu_decimal(raw_text)
        if amount is None:
            return
        for row in rows:
            if row.get("line_type") == line_type:
                row["amount"] = amount
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

    totals_obj = totals if isinstance(totals, dict) else {}
    _upsert_total_line("net_total", totals_obj.get("net_total"), "Nettosumme")
    _upsert_total_line("vat", totals_obj.get("vat_total"), "Mehrwertsteuer", Decimal("20.00"))
    _upsert_total_line("total", totals_obj.get("gross_total"), "Angebotssumme")

    rows = sorted(rows, key=lambda row: (row.get("sort_order", 0), row.get("line_type", "")))
    for idx, row in enumerate(rows):
        row["sort_order"] = idx
    return rows


def _build_line_item_rows_from_llm(llm_line_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in llm_line_items:
        if not isinstance(item, dict):
            continue
        quantity = _parse_eu_decimal(item.get("quantity_raw"))
        width_mm = _parse_eu_decimal(item.get("width_raw"))
        height_mm = _parse_eu_decimal(item.get("height_raw"))
        unit_price = _parse_eu_decimal(item.get("unit_price_raw"))
        line_total = _parse_eu_decimal(item.get("line_total_raw"))
        page_ref = _to_int_safe(item.get("page_ref"))
        if page_ref is not None and page_ref <= 0:
            page_ref = None

        llm_confidence = _to_float_safe(item.get("confidence"))
        if llm_confidence is None:
            confidence = Decimal("0.72") if line_total is None else Decimal("0.82")
        else:
            llm_confidence = max(0.0, min(1.0, llm_confidence))
            confidence = Decimal(f"{llm_confidence:.4f}")

        metadata = {
            "source": "llm",
            "quantity_raw": item.get("quantity_raw"),
            "width_raw": item.get("width_raw"),
            "height_raw": item.get("height_raw"),
            "unit_price_raw": item.get("unit_price_raw"),
            "line_total_raw": item.get("line_total_raw"),
            "llm_confidence_raw": item.get("confidence"),
        }
        rows.append(
            {
                "position_no": _clean_optional_str(item.get("position_no")),
                "lv_pos": _clean_optional_str(item.get("lv_pos")),
                "is_alternative": bool(item.get("is_alternative", False)),
                "quantity": quantity,
                "unit": _clean_optional_str(item.get("unit")),
                "width_mm": width_mm,
                "height_mm": height_mm,
                "description_short": _clean_optional_str(item.get("description_short")),
                "description_long": _clean_optional_str(item.get("description_long")),
                "unit_price": unit_price,
                "line_total": line_total,
                "page_ref": page_ref,
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


def _vendoc_target_server() -> str | None:
    return _clean_optional_str(os.getenv("VENDOC_MSSQL_HOST"))


def _vendoc_target_database() -> str:
    return _clean_optional_str(os.getenv("VENDOC_MSSQL_DATABASE")) or "SRTemp"


def _vendoc_error_text(errors: list[dict[str, Any]] | None, fallback: str | None = None) -> str | None:
    if not errors:
        return fallback
    messages: list[str] = []
    for issue in errors[:8]:
        if not isinstance(issue, dict):
            continue
        code = _clean_optional_str(issue.get("code")) or "vendoc_error"
        message = _clean_optional_str(issue.get("message")) or code
        messages.append(f"{code}: {message}")
    if len(errors) > len(messages):
        messages.append(f"... {len(errors) - len(messages)} weitere Fehler")
    return "; ".join(messages) or fallback


def _vendoc_job_response(row: dict[str, Any], *, include_payload: bool = False) -> dict[str, Any]:
    payload = dict(row)
    if not include_payload:
        payload.pop("payload_json", None)
    return _json_safe(payload)


def _record_vendoc_export_job(
    *,
    document_id: int,
    result_data: dict[str, Any],
    vendoc_payload: dict[str, Any],
    dry_run: bool,
    status: str,
    error_text: str | None = None,
) -> dict[str, Any]:
    document = result_data.get("document") if isinstance(result_data.get("document"), dict) else {}
    summary = vendoc_payload.get("summary") if isinstance(vendoc_payload.get("summary"), dict) else {}
    return insert_vendoc_export_job(
        document_id=document_id,
        external_document_id=str(vendoc_payload.get("external_document_id")),
        dry_run=dry_run,
        status=status,
        target_server=_vendoc_target_server(),
        target_database=_vendoc_target_database(),
        line_item_count=int(summary.get("position_count") or 0),
        warning_count=int(summary.get("warning_count") or 0),
        error_count=int(summary.get("error_count") or 0),
        error_text=error_text,
        approval_status=_clean_optional_str(document.get("approval_status")),
        reviewed_by=_clean_optional_str(document.get("reviewed_by")),
        reviewed_at=document.get("reviewed_at"),
        payload=vendoc_payload,
    )


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
    preview_path, media_type, transcoded = browser_preview_for_image(
        image_path,
        mime_type=image.get("mime_type"),
        cache_key=str(image.get("sha256") or f"document_{document_id}_image_{image_id}"),
    )
    output_path = preview_path if preview_path.exists() else image_path
    filename = output_path.name
    headers = {
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": "no-store",
        "X-Original-Mime-Type": str(image.get("mime_type") or ""),
        "X-Preview-Transcoded": "1" if transcoded else "0",
    }
    return FileResponse(output_path, media_type=media_type, headers=headers)


@app.post("/documents/{document_id}/line-items/{line_item_id}/assign-image")
def assign_line_item_image(document_id: int, line_item_id: int, payload: AssignImageRequest):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Result for document {document_id} not found.")

    line_items_raw = result_data.get("line_items")
    images_raw = result_data.get("images")
    line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []
    images = list(images_raw) if isinstance(images_raw, list) else []

    line_item = next((item for item in line_items if _to_int_safe(item.get("id")) == line_item_id), None)
    if not line_item:
        raise HTTPException(status_code=404, detail=f"Line item {line_item_id} for document {document_id} not found.")

    image = next((item for item in images if _to_int_safe(item.get("id")) == payload.image_id), None)
    if not image:
        raise HTTPException(status_code=404, detail=f"Image {payload.image_id} for document {document_id} not found.")

    updated = update_line_item_image_assignments(
        document_id,
        {
            line_item_id: {
                "image_ids": [payload.image_id],
                "selection_source": "manual",
                "selection_reason": "ui_manual_assignment",
                "strategy_requested": "manual",
                "review_checked": True,
                "review_checked_reason": "ui_manual_assignment",
            }
        },
    )
    if updated <= 0:
        raise HTTPException(status_code=500, detail="Image assignment could not be persisted.")

    return {
        "ok": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "image_id": payload.image_id,
        "selection_source": "manual",
        "selection_reason": "ui_manual_assignment",
        "review_checked": True,
    }


@app.delete("/documents/{document_id}/line-items/{line_item_id}/assign-image")
def clear_line_item_image_assignment(document_id: int, line_item_id: int):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Result for document {document_id} not found.")

    line_items_raw = result_data.get("line_items")
    line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []
    line_item = next((item for item in line_items if _to_int_safe(item.get("id")) == line_item_id), None)
    if not line_item:
        raise HTTPException(status_code=404, detail=f"Line item {line_item_id} for document {document_id} not found.")

    updated = update_line_item_image_assignments(
        document_id,
        {
            line_item_id: {
                "image_ids": [],
                "selection_source": "manual",
                "selection_reason": "ui_manual_clear",
                "strategy_requested": "manual",
                "clear_assignment": True,
                "review_checked": True,
                "review_checked_reason": "ui_manual_clear",
            }
        },
    )
    if updated <= 0:
        raise HTTPException(status_code=500, detail="Image assignment could not be cleared.")

    return {
        "ok": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "image_id": None,
        "selection_source": "manual",
        "selection_reason": "ui_manual_clear",
        "review_checked": True,
    }


@app.post("/documents/{document_id}/line-items/{line_item_id}/review-check")
def check_line_item_review(document_id: int, line_item_id: int):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Result for document {document_id} not found.")

    line_items_raw = result_data.get("line_items")
    line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []
    line_item = next((item for item in line_items if _to_int_safe(item.get("id")) == line_item_id), None)
    if not line_item:
        raise HTTPException(status_code=404, detail=f"Line item {line_item_id} for document {document_id} not found.")

    updated = update_line_item_review_state(
        document_id,
        line_item_id,
        checked=True,
        reason="ui_manual_review",
    )
    if updated <= 0:
        raise HTTPException(status_code=500, detail="Review state could not be persisted.")

    return {
        "ok": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "review_checked": True,
        "review_checked_reason": "ui_manual_review",
    }


@app.delete("/documents/{document_id}/line-items/{line_item_id}/review-check")
def clear_line_item_review(document_id: int, line_item_id: int):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Result for document {document_id} not found.")

    line_items_raw = result_data.get("line_items")
    line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []
    line_item = next((item for item in line_items if _to_int_safe(item.get("id")) == line_item_id), None)
    if not line_item:
        raise HTTPException(status_code=404, detail=f"Line item {line_item_id} for document {document_id} not found.")

    updated = update_line_item_review_state(
        document_id,
        line_item_id,
        checked=False,
        reason="ui_review_reset",
    )
    if updated <= 0:
        raise HTTPException(status_code=500, detail="Review state could not be cleared.")

    return {
        "ok": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "review_checked": False,
        "review_checked_reason": "ui_review_reset",
    }


@app.post("/documents/{document_id}/approval")
def approve_document(document_id: int, payload: DocumentApprovalRequest):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Result for document {document_id} not found.")

    document = result_data.get("document") if isinstance(result_data.get("document"), dict) else {}
    validation = result_data.get("validation") if isinstance(result_data.get("validation"), dict) else {}
    validation_status = str(validation.get("status") or "").strip().lower()

    if str(document.get("status") or "").strip().lower() != "processed":
        raise HTTPException(
            status_code=409,
            detail="Dokument kann erst nach abgeschlossener Verarbeitung freigegeben werden.",
        )
    if validation_status not in {"auto_accept", "manual_checked"}:
        raise HTTPException(
            status_code=409,
            detail=f"Dokument ist aktuell nicht freigabefähig (Status: {validation_status or 'unknown'}).",
        )

    updated = update_document_approval_state(
        document_id,
        approval_status="approved",
        reviewed_by=_clean_optional_str(payload.reviewer_name),
        approval_note=_clean_optional_str(payload.note),
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    return {
        "ok": True,
        "document_id": document_id,
        "approval_status": updated["approval_status"],
        "reviewed_by": updated.get("reviewed_by"),
        "reviewed_at": updated.get("reviewed_at"),
        "approval_note": updated.get("approval_note"),
    }


@app.delete("/documents/{document_id}/approval")
def reset_document_approval(document_id: int):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    updated = update_document_approval_state(document_id, approval_status="pending")
    if not updated:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    return {
        "ok": True,
        "document_id": document_id,
        "approval_status": updated["approval_status"],
        "reviewed_by": updated.get("reviewed_by"),
        "reviewed_at": updated.get("reviewed_at"),
        "approval_note": updated.get("approval_note"),
    }


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


@app.post("/reset/{document_id}")
def reset_document(document_id: int, delete_logs: bool = Query(default=True)):
    reset_info = reset_document_results(document_id)
    if not reset_info:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    _clear_process_progress(document_id)

    removed_files = 0
    if delete_logs:
        raw_text_path = reset_info.get("previous_raw_text_path")
        if raw_text_path:
            try:
                removed_files += int(_remove_file(Path(raw_text_path)))
            except Exception:
                pass

        removed_files += int(_remove_file(TEXT_DUMP_DIR / f"document_{document_id}.txt"))
        removed_files += _remove_dir(IMAGE_DUMP_DIR / f"document_{document_id}")

        for path in _list_llm_dump_files(document_id):
            removed_files += int(_remove_file(path))
        removed_files += int(_remove_file(_llm_latest_file_path(document_id)))

    return {
        "document_id": reset_info["id"],
        "status": reset_info["status"],
        "deleted_amount_lines": reset_info["deleted_amount_lines"],
        "deleted_line_items": reset_info["deleted_line_items"],
        "deleted_images": reset_info["deleted_images"],
        "deleted_log_files": removed_files,
        "delete_logs": delete_logs,
        "updated_at": reset_info["updated_at"],
    }


@app.get("/result/{document_id}")
def result(document_id: int):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    return _json_safe(result_data)


@app.get("/progress/{document_id}")
def process_progress(document_id: int):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    progress = _get_process_progress(document_id)
    if not progress:
        status_text = str(document.get("status") or "unknown")
        default_message = {
            "uploaded": "Bereit zum Start.",
            "processing": "Verarbeitung laeuft.",
            "processed": "Verarbeitung abgeschlossen.",
            "failed": "Verarbeitung fehlgeschlagen.",
        }.get(status_text, f"Status: {status_text}")
        progress = {
            "document_id": document_id,
            "status": status_text,
            "mode": None,
            "stage": status_text,
            "message": default_message,
            "step": None,
            "total": None,
            "page_ref": None,
            "error": document.get("error_message"),
            "updated_at": _utc_now_iso(),
        }
    return _json_safe({"document_id": document_id, "progress": progress})


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
        parser_supplier = supplier_name_for_template(template)
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
                    "document_type": parser_snapshot.get("document_type"),
                    "offer_reference": parser_snapshot.get("offer_reference"),
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
            "document_type": _clean_optional_str(llm_fields.get("document_type")),
            "offer_reference": _clean_optional_str(llm_fields.get("offer_reference")),
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
        matching_item = _item_for_image_matching(item)
        candidates = _candidate_images_for_item(matching_item, image_by_id, max_candidates=max_candidates)
        heuristic = _heuristic_match_for_item(matching_item, candidates, allow_multiple=allow_multiple)
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
        if not final_selected:
            final_source = "unmatched"
            if matching_item.get("image_auto_match_allowed") is False and candidates:
                final_reason = str(matching_item.get("image_assignment_reason") or "no_unique_image_slot")
            else:
                final_reason = "no_confident_candidate" if candidates else "no_candidate_images"

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
                "image_auto_match_allowed": matching_item.get("image_auto_match_allowed") is not False,
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

    items_out = rebalance_unique_primary_image_assignments(items_out, minimum_score=0.25)

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


def _persist_image_assignments(
    document_id: int,
    *,
    strategy: Literal["heuristic", "vlm", "hybrid"],
    allow_multiple: bool = False,
) -> dict[str, Any]:
    try:
        payload = match_images(
            document_id=document_id,
            strategy=strategy,
            max_candidates=6,
            max_items=250,
            allow_multiple=allow_multiple,
            vlm_min_confidence=0.40,
        )
    except HTTPException as exc:
        return {"status": "skipped", "reason": f"match_images_http_{exc.status_code}", "updated_line_items": 0}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:180], "updated_line_items": 0}

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return {"status": "skipped", "reason": "match_items_missing", "updated_line_items": 0}

    assignments: dict[int, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        line_item_id = _to_int_safe(item.get("line_item_id"))
        selected_raw = item.get("selected_image_ids")
        if line_item_id is None or not isinstance(selected_raw, list):
            continue
        selected_ids: list[int] = []
        for value in selected_raw:
            parsed = _to_int_safe(value)
            if parsed is not None:
                selected_ids.append(parsed)
        selected_ids = _dedupe_int_list(selected_ids)
        assignments[line_item_id] = {
            "image_ids": selected_ids,
            "selection_source": item.get("selection_source"),
            "selection_reason": item.get("selection_reason"),
            "strategy_requested": strategy,
            "clear_assignment": not bool(selected_ids),
        }

    updated_count = update_line_item_image_assignments(document_id, assignments)
    return {
        "status": "ok",
        "strategy": strategy,
        "allow_multiple": allow_multiple,
        "updated_line_items": updated_count,
        "assigned_line_items": len(assignments),
        "matched_items": (payload.get("summary") or {}).get("matched_items"),
        "vlm_selected_items": (payload.get("summary") or {}).get("vlm_selected_items"),
        "heuristic_selected_items": (payload.get("summary") or {}).get("heuristic_selected_items"),
    }


@app.get("/vendoc/health")
def vendoc_health():
    enabled = _is_truthy(os.getenv("VENDOC_MSSQL_ENABLED"), default=False)
    host = _vendoc_target_server()
    database = _vendoc_target_database()
    return {
        "ok": bool(enabled and host),
        "status": "configured" if enabled and host else ("disabled" if not enabled else "missing_host"),
        "target_server_configured": bool(host),
        "target_database": database,
        "live_write_available": False,
        "message": "MSSQL live write is blocked until CIBEX access and final VenDoc field rules are available.",
    }


@app.post("/vendoc/export/{document_id}")
def vendoc_export_document(
    document_id: int,
    dry_run: bool = Query(default=True),
):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    try:
        vendoc_payload = build_vendoc_payload(result_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    errors = list(vendoc_payload.get("errors") or [])
    if dry_run:
        status = "dry_run_ok" if not errors else "failed"
        error_text = _vendoc_error_text(errors)
        job = _record_vendoc_export_job(
            document_id=document_id,
            result_data=result_data,
            vendoc_payload=vendoc_payload,
            dry_run=True,
            status=status,
            error_text=error_text,
        )
        return _json_safe(
            {
                "ok": not errors,
                "document_id": document_id,
                "dry_run": True,
                "status": status,
                "job": _vendoc_job_response(job),
                "vendoc": vendoc_payload,
            }
        )

    document = result_data.get("document") if isinstance(result_data.get("document"), dict) else {}
    live_errors = list(errors)
    if str(document.get("status") or "").strip().lower() != "processed":
        live_errors.append(
            {
                "code": "document_not_processed",
                "scope": "document",
                "message": "Live-Export ist erst nach abgeschlossener Verarbeitung erlaubt.",
            }
        )
    if str(document.get("approval_status") or "").strip().lower() != "approved":
        live_errors.append(
            {
                "code": "document_not_approved",
                "scope": "document",
                "message": "Live-Export ist nur fuer freigegebene Dokumente erlaubt.",
            }
        )

    if live_errors:
        vendoc_payload["errors"] = live_errors
        if isinstance(vendoc_payload.get("summary"), dict):
            vendoc_payload["summary"]["error_count"] = len(live_errors)
        error_text = _vendoc_error_text(live_errors)
        job = _record_vendoc_export_job(
            document_id=document_id,
            result_data=result_data,
            vendoc_payload=vendoc_payload,
            dry_run=False,
            status="failed",
            error_text=error_text,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "VenDoc Live-Export ist gesperrt.",
                "errors": live_errors,
                "job": _vendoc_job_response(job),
            },
        )

    if not _is_truthy(os.getenv("VENDOC_MSSQL_ENABLED"), default=False):
        live_error = {
            "code": "mssql_disabled",
            "scope": "vendoc",
            "message": "VENDOC_MSSQL_ENABLED ist nicht aktiv; Live-Write wurde nicht ausgefuehrt.",
        }
        vendoc_payload["errors"] = [live_error]
        if isinstance(vendoc_payload.get("summary"), dict):
            vendoc_payload["summary"]["error_count"] = 1
        job = _record_vendoc_export_job(
            document_id=document_id,
            result_data=result_data,
            vendoc_payload=vendoc_payload,
            dry_run=False,
            status="failed",
            error_text=live_error["message"],
        )
        raise HTTPException(
            status_code=503,
            detail={
                "message": live_error["message"],
                "job": _vendoc_job_response(job),
            },
        )

    live_error = {
        "code": "mssql_writer_not_implemented",
        "scope": "vendoc",
        "message": "Der transaktionale MSSQL-Live-Writer ist noch nicht implementiert.",
    }
    vendoc_payload["errors"] = [live_error]
    if isinstance(vendoc_payload.get("summary"), dict):
        vendoc_payload["summary"]["error_count"] = 1
    job = _record_vendoc_export_job(
        document_id=document_id,
        result_data=result_data,
        vendoc_payload=vendoc_payload,
        dry_run=False,
        status="failed",
        error_text=live_error["message"],
    )
    raise HTTPException(
        status_code=501,
        detail={
            "message": live_error["message"],
            "job": _vendoc_job_response(job),
        },
    )


@app.get("/vendoc/export-jobs/{document_id}")
def vendoc_export_jobs(
    document_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    include_payload: bool = Query(default=False),
):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    jobs = list_vendoc_export_jobs(document_id, limit=limit)
    return {
        "document_id": document_id,
        "items": [_vendoc_job_response(job, include_payload=include_payload) for job in jobs],
        "count": len(jobs),
        "limit": limit,
    }


@app.get("/vendoc/export-jobs/{document_id}/latest")
def vendoc_latest_export_job(
    document_id: int,
    include_payload: bool = Query(default=False),
):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    job = get_latest_vendoc_export_job(document_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"No VenDoc export job found for document {document_id}.")
    return {
        "document_id": document_id,
        "job": _vendoc_job_response(job, include_payload=include_payload),
    }


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
    update_document_approval_state(document_id, approval_status="pending")

    requested_mode = _resolve_process_mode(process_mode=process_mode, use_llm=use_llm, llm_override=llm_override)
    _set_process_progress(
        document_id,
        stage="start",
        message=f"Verarbeitung gestartet (Mode: {requested_mode}).",
        mode=requested_mode,
        status="processing",
    )
    llm_requested = requested_mode != "parser_only"
    llm_enabled_env = _is_truthy(os.getenv("LLM_ENABLED"), default=True)
    llm_enabled = llm_requested and llm_enabled_env
    llm_override_effective = requested_mode == "llm_override"
    vlm_enabled_env = _is_truthy(os.getenv("VLM_ENABLED"), default=False)
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
    image_assignment_summary: dict[str, Any] | None = None

    try:
        _set_process_progress(
            document_id,
            stage="extract_text",
            message="PDF-Text wird extrahiert.",
            mode=requested_mode,
            status="processing",
        )
        extracted_text = extract_pdf_text(source_path)
        text_dump_path = TEXT_DUMP_DIR / f"document_{document_id}.txt"
        text_dump_path.write_text(extracted_text, encoding="utf-8")
        _set_process_progress(
            document_id,
            stage="extract_images",
            message="PDF-Bilder werden extrahiert.",
            mode=requested_mode,
            status="processing",
        )
        image_rows = extract_pdf_images(source_path, IMAGE_DUMP_DIR / f"document_{document_id}")

        parsed_base: dict[str, Any]
        parsed: dict[str, Any]
        if requested_mode == "llm_only":
            timeout_raw = os.getenv("LLM_ONLY_TIMEOUT_SECONDS", os.getenv("LLM_TIMEOUT_SECONDS", "300")).strip()
        else:
            timeout_raw = os.getenv("LLM_TIMEOUT_SECONDS", "120").strip()
        try:
            timeout_seconds = max(5.0, float(timeout_raw))
        except ValueError:
            timeout_seconds = 300.0 if requested_mode == "llm_only" else 120.0

        if requested_mode == "llm_only":
            parsed_base = {
                "template": "llm_only",
                "document_type": None,
                "offer_reference": None,
                "document_number": None,
                "document_date": None,
                "project_ref": None,
                "currency": None,
                "supplier_name": None,
                "totals": {"net_total": None, "vat_total": None, "gross_total": None},
                "position_count": 0,
            }
            if not llm_enabled_env:
                llm_result = {
                    "ok": False,
                    "status": "disabled_env",
                    "model": llm_model,
                    "error": "LLM disabled via LLM_ENABLED=false.",
                    "raw_text": None,
                    "fields": {},
                    "amount_lines": [],
                    "line_items": [],
                }
            else:
                def _llm_progress(event: dict[str, Any]) -> None:
                    stage = _clean_optional_str(event.get("stage")) or "llm_only"
                    message = _clean_optional_str(event.get("message")) or "LLM-only Verarbeitung laeuft."
                    _set_process_progress(
                        document_id,
                        stage=stage,
                        message=message,
                        mode=requested_mode,
                        step=_to_int_safe(event.get("step")),
                        total=_to_int_safe(event.get("total")),
                        page_ref=_to_int_safe(event.get("page_ref")),
                        status="processing",
                    )

                llm_result = extract_document_full_with_ollama(
                    extracted_text=extracted_text,
                    timeout_seconds=timeout_seconds,
                    progress_callback=_llm_progress,
                )

            if not (llm_result and llm_result.get("ok")):
                status = (llm_result or {}).get("status") or "error"
                error_text = (llm_result or {}).get("error") or "unknown"
                raise RuntimeError(f"LLM-only extraction failed ({status}): {error_text}")

            llm_fields = llm_result.get("fields")
            llm_fields = llm_fields if isinstance(llm_fields, dict) else {}
            parsed, llm_changes = _build_llm_only_fields(parsed_base, llm_fields)
            parsed["template"] = "llm_only"
            template = "llm_only"
            amount_line_rows = _build_amount_line_rows_from_llm(
                llm_result.get("amount_lines") if isinstance(llm_result.get("amount_lines"), list) else [],
                parsed.get("totals") if isinstance(parsed.get("totals"), dict) else {},
            )
            line_item_rows = _build_line_item_rows_from_llm(
                llm_result.get("line_items") if isinstance(llm_result.get("line_items"), list) else []
            )
            process_mode_effective = "llm_only"
        else:
            _set_process_progress(
                document_id,
                stage="parse_text",
                message="Parser extrahiert Felder, Positionen und Betragszeilen.",
                mode=requested_mode,
                status="processing",
            )
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
                _set_process_progress(
                    document_id,
                    stage="llm_enrich",
                    message="LLM reichert Parser-Ergebnis an.",
                    mode=requested_mode,
                    status="processing",
                )
                llm_result = enrich_document_fields_with_ollama(
                    extracted_text=extracted_text,
                    parser_snapshot={
                        "template": parsed_base.get("template"),
                        "document_type": parsed_base.get("document_type"),
                        "offer_reference": parsed_base.get("offer_reference"),
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
                if requested_mode == "llm_override":
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

            amount_line_rows = _build_amount_line_rows(
                extracted_text,
                parsed.get("totals") if isinstance(parsed.get("totals"), dict) else {},
            )
            line_item_rows = _build_line_item_rows(extracted_text, template)

        _set_process_progress(
            document_id,
            stage="persist_rows",
            message="Extraktion wird in die Datenbank geschrieben.",
            mode=requested_mode,
            status="processing",
        )
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
        supplier_name = supplier_name_for_template(template)
        llm_supplier = _clean_optional_str((llm_result or {}).get("fields", {}).get("supplier_name"))
        if requested_mode == "llm_only":
            supplier_name = llm_supplier
        elif llm_supplier and (supplier_name is None or llm_override_effective):
            supplier_name = llm_supplier
        replace_document_amount_lines(document_id, amount_line_rows)
        replace_line_items(document_id, line_item_rows)
        replace_document_images(document_id, image_rows)
        if line_item_rows and image_rows:
            image_match_strategy: Literal["heuristic", "vlm", "hybrid"] = "heuristic"
            if requested_mode != "parser_only" and vlm_enabled_env:
                image_match_strategy = "hybrid"
            _set_process_progress(
                document_id,
                stage="image_match",
                message="Bildzuordnung pro Position wird berechnet.",
                mode=requested_mode,
                status="processing",
            )
            image_assignment_summary = _persist_image_assignments(
                document_id,
                strategy=image_match_strategy,
                allow_multiple=False,
            )

        position_count = len(line_item_rows) if line_item_rows else int(parsed.get("position_count", 0) or 0)
        confidence = _compute_confidence(
            template=template,
            position_count=position_count,
            has_totals=any(v is not None for v in (net_total, vat_total, gross_total)),
        )

        updated = update_document_parse_result(
            document_id,
            supplier_name=supplier_name,
            document_type=parsed.get("document_type"),
            offer_reference=parsed.get("offer_reference"),
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
        _set_process_progress(
            document_id,
            stage="completed",
            message="Verarbeitung abgeschlossen.",
            mode=requested_mode,
            status="processed",
        )
    except HTTPException:
        _set_process_progress(
            document_id,
            stage="failed",
            message="Verarbeitung mit HTTP-Fehler beendet.",
            mode=requested_mode,
            status="failed",
        )
        raise
    except Exception as exc:
        update_document_status(document_id, status="failed", error_message=str(exc)[:1000])
        _set_process_progress(
            document_id,
            stage="failed",
            message="Verarbeitung fehlgeschlagen.",
            mode=requested_mode,
            status="failed",
            error=str(exc)[:1000],
        )
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc

    return {
        "document_id": updated["id"],
        "status": updated["status"],
        "template": template,
        "parser_used": requested_mode != "llm_only",
        "position_count": position_count,
        "line_item_count": len(line_item_rows),
        "amount_line_count": len(amount_line_rows),
        "image_count": len(image_rows),
        "supplier_name": updated["supplier_name"],
        "document_type": updated["document_type"],
        "offer_reference": updated["offer_reference"],
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
        "llm_line_item_count": len((llm_result or {}).get("line_items") or []) if requested_mode == "llm_only" else None,
        "llm_amount_line_count": len((llm_result or {}).get("amount_lines") or []) if requested_mode == "llm_only" else None,
        "image_assignment": image_assignment_summary,
        "llm_image_assignment": image_assignment_summary,
        "llm_dump_path": llm_dump_path,
        "updated_at": updated["updated_at"],
    }


@app.post("/dev/parse-text")
def parse_text(request: ParseTextRequest):
    return parse_document_text(request.text)
