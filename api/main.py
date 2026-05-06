import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from threading import Lock
from typing import Any, Literal
from uuid import UUID, uuid4

import fitz
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
    insert_document_image,
    insert_vendoc_export_job,
    list_documents,
    list_vendoc_export_jobs,
    get_document_relations,
    refresh_document_links,
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
from document_package import build_document_package_result
from exporter import build_export_content
from image_assignment import (
    image_aspect_difference,
    image_within_item_vertical_window,
    item_dimension_ratio,
    is_non_visual_line_item,
    is_viable_auto_assignment_image,
    is_viable_auto_assignment_image_for_item,
    page_candidate_rank,
    rebalance_unique_primary_image_assignments,
)
from image_preview import browser_preview_for_image
from parser import parse_document_text, supplier_name_for_template
from structured_parser import extract_amount_lines, extract_line_items
from template_alu_one import extract_line_item_layout_hints as extract_alu_one_line_item_layout_hints
from template_koch_detail import parse_page_details as parse_koch_detail_page_details
from vendoc_exporter import build_vendoc_payload
from vendoc_mssql import build_srtemp_export_preview, check_connection, config_from_env, driver_status, write_srtemp_payload

app = FastAPI(title="PDF Reader PoC API")

UPLOAD_DIR = Path("/data/uploads")
EXPORT_DIR = Path("/data/exports")
TEXT_DUMP_DIR = Path("/data/logs/extracted_text")
IMAGE_DUMP_DIR = Path("/data/logs/extracted_images")
UI_DIR = Path(__file__).resolve().parent / "ui"
UI_INDEX_PATH = UI_DIR / "index.html"
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
PROCESS_MODES = ("parser_only",)
AI_DISABLED_DETAIL = (
    "KI-/Modellverarbeitung ist im Produktbetrieb deaktiviert. "
    "Erlaubt ist nur die lokale Parser-Verarbeitung."
)

PROCESS_PROGRESS: dict[int, dict[str, Any]] = {}
PROCESS_PROGRESS_LOCK = Lock()


class ParseTextRequest(BaseModel):
    text: str = Field(min_length=1, description="Raw text content extracted from a PDF.")


class AssignImageRequest(BaseModel):
    image_id: int = Field(gt=0, description="Final image id to assign to the line item.")


class DocumentPackageRequest(BaseModel):
    document_ids: list[int] = Field(min_length=1, description="Documents that belong to one logical PDF package.")
    main_document_id: int | None = Field(default=None, description="Optional explicit master document id.")


class PdfCropImageRequest(BaseModel):
    page_ref: int = Field(ge=1, description="PDF page number to crop from.")
    left_ratio: float = Field(ge=0, le=1, description="Selection left edge relative to rendered page width.")
    top_ratio: float = Field(ge=0, le=1, description="Selection top edge relative to rendered page height.")
    width_ratio: float = Field(gt=0, le=1, description="Selection width relative to rendered page width.")
    height_ratio: float = Field(gt=0, le=1, description="Selection height relative to rendered page height.")


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


def _postprocess_image_rows(
    image_rows: list[dict[str, Any]],
    *,
    template: str,
    document_type: str | None,
    extracted_text: str,
) -> list[dict[str, Any]]:
    def _image_signature(row: dict[str, Any]) -> tuple[Any, ...]:
        metadata = row.get("metadata_json") or {}
        return (
            metadata.get("layout_source"),
            int(row.get("width") or 0),
            int(row.get("height") or 0),
            int(row.get("bytes_size") or 0),
            round(float(metadata.get("top_ratio") or 0), 6),
            round(float(metadata.get("left_ratio") or 0), 6),
            round(float(metadata.get("width_ratio") or 0), 6),
            round(float(metadata.get("height_ratio") or 0), 6),
        )

    def _is_alu_one_header_logo(row: dict[str, Any]) -> bool:
        metadata = row.get("metadata_json") or {}
        return (
            metadata.get("layout_source") == "fitz_image_block"
            and int(row.get("width") or 0) == 230
            and int(row.get("height") or 0) == 109
            and int(row.get("bytes_size") or 0) == 9632
            and float(metadata.get("top_ratio") or 0) <= 0.08
            and float(metadata.get("left_ratio") or 0) <= 0.10
            and float(metadata.get("width_ratio") or 0) >= 0.25
            and float(metadata.get("height_ratio") or 0) <= 0.11
        )

    if template == "alu_one" and str(document_type or "").lower() in {"angebot", "auftragsbestaetigung"}:
        return [
            row
            for row in image_rows
            if not _is_alu_one_header_logo(row)
        ]

    if template == "koch" and str(document_type or "").lower() in {"angebot", "auftragsbestaetigung"}:
        return [
            row
            for row in image_rows
            if (row.get("metadata_json") or {}).get("layout_source")
            not in {"vector_strip_band", "vector_position_line_art"}
        ]

    if template != "koch_detail":
        return image_rows

    page_details = parse_koch_detail_page_details(extracted_text)
    processed: list[dict[str, Any]] = []
    for row in image_rows:
        width = int(row.get("width") or 0)
        height = int(row.get("height") or 0)
        if width <= 0 or height <= 0:
            continue
        # Koch technical PDFs include repeated header logos and small profile fragments.
        # Keep the large drawings that can be assigned to positions.
        if width >= 500 and height <= 220:
            continue
        if max(width, height) < 700:
            continue
        metadata = dict(row.get("metadata_json") or {})
        metadata.update(page_details.get(int(row.get("page_ref") or 0), {}))
        metadata["source_template"] = "koch_detail"
        metadata["koch_detail_candidate"] = True
        row = {**row, "metadata_json": metadata}
        processed.append(row)
    return processed


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


def _resolve_process_mode(
    *,
    process_mode: str | None,
    use_ai: bool,
    ai_override: bool,
) -> Literal["parser_only"]:
    normalized = (process_mode or "parser_only").strip().lower()
    if normalized not in PROCESS_MODES or use_ai or ai_override:
        raise HTTPException(status_code=400, detail=f"{AI_DISABLED_DETAIL} Verwende process_mode=parser_only.")
    return "parser_only"


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


def _clamp_ratio(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _render_pdf_page_png(source_path: Path, page_ref: int, *, scale: float = 2.0) -> tuple[bytes, int, int]:
    try:
        with fitz.open(str(source_path)) as document:
            if page_ref < 1 or page_ref > document.page_count:
                raise HTTPException(status_code=404, detail=f"PDF page {page_ref} not found.")
            page = document.load_page(page_ref - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            return pixmap.tobytes("png"), int(pixmap.width), int(pixmap.height)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF page preview could not be rendered: {exc}") from exc


def _crop_pdf_region_to_png(
    source_path: Path,
    payload: PdfCropImageRequest,
    *,
    scale: float = 3.0,
) -> tuple[bytes, int, int, dict[str, Any]]:
    try:
        with fitz.open(str(source_path)) as document:
            if payload.page_ref < 1 or payload.page_ref > document.page_count:
                raise HTTPException(status_code=404, detail=f"PDF page {payload.page_ref} not found.")
            page = document.load_page(payload.page_ref - 1)
            page_rect = page.rect
            left_ratio = _clamp_ratio(payload.left_ratio)
            top_ratio = _clamp_ratio(payload.top_ratio)
            right_ratio = min(1.0, left_ratio + _clamp_ratio(payload.width_ratio))
            bottom_ratio = min(1.0, top_ratio + _clamp_ratio(payload.height_ratio))
            if right_ratio - left_ratio < 0.01 or bottom_ratio - top_ratio < 0.01:
                raise HTTPException(status_code=400, detail="Selected PDF area is too small.")

            clip = fitz.Rect(
                page_rect.x0 + left_ratio * page_rect.width,
                page_rect.y0 + top_ratio * page_rect.height,
                page_rect.x0 + right_ratio * page_rect.width,
                page_rect.y0 + bottom_ratio * page_rect.height,
            )
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
            if pixmap.width < 24 or pixmap.height < 24:
                raise HTTPException(status_code=400, detail="Selected PDF area is too small.")
            metadata = {
                "source": "ui_pdf_crop",
                "layout_source": "manual_pdf_crop",
                "crop_page_ref": payload.page_ref,
                "left_ratio": round(left_ratio, 6),
                "top_ratio": round(top_ratio, 6),
                "width_ratio": round(right_ratio - left_ratio, 6),
                "height_ratio": round(bottom_ratio - top_ratio, 6),
                "render_scale": scale,
            }
            return pixmap.tobytes("png"), int(pixmap.width), int(pixmap.height), metadata
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF area could not be cropped: {exc}") from exc


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
    if _image_assignment_source(item) in {"manual", "manual_crop"}:
        return item

    # Automatic assignments are recalculated on every match run. Otherwise a
    # previous bad heuristic result can become "final" input for the next run.
    clone = dict(item)
    clone["image_assignment_is_final"] = False
    clone["image_auto_match_allowed"] = True
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


def _candidate_aspect_ratio_bonus(
    item: dict[str, Any],
    image: dict[str, Any],
    *,
    image_assignment_is_final: bool,
) -> float:
    diff = image_aspect_difference(item, image)
    if diff is None:
        return 0.0
    if diff <= 0.12:
        return 0.72 if not image_assignment_is_final else 0.54
    if diff <= 0.28:
        return 0.42 if not image_assignment_is_final else 0.30
    if diff <= 0.55:
        return 0.16 if not image_assignment_is_final else 0.10
    if diff >= 1.25:
        return -1.10 if not image_assignment_is_final else -0.80
    if diff >= 0.85:
        return -0.65 if not image_assignment_is_final else -0.46
    return -0.18 if not image_assignment_is_final else -0.12


def _item_has_size_hint(item: dict[str, Any]) -> bool:
    return item_dimension_ratio(item) is not None


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
                and is_viable_auto_assignment_image_for_item(item, image_by_id.get(image_id, {}))
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
    has_size_hint = _item_has_size_hint(item)
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
        if not image_assignment_is_final and not image_within_item_vertical_window(item, image):
            continue
        if (
            not image_assignment_is_final
            and page_ref is not None
            and image_page is not None
        ):
            same_page = image_page == page_ref
            next_page_carryover = (
                image_page == page_ref + 1
                and next_page_allowed
                and (prefers_next_page or not same_page_viable_exists or has_size_hint)
                and is_viable_auto_assignment_image_for_item(item, image)
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
        aspect_bonus = _candidate_aspect_ratio_bonus(
            item,
            image,
            image_assignment_is_final=image_assignment_is_final,
        )
        score = (
            page_bonus
            + area_bonus
            + primary_bonus
            + rank_bonus
            + aspect_bonus
            + decorative_penalty
            + repeated_penalty
        )
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
    has_size_hint = _item_has_size_hint(item)
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
            and is_viable_auto_assignment_image_for_item(item, image)
        )
        for image in candidate_images
    )

    score_rows: list[dict[str, Any]] = []
    for candidate_index, image in enumerate(candidate_images):
        image_id = _to_int_safe(image.get("id"))
        if image_id is None:
            continue
        image_page = _to_int_safe(image.get("page_ref"))
        if not image_assignment_is_final and not image_within_item_vertical_window(item, image):
            continue
        if (
            not image_assignment_is_final
            and page_ref is not None
            and image_page is not None
        ):
            same_page = image_page == page_ref
            next_page_carryover = (
                image_page == page_ref + 1
                and next_page_allowed
                and (prefers_next_page or not same_page_viable_exists or has_size_hint)
                and is_viable_auto_assignment_image_for_item(item, image)
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
        score += _candidate_aspect_ratio_bonus(
            item,
            image,
            image_assignment_is_final=image_assignment_is_final,
        )
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
                "reason": "heuristic(page+layout_rank+area+aspect+decorative+primary)",
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


def _build_line_item_rows(extracted_text: str, template: str, source_path: Path | None = None) -> list[dict]:
    rows: list[dict] = []
    items = extract_line_items(extracted_text, template)
    if template == "alu_one" and source_path is not None and source_path.exists():
        try:
            hints = extract_alu_one_line_item_layout_hints(source_path)
        except Exception:
            hints = []
        hint_index = 0
        for item in items:
            position_no = str(item.get("position_no") or "").strip()
            page_ref = _to_int_safe(item.get("page_ref"))
            while hint_index < len(hints):
                hint = hints[hint_index]
                hint_pos = str(hint.get("position_no") or "").strip()
                hint_page = _to_int_safe(hint.get("page_ref"))
                if hint_pos == position_no and hint_page == page_ref:
                    item["item_top_ratio"] = hint.get("item_top_ratio")
                    hint_index += 1
                    break
                hint_index += 1
        hinted_items = [item for item in items if item.get("item_top_ratio") is not None and _to_int_safe(item.get("page_ref")) is not None]
        for idx, item in enumerate(hinted_items[:-1]):
            next_item = hinted_items[idx + 1]
            item["next_position_page_ref"] = _to_int_safe(next_item.get("page_ref"))
            item["next_position_top_ratio"] = next_item.get("item_top_ratio")

        page_groups: dict[int, list[dict[str, Any]]] = {}
        for item in items:
            page_ref = _to_int_safe(item.get("page_ref"))
            if page_ref is None:
                continue
            if item.get("item_top_ratio") is None:
                continue
            page_groups.setdefault(page_ref, []).append(item)
        for page_items in page_groups.values():
            page_items.sort(key=lambda entry: float(entry.get("item_top_ratio") or 0.0))
            for idx, item in enumerate(page_items[:-1]):
                next_item = page_items[idx + 1]
                item["next_item_top_ratio"] = next_item.get("item_top_ratio")
        ordered_pages = sorted(page_groups)
        for page_idx, page_ref in enumerate(ordered_pages[:-1]):
            current_items = page_groups.get(page_ref) or []
            next_page_items = page_groups.get(ordered_pages[page_idx + 1]) or []
            if not current_items or not next_page_items:
                continue
            last_item = max(current_items, key=lambda entry: float(entry.get("item_top_ratio") or 0.0))
            first_next_item = min(next_page_items, key=lambda entry: float(entry.get("item_top_ratio") or 0.0))
            last_item["next_page_first_item_top_ratio"] = first_next_item.get("item_top_ratio")

    for item in items:
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
        if item.get("item_top_ratio") is not None:
            metadata["item_top_ratio"] = float(item.get("item_top_ratio"))
        if item.get("next_item_top_ratio") is not None:
            metadata["next_item_top_ratio"] = float(item.get("next_item_top_ratio"))
        if item.get("next_page_first_item_top_ratio") is not None:
            metadata["next_page_first_item_top_ratio"] = float(item.get("next_page_first_item_top_ratio"))
        if item.get("next_position_page_ref") is not None:
            metadata["next_position_page_ref"] = int(item.get("next_position_page_ref"))
        if item.get("next_position_top_ratio") is not None:
            metadata["next_position_top_ratio"] = float(item.get("next_position_top_ratio"))
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


@app.on_event("startup")
def startup() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DUMP_DIR.mkdir(parents=True, exist_ok=True)
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


def _load_package_result(request: DocumentPackageRequest) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    missing: list[int] = []
    seen: set[int] = set()
    for document_id in request.document_ids:
        if document_id in seen:
            continue
        seen.add(document_id)
        result = get_document_result(document_id)
        if result is None:
            missing.append(document_id)
            continue
        results.append(result)
    if missing:
        raise HTTPException(status_code=404, detail=f"Documents not found: {', '.join(str(item) for item in missing)}")
    try:
        return build_document_package_result(results, main_document_id=request.main_document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _apply_srtemp_preview(vendoc_payload: dict[str, Any], include_sql: bool) -> list[dict[str, Any]]:
    errors = list(vendoc_payload.get("errors") or [])
    if include_sql:
        try:
            vendoc_payload["srtemp"] = build_srtemp_export_preview(vendoc_payload, config=config_from_env())
        except ValueError as exc:
            errors.append(
                {
                    "code": "srtemp_sql_preview_failed",
                    "scope": "vendoc",
                    "message": str(exc),
                }
            )
    vendoc_payload["errors"] = errors
    if isinstance(vendoc_payload.get("summary"), dict):
        vendoc_payload["summary"]["error_count"] = len(errors)
    return errors


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


@app.get("/document/{document_id}/page/{page_ref}/preview")
def document_page_preview(
    document_id: int,
    page_ref: int,
    scale: float = Query(default=2.0, ge=0.5, le=4.0),
):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    source_path = Path(document["source_file"])
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail=f"Source file not found: {source_path}")
    content, width, height = _render_pdf_page_png(source_path, page_ref, scale=scale)
    return Response(
        content=content,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Page-Width": str(width),
            "X-Page-Height": str(height),
        },
    )


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


@app.post("/documents/{document_id}/line-items/{line_item_id}/crop-image")
def crop_line_item_image(document_id: int, line_item_id: int, payload: PdfCropImageRequest):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Result for document {document_id} not found.")

    line_items_raw = result_data.get("line_items")
    line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []
    line_item = next((item for item in line_items if _to_int_safe(item.get("id")) == line_item_id), None)
    if not line_item:
        raise HTTPException(status_code=404, detail=f"Line item {line_item_id} for document {document_id} not found.")

    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    source_path = Path(document["source_file"])
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=404, detail=f"Source file not found: {source_path}")

    image_bytes, width, height, metadata = _crop_pdf_region_to_png(source_path, payload)
    metadata.update(
        {
            "line_item_id": line_item_id,
            "position_no": line_item.get("position_no"),
            "lv_pos": line_item.get("lv_pos"),
        }
    )

    digest = sha256(image_bytes).hexdigest()
    output_dir = IMAGE_DUMP_DIR / f"document_{document_id}" / "manual_crops"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"manual_crop_line_{line_item_id}_page_{payload.page_ref}_{uuid4().hex[:10]}.png"
    output_path.write_bytes(image_bytes)

    image = insert_document_image(
        document_id,
        {
            "page_ref": payload.page_ref,
            "mime_type": "image/png",
            "storage_path": str(output_path),
            "sha256": digest,
            "width": width,
            "height": height,
            "bytes_size": len(image_bytes),
            "metadata_json": metadata,
        },
    )

    image_id = int(image["id"])
    updated = update_line_item_image_assignments(
        document_id,
        {
            line_item_id: {
                "image_ids": [image_id],
                "selection_source": "manual_crop",
                "selection_reason": "ui_pdf_crop",
                "strategy_requested": "manual_crop",
                "review_checked": True,
                "review_checked_reason": "ui_pdf_crop",
            }
        },
    )
    if updated <= 0:
        raise HTTPException(status_code=500, detail="Manual PDF crop could not be assigned to the line item.")

    return {
        "ok": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "image_id": image_id,
        "page_ref": payload.page_ref,
        "width": width,
        "height": height,
        "selection_source": "manual_crop",
        "selection_reason": "ui_pdf_crop",
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


@app.get("/relations/{document_id}")
def document_relations(document_id: int):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    return _json_safe({"document_id": document_id, **get_document_relations(document_id)})


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


@app.post("/match-images/{document_id}")
def match_images(
    document_id: int,
    strategy: str = Query(default="heuristic"),
    max_candidates: int = Query(default=4, ge=1, le=10),
    max_items: int = Query(default=60, ge=1, le=500),
    allow_multiple: bool = Query(default=True),
):
    if strategy != "heuristic":
        raise HTTPException(status_code=400, detail=f"{AI_DISABLED_DETAIL} Bildzuordnung laeuft heuristisch.")

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

    items_out: list[dict[str, Any]] = []
    for item in line_items[:max_items]:
        matching_item = _item_for_image_matching(item)
        candidates = _candidate_images_for_item(matching_item, image_by_id, max_candidates=max_candidates)
        heuristic = _heuristic_match_for_item(matching_item, candidates, allow_multiple=allow_multiple)
        heuristic_selected = list(heuristic.get("selected_image_ids") or [])

        final_selected = heuristic_selected
        final_source = "heuristic"
        final_reason = "heuristic_default"

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
    heuristic_selected_items = len([item for item in items_out if item.get("selection_source", "").startswith("heuristic")])

    return _json_safe(
        {
            "document_id": document_id,
            "strategy_requested": strategy,
            "max_candidates": max_candidates,
            "max_items": max_items,
            "allow_multiple": allow_multiple,
            "summary": {
                "line_items_processed": len(items_out),
                "line_items_total": len(line_items),
                "matched_items": matched_items,
                "unmatched_items": len(items_out) - matched_items,
                "single_matches": single_matches,
                "multi_matches": multi_matches,
                "heuristic_selected_items": heuristic_selected_items,
            },
            "items": items_out,
        }
    )


def _persist_image_assignments(
    document_id: int,
    *,
    strategy: Literal["heuristic"],
    allow_multiple: bool = False,
) -> dict[str, Any]:
    try:
        payload = match_images(
            document_id=document_id,
            strategy=strategy,
            max_candidates=6,
            max_items=250,
            allow_multiple=allow_multiple,
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
        "heuristic_selected_items": (payload.get("summary") or {}).get("heuristic_selected_items"),
    }


@app.get("/vendoc/health")
def vendoc_health(check_connection_live: bool = Query(default=False, alias="check_connection")):
    enabled = _is_truthy(os.getenv("VENDOC_MSSQL_ENABLED"), default=False)
    host = _vendoc_target_server()
    database = _vendoc_target_database()
    driver = driver_status()
    config = config_from_env()
    connection = None
    if enabled and config and check_connection_live:
        connection = check_connection(config)
    return {
        "ok": bool(enabled and config and driver.get("available") and ((connection or {}).get("ok") if check_connection_live else True)),
        "status": (
            "disabled"
            if not enabled
            else ("missing_config" if config is None else ((connection or {}).get("status") or "configured"))
        ),
        "target_server_configured": bool(host),
        "target_database": database,
        "driver": driver,
        "connection": connection,
        "live_write_available": bool(enabled and config and driver.get("available")),
        "connection_tested": check_connection_live,
        "message": (
            "MSSQL live write is disabled."
            if not enabled
            else (
                "MSSQL config is incomplete."
                if config is None
                else ((connection or {}).get("message") or "MSSQL live write is configured.")
            )
        ),
    }


@app.post("/document-packages/preview")
def document_package_preview(request: DocumentPackageRequest):
    package_result = _load_package_result(request)
    return _json_safe(
        {
            "ok": True,
            "package": package_result.get("package"),
            "document": package_result.get("document"),
            "amount_lines": package_result.get("amount_lines"),
            "line_items": package_result.get("line_items"),
            "images": package_result.get("images"),
            "validation": package_result.get("validation"),
        }
    )


@app.post("/vendoc/export-package")
def vendoc_export_document_package(
    request: DocumentPackageRequest,
    dry_run: bool = Query(default=True),
    include_sql: bool = Query(default=False),
):
    result_data = _load_package_result(request)
    document = result_data.get("document") if isinstance(result_data.get("document"), dict) else {}
    document_id = int(document.get("id") or result_data.get("package", {}).get("main_document_id") or 0)
    if document_id <= 0:
        raise HTTPException(status_code=400, detail="Package main document id is missing.")

    try:
        vendoc_payload = build_vendoc_payload(result_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    vendoc_payload["package"] = result_data.get("package")

    errors = _apply_srtemp_preview(vendoc_payload, include_sql)
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
                "package": result_data.get("package"),
                "vendoc": vendoc_payload,
            }
        )

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
                "scope": "approval",
                "message": "Live-Export ist erst nach Freigabe des Hauptdokuments erlaubt.",
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
            status_code=400,
            detail={
                "message": error_text,
                "job": _vendoc_job_response(job),
                "package": result_data.get("package"),
                "vendoc": vendoc_payload,
            },
        )

    config = config_from_env()
    if config is None:
        live_error = {
            "code": "mssql_config_incomplete",
            "scope": "vendoc",
            "message": "MSSQL-Ziel ist aktiviert, aber Host/User/Passwort sind nicht vollstaendig konfiguriert.",
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
                "package": result_data.get("package"),
            },
        )

    try:
        write_result = write_srtemp_payload(vendoc_payload, config)
    except Exception as exc:
        live_error = {
            "code": "mssql_write_failed",
            "scope": "vendoc",
            "message": str(exc)[:1000],
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
            status_code=502,
            detail={
                "message": "MSSQL Live-Write fehlgeschlagen.",
                "error": live_error,
                "job": _vendoc_job_response(job),
                "package": result_data.get("package"),
            },
        ) from exc

    job = _record_vendoc_export_job(
        document_id=document_id,
        result_data=result_data,
        vendoc_payload=vendoc_payload,
        dry_run=False,
        status="exported",
        error_text=None,
    )
    return _json_safe(
        {
            "ok": True,
            "document_id": document_id,
            "dry_run": False,
            "status": "exported",
            "job": _vendoc_job_response(job),
            "package": result_data.get("package"),
            "write": write_result,
            "vendoc": vendoc_payload,
        }
    )


@app.post("/vendoc/export/{document_id}")
def vendoc_export_document(
    document_id: int,
    dry_run: bool = Query(default=True),
    include_sql: bool = Query(default=False),
):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    try:
        vendoc_payload = build_vendoc_payload(result_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    errors = list(vendoc_payload.get("errors") or [])
    if include_sql:
        try:
            vendoc_payload["srtemp"] = build_srtemp_export_preview(vendoc_payload, config=config_from_env())
        except ValueError as exc:
            errors.append(
                {
                    "code": "srtemp_sql_preview_failed",
                    "scope": "vendoc",
                    "message": str(exc),
                }
            )
    vendoc_payload["errors"] = errors
    if isinstance(vendoc_payload.get("summary"), dict):
        vendoc_payload["summary"]["error_count"] = len(errors)
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

    config = config_from_env()
    if config is None:
        live_error = {
            "code": "mssql_config_incomplete",
            "scope": "vendoc",
            "message": "MSSQL-Ziel ist aktiviert, aber Host/User/Passwort sind nicht vollstaendig konfiguriert.",
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

    try:
        write_result = write_srtemp_payload(vendoc_payload, config)
    except Exception as exc:
        live_error = {
            "code": "mssql_write_failed",
            "scope": "vendoc",
            "message": str(exc)[:1000],
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
            status_code=502,
            detail={
                "message": "MSSQL Live-Write fehlgeschlagen.",
                "error": live_error,
                "job": _vendoc_job_response(job),
            },
        ) from exc

    job = _record_vendoc_export_job(
        document_id=document_id,
        result_data=result_data,
        vendoc_payload=vendoc_payload,
        dry_run=False,
        status="exported",
        error_text=None,
    )
    return _json_safe(
        {
            "ok": True,
            "document_id": document_id,
            "dry_run": False,
            "status": "exported",
            "job": _vendoc_job_response(job),
            "write": write_result,
            "vendoc": vendoc_payload,
        }
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
    process_mode: str | None = Query(default="parser_only"),
    use_ai: bool = Query(default=False, alias="use_llm", include_in_schema=False),
    ai_override: bool = Query(default=False, alias="llm_override", include_in_schema=False),
):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    source_path = Path(document["source_file"])
    if not source_path.exists():
        update_document_status(document_id, status="failed", error_message=f"File missing: {source_path}")
        raise HTTPException(status_code=400, detail=f"Source file does not exist: {source_path}")

    requested_mode = _resolve_process_mode(process_mode=process_mode, use_ai=use_ai, ai_override=ai_override)
    update_document_status(document_id, status="processing", error_message=None)
    update_document_approval_state(document_id, approval_status="pending")

    _set_process_progress(
        document_id,
        stage="start",
        message=f"Verarbeitung gestartet (Mode: {requested_mode}).",
        mode=requested_mode,
        status="processing",
    )
    process_mode_effective = "parser_only"
    template = "generic"
    position_count = 0
    line_item_rows: list[dict[str, Any]] = []
    amount_line_rows: list[dict[str, Any]] = []
    image_rows: list[dict[str, Any]] = []
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
            stage="parse_text",
            message="Parser extrahiert Felder, Positionen und Betragszeilen.",
            mode=requested_mode,
            status="processing",
        )
        parsed = parse_document_text(extracted_text)
        template = _clean_optional_str(parsed.get("template")) or "generic"
        _set_process_progress(
            document_id,
            stage="extract_images",
            message="PDF-Bilder werden extrahiert.",
            mode=requested_mode,
            status="processing",
        )
        image_rows = extract_pdf_images(source_path, IMAGE_DUMP_DIR / f"document_{document_id}")
        image_rows = _postprocess_image_rows(
            image_rows,
            template=template,
            document_type=parsed.get("document_type"),
            extracted_text=extracted_text,
        )
        amount_line_rows = _build_amount_line_rows(
            extracted_text,
            parsed.get("totals") if isinstance(parsed.get("totals"), dict) else {},
        )
        line_item_rows = _build_line_item_rows(extracted_text, template, source_path=source_path)

        _set_process_progress(
            document_id,
            stage="persist_rows",
            message="Extraktion wird in die Datenbank geschrieben.",
            mode=requested_mode,
            status="processing",
        )
        totals = parsed.get("totals")
        totals = totals if isinstance(totals, dict) else {}
        net_total = _parse_eu_decimal(totals.get("net_total"))
        vat_total = _parse_eu_decimal(totals.get("vat_total"))
        gross_total = _parse_eu_decimal(totals.get("gross_total"))
        date_value = _parse_date(parsed.get("document_date"))
        supplier_name = supplier_name_for_template(template) or _clean_optional_str(parsed.get("supplier_name"))
        replace_document_amount_lines(document_id, amount_line_rows)
        replace_line_items(document_id, line_item_rows)
        replace_document_images(document_id, image_rows)
        if line_item_rows and image_rows:
            _set_process_progress(
                document_id,
                stage="image_match",
                message="Bildzuordnung pro Position wird berechnet.",
                mode=requested_mode,
                status="processing",
            )
            image_assignment_summary = _persist_image_assignments(
                document_id,
                strategy="heuristic",
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
            document_notes=_clean_optional_str(parsed.get("document_notes")),
        )
        refreshed = refresh_document_links(document_id)
        if refreshed:
            updated = refreshed
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
        "parser_used": True,
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
        "linked_offer_document_id": updated.get("linked_offer_document_id"),
        "image_assignment": image_assignment_summary,
        "updated_at": updated["updated_at"],
    }


@app.post("/dev/parse-text")
def parse_text(request: ParseTextRequest):
    return parse_document_text(request.text)
