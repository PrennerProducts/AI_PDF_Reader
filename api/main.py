import base64
import binascii
from io import BytesIO
import re
import hmac
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import pbkdf2_hmac, sha256
import json
import os
from pathlib import Path
import shutil
from threading import Lock
from typing import Any, Callable, Literal
from uuid import UUID, uuid4

import fitz
from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from db import (
    apply_migrations,
    count_app_users,
    create_app_session,
    create_app_user,
    ensure_app_user,
    get_app_session_user,
    get_app_user_by_username,
    get_document,
    get_document_image,
    get_vendoc_import_state,
    get_document_result,
    get_latest_vendoc_export_job,
    insert_document,
    insert_audit_event,
    insert_document_image,
    insert_vendoc_export_job,
    list_documents,
    list_offer_candidates,
    set_document_linked_offer,
    list_vendoc_export_jobs,
    get_document_relations,
    refresh_document_links,
    reset_document_results,
    update_line_item_alternative_append_mode,
    update_line_item_embedded_alternative_append_mode,
    update_line_item_fields,
    update_line_item_image_assignments,
    update_line_item_line_total_override,
    update_line_item_review_state,
    replace_document_images,
    replace_document_amount_lines,
    replace_line_items,
    revoke_app_session,
    update_document_approval_state,
    update_document_alternative_position_mode,
    update_document_parse_result,
    update_document_pricing_adjustments,
    update_document_status,
    update_document_vendoc_customer,
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
from template_rieder import extract_delivery_charge_item as extract_rieder_delivery_charge_item
from template_koch_detail import parse_page_details as parse_koch_detail_page_details
from vendoc_exporter import build_vendoc_payload
from vendoc_mssql import (
    build_srtemp_export_preview,
    check_connection,
    config_from_env,
    customer_view_from_env,
    driver_status,
    list_customer_options,
    write_srtemp_payload,
)

app = FastAPI(title="PDF Reader PoC API")

UPLOAD_DIR = Path("/data/uploads")
EXPORT_DIR = Path("/data/exports")
TEXT_DUMP_DIR = Path("/data/logs/extracted_text")
IMAGE_DUMP_DIR = Path("/data/logs/extracted_images")
UI_DIR = Path(__file__).resolve().parent / "ui"
UI_INDEX_PATH = UI_DIR / "index.html"
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
SCREEN_CROP_MAX_BYTES = 12 * 1024 * 1024
PROCESS_MODES = ("parser_only",)
AI_DISABLED_DETAIL = (
    "KI-/Modellverarbeitung ist im Produktbetrieb deaktiviert. "
    "Erlaubt ist nur die lokale Parser-Verarbeitung."
)

PROCESS_PROGRESS: dict[int, dict[str, Any]] = {}
PROCESS_PROGRESS_LOCK = Lock()
SESSION_COOKIE_NAME = "pdr_session"
PASSWORD_HASH_ITERATIONS = 260_000
AUTH_EXEMPT_PATHS = {
    "/",
    "/ui",
    "/health",
    "/auth/login",
    "/auth/logout",
    "/auth/me",
    "/auth/setup-status",
    "/auth/register",
}


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


class ScreenCropImageRequest(BaseModel):
    page_ref: int = Field(ge=1, description="Reference PDF page for sorting/manual review.")
    image_data_url: str = Field(min_length=1, description="Browser-captured crop as image data URL.")


class DocumentApprovalRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000, description="Optional approval note.")


class DocumentVendocCustomerRequest(BaseModel):
    contact_oid: str | None = Field(default=None, max_length=120)
    customer_number: str | None = Field(default=None, max_length=120)
    uid_number: str | None = Field(default=None, max_length=120)
    display_name: str | None = Field(default=None, max_length=255)
    inactive: bool | None = Field(default=None)


class DocumentAlternativePositionModeRequest(BaseModel):
    mode: Literal["nested", "append"] = "nested"


class DocumentPricingAdjustmentsRequest(BaseModel):
    apply_pricing_adjustments: bool = True


class DocumentLinkedOfferRequest(BaseModel):
    linked_offer_document_id: int | None = Field(default=None)


class LineItemAlternativeAppendRequest(BaseModel):
    append_at_end: bool = False


class LineItemLineTotalOverrideRequest(BaseModel):
    line_total: Decimal = Field(ge=0, le=Decimal("99999999.99"))


class LineItemUpdateRequest(BaseModel):
    position_no: str | None = Field(default=None, max_length=80)
    lv_pos: str | None = Field(default=None, max_length=120)
    is_alternative: bool | None = None
    quantity: Decimal | None = Field(default=None, ge=0, le=Decimal("99999999.9999"))
    unit: str | None = Field(default=None, max_length=80)
    width_mm: Decimal | None = Field(default=None, ge=0, le=Decimal("99999999.99"))
    height_mm: Decimal | None = Field(default=None, ge=0, le=Decimal("99999999.99"))
    description_short: str | None = Field(default=None, max_length=1000)
    description_long: str | None = Field(default=None, max_length=20000)
    unit_price: Decimal | None = Field(default=None, ge=0, le=Decimal("99999999.99"))
    line_total: Decimal | None = Field(default=None, ge=0, le=Decimal("99999999.99"))
    page_ref: int | None = Field(default=None, ge=1, le=9999)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=1, max_length=500)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=4, max_length=500)
    display_name: str | None = Field(default=None, max_length=160)


def _safe_filename(filename: str) -> str:
    base_name = Path(filename).name.strip()
    if not base_name:
        return "upload.pdf"
    sanitized = SAFE_FILENAME_RE.sub("_", base_name).strip("._")
    if not sanitized:
        return "upload.pdf"
    return sanitized


def _auth_enabled() -> bool:
    return _is_truthy(os.getenv("APP_AUTH_ENABLED"), default=False)


def _session_ttl_hours() -> int:
    raw = str(os.getenv("APP_SESSION_TTL_HOURS") or "12").strip()
    try:
        parsed = int(raw)
    except ValueError:
        return 12
    return max(1, min(parsed, 24 * 30))


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


def _hash_session_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _hash_password(password: str, *, salt_hex: str | None = None, iterations: int = PASSWORD_HASH_ITERATIONS) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    parts = str(stored_hash).split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
        expected = _hash_password(password, salt_hex=parts[2], iterations=iterations)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected, stored_hash)


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "display_name": user.get("display_name") or user.get("username"),
    }


def _current_user_from_request(request: Request) -> dict[str, Any] | None:
    user = getattr(request.state, "user", None)
    return user if isinstance(user, dict) else None


def _require_user(request: Request) -> dict[str, Any]:
    if not _auth_enabled():
        return {"id": None, "username": "dev", "display_name": "Dev"}
    user = _current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login erforderlich.")
    return user


def _audit(
    request: Request,
    action: str,
    *,
    document_id: int | None = None,
    line_item_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    user = _current_user_from_request(request)
    if not user and not _auth_enabled():
        user = {"id": None, "username": "dev", "display_name": "Dev"}
    try:
        insert_audit_event(
            action=action,
            actor_user_id=int(user["id"]) if user and user.get("id") is not None else None,
            actor_username=str(user.get("username")) if user and user.get("username") else None,
            actor_ip=_client_ip(request),
            document_id=document_id,
            line_item_id=line_item_id,
            details=details or {},
        )
    except Exception as exc:
        print(f"Audit event failed for {action}: {exc}")


def _bootstrap_auth_user() -> None:
    username = _clean_optional_str(os.getenv("APP_BOOTSTRAP_USERNAME"))
    password = os.getenv("APP_BOOTSTRAP_PASSWORD")
    if not username or not password:
        return
    display_name = _clean_optional_str(os.getenv("APP_BOOTSTRAP_DISPLAY_NAME")) or username
    ensure_app_user(
        username=username,
        password_hash=_hash_password(password),
        display_name=display_name,
    )


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not _auth_enabled() or request.url.path in AUTH_EXEMPT_PATHS:
        return await call_next(request)

    token = request.cookies.get(SESSION_COOKIE_NAME)
    user = get_app_session_user(_hash_session_token(token)) if token else None
    if not user:
        return JSONResponse({"detail": "Login erforderlich."}, status_code=401)

    request.state.user = user
    return await call_next(request)


@app.get("/auth/me")
def auth_me(request: Request):
    if not _auth_enabled():
        return {"ok": True, "auth_enabled": False, "user": {"id": None, "username": "dev", "display_name": "Dev"}}

    token = request.cookies.get(SESSION_COOKIE_NAME)
    user = get_app_session_user(_hash_session_token(token)) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Login erforderlich.")
    return {"ok": True, "auth_enabled": True, "user": _public_user(user)}


@app.post("/auth/login")
def auth_login(payload: LoginRequest, request: Request, response: Response):
    user = get_app_user_by_username(payload.username)
    if not user or not _verify_password(payload.password, str(user.get("password_hash") or "")):
        raise HTTPException(status_code=401, detail="Benutzername oder Passwort ist falsch.")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Benutzer ist deaktiviert.")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=_session_ttl_hours())
    create_app_session(
        user_id=int(user["id"]),
        session_token_hash=_hash_session_token(token),
        expires_at=expires_at,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=_session_ttl_hours() * 3600,
    )
    request.state.user = user
    _audit(request, "auth_login")
    return {"ok": True, "user": _public_user(user)}


@app.get("/auth/setup-status")
def auth_setup_status():
    if not _auth_enabled():
        return {"ok": True, "auth_enabled": False, "needs_setup": False}
    return {"ok": True, "auth_enabled": True, "needs_setup": count_app_users() == 0}


@app.post("/auth/register")
def auth_register(payload: CreateUserRequest, request: Request, response: Response):
    if not _auth_enabled():
        raise HTTPException(status_code=400, detail="Login ist nicht aktiv.")
    if count_app_users() > 0:
        raise HTTPException(status_code=403, detail="Registrierung ist nur fuer den ersten Benutzer offen.")

    try:
        user = create_app_user(
            username=payload.username,
            password_hash=_hash_password(payload.password),
            display_name=_clean_optional_str(payload.display_name),
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Benutzer konnte nicht angelegt werden: {exc}") from exc

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=_session_ttl_hours())
    create_app_session(
        user_id=int(user["id"]),
        session_token_hash=_hash_session_token(token),
        expires_at=expires_at,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=_session_ttl_hours() * 3600,
    )
    request.state.user = user
    _audit(request, "auth_first_user_registered")
    return {"ok": True, "user": _public_user(user)}


@app.post("/auth/logout")
def auth_logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        user = get_app_session_user(_hash_session_token(token))
        if user:
            request.state.user = user
            _audit(request, "auth_logout")
        revoke_app_session(_hash_session_token(token))
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@app.post("/auth/users")
def auth_create_user(payload: CreateUserRequest, request: Request):
    _require_user(request)
    try:
        created = create_app_user(
            username=payload.username,
            password_hash=_hash_password(payload.password),
            display_name=_clean_optional_str(payload.display_name),
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Benutzer konnte nicht angelegt werden: {exc}") from exc
    _audit(request, "user_created", details={"username": created.get("username")})
    return {"ok": True, "user": _public_user(created)}


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

    if template == "schachermayer" and str(document_type or "").lower() in {"angebot", "auftragsbestaetigung"}:
        return []

    if template == "schlotterer" and str(document_type or "").lower() in {"angebot", "auftragsbestaetigung"}:
        return []

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


LINE_ITEM_DECIMAL_EDIT_FIELDS = {
    "quantity": Decimal("0.0001"),
    "width_mm": Decimal("0.01"),
    "height_mm": Decimal("0.01"),
    "unit_price": Decimal("0.01"),
    "line_total": Decimal("0.01"),
}
LINE_ITEM_TEXT_EDIT_FIELDS = {
    "position_no",
    "lv_pos",
    "unit",
    "description_short",
    "description_long",
}


def _line_item_update_payload(payload: LineItemUpdateRequest) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        raw_updates = payload.model_dump(exclude_unset=True)
    else:
        raw_updates = payload.dict(exclude_unset=True)
    updates: dict[str, Any] = {}
    for field, value in raw_updates.items():
        if field in LINE_ITEM_TEXT_EDIT_FIELDS:
            updates[field] = _clean_optional_str(value)
            continue
        if field in LINE_ITEM_DECIMAL_EDIT_FIELDS:
            if value is None:
                updates[field] = None
                continue
            try:
                updates[field] = Decimal(str(value)).quantize(
                    LINE_ITEM_DECIMAL_EDIT_FIELDS[field],
                    rounding=ROUND_HALF_UP,
                )
            except (InvalidOperation, ValueError):
                raise HTTPException(status_code=422, detail=f"{field} is not a valid decimal value.")
            continue
        if field == "page_ref":
            updates[field] = int(value) if value is not None else None
            continue
        if field == "is_alternative":
            updates[field] = bool(value) if value is not None else False
    return updates


def _line_item_edit_compare_value(field: str, value: Any) -> Any:
    if field in LINE_ITEM_TEXT_EDIT_FIELDS:
        return _clean_optional_str(value)
    if field in LINE_ITEM_DECIMAL_EDIT_FIELDS:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value)).quantize(LINE_ITEM_DECIMAL_EDIT_FIELDS[field], rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError, TypeError):
            return None
    if field == "page_ref":
        return _to_int_safe(value)
    if field == "is_alternative":
        return bool(value)
    return value


def _changed_line_item_updates(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    for field, value in updates.items():
        old_value = _line_item_edit_compare_value(field, current.get(field))
        new_value = _line_item_edit_compare_value(field, value)
        if old_value != new_value:
            changed[field] = value
    return changed


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


def _screen_crop_data_url_to_png(payload: ScreenCropImageRequest) -> tuple[bytes, int, int, str]:
    data_url = payload.image_data_url.strip()
    if "," not in data_url:
        raise HTTPException(status_code=400, detail="Screenshot payload must be an image data URL.")
    header, encoded = data_url.split(",", 1)
    header = header.lower()
    if not header.startswith("data:image/") or ";base64" not in header:
        raise HTTPException(status_code=400, detail="Screenshot payload must be a base64 image data URL.")
    mime_type = header[5:].split(";", 1)[0]
    if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=400, detail="Screenshot payload must be PNG, JPEG or WebP.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Screenshot payload is not valid base64.") from exc
    if not raw or len(raw) > SCREEN_CROP_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Screenshot payload is empty or too large.")

    try:
        with Image.open(BytesIO(raw)) as image:
            image.load()
            width, height = int(image.width), int(image.height)
            if width < 24 or height < 24:
                raise HTTPException(status_code=400, detail="Selected screenshot area is too small.")
            normalized = image.convert("RGB")
            buffer = BytesIO()
            normalized.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue(), width, height, mime_type
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Screenshot payload is not a readable image.") from exc


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


def _build_amount_line_rows(
    extracted_text: str,
    totals: dict[str, str | None],
    *,
    template: str | None = None,
) -> list[dict]:
    def _format_amount_line_decimal(value: Decimal) -> str:
        return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")

    rows: list[dict] = []
    schlotterer_discount_groups = _parse_schlotterer_discount_groups(extracted_text) if template == "schlotterer" else []
    schlotterer_discount_insert_order: Decimal | None = None
    for item in extract_amount_lines(extracted_text):
        line_type = item.get("line_type", "other")
        if template == "alu_one" and line_type not in {"net_total", "vat", "total"}:
            continue
        label_raw = item.get("label_raw", "")
        normalized_label = str(label_raw or "").strip().lower()
        if template == "schuchter" and "summe positionen" in normalized_label:
            line_type = "subtotal"
        if schlotterer_discount_groups:
            if "gesamtpreis positionen" in normalized_label:
                line_type = "subtotal"
            if line_type == "discount" and normalized_label.startswith("rabatte"):
                schlotterer_discount_insert_order = Decimal(str(item.get("sort_order", len(rows)))) + Decimal("0.10")
                continue
            if normalized_label.startswith("summe:"):
                continue
        amount = _parse_eu_decimal(item.get("amount_raw"))
        if amount is None:
            continue
        rows.append(
            {
                "line_type": line_type,
                "label_raw": label_raw,
                "percent": _parse_eu_decimal(item.get("percent_raw")),
                "base_amount": _parse_eu_decimal(item.get("base_amount_raw")),
                "amount": amount,
                "sort_order": item.get("sort_order", 0),
            }
        )

    if schlotterer_discount_groups:
        if schlotterer_discount_insert_order is None:
            subtotal_orders = [
                Decimal(str(row.get("sort_order", 0)))
                for row in rows
                if row.get("line_type") == "subtotal"
            ]
            schlotterer_discount_insert_order = (max(subtotal_orders) if subtotal_orders else Decimal("0")) + Decimal("0.10")
        for offset, group in enumerate(schlotterer_discount_groups):
            rows.append(
                {
                    "line_type": "discount",
                    "label_raw": (
                        f"{group['label']} {_format_amount_line_decimal(group['base_amount'])} "
                        f"{_format_amount_line_decimal(group['percent'])}% "
                        f"{_format_amount_line_decimal(group['discount_amount'])}"
                    ),
                    "percent": group["percent"],
                    "base_amount": group["base_amount"],
                    "amount": group["discount_amount"],
                    "sort_order": schlotterer_discount_insert_order + Decimal(offset + 1) / Decimal("100"),
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


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _line_item_metadata_dict(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata_json")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _set_line_item_metadata(row: dict[str, Any], metadata: dict[str, Any]) -> None:
    row["metadata_json"] = json.dumps(metadata, ensure_ascii=True)


def _pricing_operations_from_amount_lines(amount_line_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for row in sorted(amount_line_rows or [], key=lambda item: int(item.get("sort_order") or 0)):
        line_type = str(row.get("line_type") or "").strip().lower()
        percent = row.get("percent")
        if line_type not in {"discount", "surcharge"} or percent is None:
            continue
        try:
            percent_decimal = Decimal(percent)
        except (InvalidOperation, TypeError, ValueError):
            continue
        if percent_decimal == 0:
            continue
        operations.append(
            {
                "line_type": line_type,
                "percent": percent_decimal,
                "label_raw": row.get("label_raw") or "",
                "sort_order": row.get("sort_order", 0),
            }
        )
    return operations


def _rieder_pricing_operations(amount_line_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return _pricing_operations_from_amount_lines(amount_line_rows)


def _rieder_last_discount_subtotal(amount_line_rows: list[dict[str, Any]] | None) -> Decimal | None:
    last_subtotal: Decimal | None = None
    for row in sorted(amount_line_rows or [], key=lambda item: int(item.get("sort_order") or 0)):
        line_type = str(row.get("line_type") or "").strip().lower()
        if line_type == "net_total":
            break
        if line_type == "subtotal":
            amount = row.get("amount")
            if isinstance(amount, Decimal):
                last_subtotal = amount
    return last_subtotal


def _last_adjusted_subtotal(amount_line_rows: list[dict[str, Any]] | None) -> Decimal | None:
    last_subtotal_after_adjustment: Decimal | None = None
    saw_adjustment = False
    for row in sorted(amount_line_rows or [], key=lambda item: int(item.get("sort_order") or 0)):
        line_type = str(row.get("line_type") or "").strip().lower()
        if line_type == "net_total":
            break
        if line_type in {"discount", "surcharge"} and row.get("percent") is not None:
            saw_adjustment = True
        if line_type == "subtotal":
            amount = row.get("amount")
            if isinstance(amount, Decimal) and saw_adjustment:
                last_subtotal_after_adjustment = amount
    return last_subtotal_after_adjustment


def _net_total_from_amount_lines(amount_line_rows: list[dict[str, Any]] | None) -> Decimal | None:
    for row in sorted(amount_line_rows or [], key=lambda item: int(item.get("sort_order") or 0)):
        if str(row.get("line_type") or "").strip().lower() != "net_total":
            continue
        amount = row.get("amount")
        if isinstance(amount, Decimal):
            return amount
    return None


def _apply_pricing_operations(value: Decimal, operations: list[dict[str, Any]]) -> Decimal:
    current = value
    for operation in operations:
        percent = operation["percent"] / Decimal("100")
        factor = Decimal("1") + percent if operation["line_type"] == "surcharge" else Decimal("1") - percent
        current = current * factor
    return _money(current)


def _apply_rieder_operations(value: Decimal, operations: list[dict[str, Any]]) -> Decimal:
    return _apply_pricing_operations(value, operations)


def _update_row_unit_price_from_total(row: dict[str, Any]) -> None:
    line_total = row.get("line_total")
    if not isinstance(line_total, Decimal):
        return
    quantity = row.get("quantity")
    if isinstance(quantity, Decimal) and quantity != 0:
        row["unit_price"] = _money(line_total / quantity)
    else:
        row["unit_price"] = line_total


def _operation_metadata(operations: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "line_type": operation["line_type"],
            "percent": str(operation["percent"]),
            "label_raw": operation["label_raw"],
        }
        for operation in operations
    ]


def _apply_sequential_pricing_to_line_item_rows(
    rows: list[dict[str, Any]],
    amount_line_rows: list[dict[str, Any]] | None,
    *,
    provider_key: str,
    skip_pricing_sources: set[str] | None = None,
    skip_row: Callable[[dict[str, Any], dict[str, Any]], bool] | None = None,
    target_subtotal: Decimal | None = None,
) -> None:
    operations = _pricing_operations_from_amount_lines(amount_line_rows)
    if not operations:
        return

    skip_pricing_sources = skip_pricing_sources or set()
    operation_metadata = _operation_metadata(operations)
    normal_row_indexes: list[int] = []
    rounding_row_indexes: list[int] = []
    for index, row in enumerate(rows):
        line_total = row.get("line_total")
        if not isinstance(line_total, Decimal):
            continue
        metadata = _line_item_metadata_dict(row)
        if metadata.get("pricing_source") in skip_pricing_sources or (skip_row is not None and skip_row(row, metadata)):
            if not bool(row.get("is_alternative")):
                normal_row_indexes.append(index)
            continue

        original_line_total = line_total
        original_unit_price = row.get("unit_price")
        adjusted_line_total = _apply_pricing_operations(original_line_total, operations)
        row["line_total"] = adjusted_line_total
        _update_row_unit_price_from_total(row)

        metadata["pricing_adjustment_source"] = f"{provider_key}_amount_lines"
        metadata["pricing_adjustments_applied"] = True
        metadata["pricing_original_line_total"] = str(original_line_total)
        if isinstance(original_unit_price, Decimal):
            metadata["pricing_original_unit_price"] = str(original_unit_price)
        metadata["pricing_adjusted_line_total"] = str(adjusted_line_total)
        if isinstance(row.get("unit_price"), Decimal):
            metadata["pricing_adjusted_unit_price"] = str(row["unit_price"])
        metadata["pricing_operations"] = operation_metadata
        metadata[f"{provider_key}_pricing_applied"] = True
        metadata[f"{provider_key}_original_line_total"] = str(original_line_total)
        if isinstance(original_unit_price, Decimal):
            metadata[f"{provider_key}_original_unit_price"] = str(original_unit_price)
        metadata[f"{provider_key}_adjusted_line_total"] = str(adjusted_line_total)
        if isinstance(row.get("unit_price"), Decimal):
            metadata[f"{provider_key}_adjusted_unit_price"] = str(row["unit_price"])
        metadata[f"{provider_key}_pricing_operations"] = operation_metadata
        _set_line_item_metadata(row, metadata)

        if not bool(row.get("is_alternative")):
            normal_row_indexes.append(index)
            rounding_row_indexes.append(index)

    if target_subtotal is None or not normal_row_indexes:
        return
    current_subtotal = sum((rows[index].get("line_total") for index in normal_row_indexes), Decimal("0.00"))
    delta = _money(target_subtotal - current_subtotal)
    if abs(delta) > Decimal("0.10") or delta == 0:
        return

    target_index = rounding_row_indexes[-1] if rounding_row_indexes else normal_row_indexes[-1]
    target_row = rows[target_index]
    if not isinstance(target_row.get("line_total"), Decimal):
        return
    target_row["line_total"] = _money(target_row["line_total"] + delta)
    _update_row_unit_price_from_total(target_row)
    metadata = _line_item_metadata_dict(target_row)
    metadata["pricing_rounding_delta"] = str(delta)
    metadata[f"{provider_key}_rounding_delta"] = str(delta)
    metadata["pricing_adjusted_line_total"] = str(target_row["line_total"])
    if isinstance(target_row.get("unit_price"), Decimal):
        metadata["pricing_adjusted_unit_price"] = str(target_row["unit_price"])
    metadata[f"{provider_key}_adjusted_line_total"] = str(target_row["line_total"])
    if isinstance(target_row.get("unit_price"), Decimal):
        metadata[f"{provider_key}_adjusted_unit_price"] = str(target_row["unit_price"])
    _set_line_item_metadata(target_row, metadata)


def _apply_rieder_pricing_to_line_item_rows(rows: list[dict[str, Any]], amount_line_rows: list[dict[str, Any]] | None) -> None:
    operations = _rieder_pricing_operations(amount_line_rows)
    if not operations:
        return

    normal_row_indexes: list[int] = []
    for index, row in enumerate(rows):
        line_total = row.get("line_total")
        if not isinstance(line_total, Decimal):
            continue
        metadata = _line_item_metadata_dict(row)
        if metadata.get("pricing_source") == "rieder_delivery_block":
            continue

        original_line_total = line_total
        original_unit_price = row.get("unit_price")
        adjusted_line_total = _apply_rieder_operations(original_line_total, operations)
        row["line_total"] = adjusted_line_total
        _update_row_unit_price_from_total(row)

        metadata["rieder_pricing_applied"] = True
        metadata["rieder_original_line_total"] = str(original_line_total)
        if isinstance(original_unit_price, Decimal):
            metadata["rieder_original_unit_price"] = str(original_unit_price)
        metadata["rieder_adjusted_line_total"] = str(row["line_total"])
        if isinstance(row.get("unit_price"), Decimal):
            metadata["rieder_adjusted_unit_price"] = str(row["unit_price"])
        metadata["rieder_pricing_operations"] = [
            {
                "line_type": operation["line_type"],
                "percent": str(operation["percent"]),
                "label_raw": operation["label_raw"],
            }
            for operation in operations
        ]
        _set_line_item_metadata(row, metadata)

        if not bool(row.get("is_alternative")):
            normal_row_indexes.append(index)

    target_subtotal = _rieder_last_discount_subtotal(amount_line_rows)
    if target_subtotal is None or not normal_row_indexes:
        return
    current_subtotal = sum((rows[index].get("line_total") for index in normal_row_indexes), Decimal("0.00"))
    delta = _money(target_subtotal - current_subtotal)
    if abs(delta) > Decimal("0.10") or delta == 0:
        return

    target_index = normal_row_indexes[-1]
    target_row = rows[target_index]
    if not isinstance(target_row.get("line_total"), Decimal):
        return
    target_row["line_total"] = _money(target_row["line_total"] + delta)
    _update_row_unit_price_from_total(target_row)
    metadata = _line_item_metadata_dict(target_row)
    metadata["rieder_rounding_delta"] = str(delta)
    metadata["rieder_adjusted_line_total"] = str(target_row["line_total"])
    if isinstance(target_row.get("unit_price"), Decimal):
        metadata["rieder_adjusted_unit_price"] = str(target_row["unit_price"])
    _set_line_item_metadata(target_row, metadata)


def _apply_entholzer_pricing_to_line_item_rows(
    rows: list[dict[str, Any]],
    amount_line_rows: list[dict[str, Any]] | None,
) -> None:
    _apply_sequential_pricing_to_line_item_rows(
        rows,
        amount_line_rows,
        provider_key="entholzer",
        target_subtotal=_last_adjusted_subtotal(amount_line_rows),
    )


def _is_rekord_vomp_non_discounted_delivery_row(row: dict[str, Any], metadata: dict[str, Any]) -> bool:
    line_total = row.get("line_total")
    if not isinstance(line_total, Decimal):
        return False
    if line_total > Decimal("300.01"):
        return False
    text = " ".join(
        str(value or "")
        for value in (
            row.get("position_no"),
            row.get("lv_pos"),
            row.get("description_short"),
            row.get("description_long"),
            metadata.get("line_total_raw"),
        )
    ).lower()
    return "xx-lief-baus" in text or ("lieferung" in text and "baustelle" in text)


def _apply_rekord_vomp_pricing_to_line_item_rows(
    rows: list[dict[str, Any]],
    amount_line_rows: list[dict[str, Any]] | None,
) -> None:
    _apply_sequential_pricing_to_line_item_rows(
        rows,
        amount_line_rows,
        provider_key="rekord_vomp",
        skip_row=_is_rekord_vomp_non_discounted_delivery_row,
        target_subtotal=_net_total_from_amount_lines(amount_line_rows),
    )


def _apply_koch_pricing_to_line_item_rows(
    rows: list[dict[str, Any]],
    amount_line_rows: list[dict[str, Any]] | None,
) -> None:
    _apply_sequential_pricing_to_line_item_rows(
        rows,
        amount_line_rows,
        provider_key="koch",
        target_subtotal=_net_total_from_amount_lines(amount_line_rows),
    )


def _apply_schachermayer_line_pricing_to_line_item_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        quantity = row.get("quantity")
        unit_price = row.get("unit_price")
        line_total = row.get("line_total")
        if not all(isinstance(value, Decimal) for value in (quantity, unit_price, line_total)):
            continue
        if quantity == 0:
            continue
        original_line_total = _money(unit_price * quantity)
        if original_line_total <= 0 or abs(original_line_total - line_total) <= Decimal("0.01"):
            continue

        adjusted_unit_price = _money(line_total / quantity)
        discount_percent = _money((Decimal("1") - (line_total / original_line_total)) * Decimal("100"))
        metadata = _line_item_metadata_dict(row)
        metadata["pricing_adjustment_source"] = "schachermayer_line_discount"
        metadata["pricing_adjustments_applied"] = True
        metadata["pricing_original_line_total"] = str(original_line_total)
        metadata["pricing_original_unit_price"] = str(unit_price)
        metadata["pricing_adjusted_line_total"] = str(line_total)
        metadata["pricing_adjusted_unit_price"] = str(adjusted_unit_price)
        metadata["pricing_operations"] = [
            {
                "line_type": "discount",
                "percent": str(discount_percent),
                "label_raw": "Schachermayer Positionsrabatt laut Nettobetrag",
            }
        ]
        metadata["schachermayer_pricing_applied"] = True
        metadata["schachermayer_original_line_total"] = str(original_line_total)
        metadata["schachermayer_original_unit_price"] = str(unit_price)
        metadata["schachermayer_adjusted_line_total"] = str(line_total)
        metadata["schachermayer_adjusted_unit_price"] = str(adjusted_unit_price)
        metadata["schachermayer_pricing_operations"] = metadata["pricing_operations"]
        row["unit_price"] = adjusted_unit_price
        _set_line_item_metadata(row, metadata)


SCHLOTTERER_AMOUNT_PATTERN = r"[0-9]{1,3}(?:[ .][0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2}"
SCHLOTTERER_DISCOUNT_GROUP_RE = re.compile(
    rf"^\s*(?P<label>[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9 /+._-]*?)\s+"
    rf"(?P<base>{SCHLOTTERER_AMOUNT_PATTERN})\s+"
    rf"(?P<percent>[0-9]+(?:[,.][0-9]+)?)\s*%\s+"
    rf"(?P<amount>-?\s*{SCHLOTTERER_AMOUNT_PATTERN})",
    flags=re.IGNORECASE,
)


def _is_schlotterer_unrebated_row(row: dict[str, Any], metadata: dict[str, Any]) -> bool:
    description = " ".join(str(row.get(key) or "") for key in ("position_no", "lv_pos", "description_short")).lower()
    return (
        "auftragsinfo" in description
        or "verpackungsbeitrag" in description
        or "web erfasser" in description
        or metadata.get("pricing_source") == "schlotterer_unrebated"
    )


def _schlotterer_normalized_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _schlotterer_group_key(label: str) -> str:
    normalized = _schlotterer_normalized_key(label)
    if "motor" in normalized:
        return "motor"
    if normalized.startswith("igi ") or normalized == "igi":
        return "igi"
    if "zubehoer" in normalized or "panzer" in normalized:
        return "panzer"
    return normalized


def _parse_schlotterer_discount_groups(extracted_text: str | None) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    seen: set[tuple[str, Decimal, Decimal]] = set()
    if not extracted_text:
        return groups

    for raw_line in extracted_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line.replace("\u00a0", " ")).strip()
        if not line:
            continue
        match = SCHLOTTERER_DISCOUNT_GROUP_RE.match(line)
        if not match:
            continue
        label = match.group("label").strip()
        label_key = _schlotterer_normalized_key(label)
        if label_key.startswith(("rabatte", "summe", "gesamt", "mwst", "unrabattierte")):
            continue
        base_amount = _parse_eu_decimal(match.group("base"))
        percent = _parse_eu_decimal(match.group("percent"))
        discount_amount = _parse_eu_decimal(match.group("amount"))
        if base_amount is None or percent is None or discount_amount is None:
            continue
        discount_amount = -abs(discount_amount)
        key = (label_key, base_amount, percent)
        if key in seen:
            continue
        seen.add(key)
        groups.append(
            {
                "label": label,
                "key": _schlotterer_group_key(label),
                "base_amount": base_amount,
                "percent": percent,
                "discount_amount": discount_amount,
            }
        )
    return groups


def _schlotterer_row_group_key(row: dict[str, Any], groups_by_key: dict[str, dict[str, Any]]) -> str | None:
    description = _schlotterer_normalized_key(row.get("description_short"))
    if not description:
        return None
    if "igi" in groups_by_key and description.startswith("igi"):
        return "igi"
    if "panzer" in groups_by_key and ("panzer" in description or "artikel mit bearbeitung" in description):
        return "panzer"

    for key in groups_by_key:
        if key in {"motor", "igi", "panzer"}:
            continue
        if description == key or description.startswith(f"{key} ") or key.startswith(f"{description} "):
            return key
    return None


def _schlotterer_component_total(
    components: Any,
    quantity: Decimal | None,
    *,
    group_key: str,
) -> Decimal:
    if not isinstance(components, list):
        return Decimal("0.00")
    multiplier = quantity if isinstance(quantity, Decimal) and quantity != 0 else Decimal("1")
    total = Decimal("0.00")
    for component in components:
        if not isinstance(component, dict):
            continue
        label = _schlotterer_normalized_key(component.get("label"))
        if group_key == "motor" and "motor" not in label:
            continue
        amount = _parse_eu_decimal(str(component.get("amount_raw") or ""))
        if amount is None:
            continue
        total += amount * multiplier
    return _money(total)


def _schlotterer_operation_metadata(groups: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "line_type": "discount",
            "percent": str(group["percent"]),
            "label_raw": group["label"],
        }
        for group in groups
    ]


def _restore_line_item_snapshots(rows: list[dict[str, Any]], snapshots: list[dict[str, Any]]) -> None:
    for index, snapshot in enumerate(snapshots):
        rows[index].clear()
        rows[index].update(snapshot)


def _apply_schlotterer_discount_group_pricing_to_line_item_rows(
    rows: list[dict[str, Any]],
    amount_line_rows: list[dict[str, Any]] | None,
    extracted_text: str | None,
) -> bool:
    discount_groups = _parse_schlotterer_discount_groups(extracted_text)
    if not discount_groups:
        return False

    groups_by_key = {group["key"]: group for group in discount_groups}
    target_net = _net_total_from_amount_lines(amount_line_rows)
    snapshots = [dict(row) for row in rows]
    adjusted_non_alt_indexes: list[int] = []
    operation_metadata = _schlotterer_operation_metadata(discount_groups)

    for index, row in enumerate(rows):
        line_total = row.get("line_total")
        if not isinstance(line_total, Decimal):
            continue
        metadata = _line_item_metadata_dict(row)
        if _is_schlotterer_unrebated_row(row, metadata):
            continue

        original_line_total = line_total
        original_unit_price = row.get("unit_price")
        quantity = row.get("quantity") if isinstance(row.get("quantity"), Decimal) else None
        remaining_total = original_line_total
        allocations: list[dict[str, Any]] = []
        row_group_key = _schlotterer_row_group_key(row, groups_by_key)
        row_group = groups_by_key.get(row_group_key or "")

        motor_group = groups_by_key.get("motor")
        if motor_group and row_group:
            motor_total = _schlotterer_component_total(
                metadata.get("schlotterer_pricing_components"),
                quantity,
                group_key="motor",
            )
            if motor_total > 0 and motor_total <= remaining_total + Decimal("0.01"):
                remaining_total = _money(remaining_total - motor_total)
                allocations.append({"group": motor_group, "original_total": motor_total})

        if row_group and remaining_total > 0:
            allocations.append({"group": row_group, "original_total": remaining_total})

        if not allocations:
            continue

        adjusted_line_total = Decimal("0.00")
        allocation_metadata: list[dict[str, str]] = []
        for allocation in allocations:
            group = allocation["group"]
            original_total = allocation["original_total"]
            factor = Decimal("1") - (group["percent"] / Decimal("100"))
            adjusted_total = _money(original_total * factor)
            adjusted_line_total += adjusted_total
            allocation_metadata.append(
                {
                    "label": group["label"],
                    "percent": str(group["percent"]),
                    "original_total": str(original_total),
                    "adjusted_total": str(adjusted_total),
                }
            )
        adjusted_line_total = _money(adjusted_line_total)
        row["line_total"] = adjusted_line_total
        _update_row_unit_price_from_total(row)

        metadata["pricing_adjustment_source"] = "schlotterer_discount_groups"
        metadata["pricing_adjustments_applied"] = True
        metadata["pricing_original_line_total"] = str(original_line_total)
        if isinstance(original_unit_price, Decimal):
            metadata["pricing_original_unit_price"] = str(original_unit_price)
        metadata["pricing_adjusted_line_total"] = str(adjusted_line_total)
        if isinstance(row.get("unit_price"), Decimal):
            metadata["pricing_adjusted_unit_price"] = str(row["unit_price"])
        metadata["pricing_operations"] = operation_metadata
        metadata["schlotterer_pricing_applied"] = True
        metadata["schlotterer_pricing_mode"] = "discount_groups"
        metadata["schlotterer_discount_allocations"] = allocation_metadata
        metadata["schlotterer_original_line_total"] = str(original_line_total)
        if isinstance(original_unit_price, Decimal):
            metadata["schlotterer_original_unit_price"] = str(original_unit_price)
        metadata["schlotterer_adjusted_line_total"] = str(adjusted_line_total)
        if isinstance(row.get("unit_price"), Decimal):
            metadata["schlotterer_adjusted_unit_price"] = str(row["unit_price"])
        metadata["schlotterer_pricing_operations"] = operation_metadata
        _set_line_item_metadata(row, metadata)

        if not bool(row.get("is_alternative")):
            adjusted_non_alt_indexes.append(index)

    if not adjusted_non_alt_indexes:
        _restore_line_item_snapshots(rows, snapshots)
        return False

    if target_net is None:
        return True

    current_non_alt_total = sum(
        (row.get("line_total") for row in rows if not bool(row.get("is_alternative")) and isinstance(row.get("line_total"), Decimal)),
        Decimal("0.00"),
    )
    delta = _money(target_net - current_non_alt_total)
    if abs(delta) > Decimal("0.25"):
        _restore_line_item_snapshots(rows, snapshots)
        return False
    if delta == 0:
        return True

    target_row = rows[adjusted_non_alt_indexes[-1]]
    if not isinstance(target_row.get("line_total"), Decimal):
        _restore_line_item_snapshots(rows, snapshots)
        return False
    target_row["line_total"] = _money(target_row["line_total"] + delta)
    _update_row_unit_price_from_total(target_row)
    metadata = _line_item_metadata_dict(target_row)
    metadata["pricing_rounding_delta"] = str(delta)
    metadata["schlotterer_rounding_delta"] = str(delta)
    metadata["pricing_adjusted_line_total"] = str(target_row["line_total"])
    if isinstance(target_row.get("unit_price"), Decimal):
        metadata["pricing_adjusted_unit_price"] = str(target_row["unit_price"])
    metadata["schlotterer_adjusted_line_total"] = str(target_row["line_total"])
    if isinstance(target_row.get("unit_price"), Decimal):
        metadata["schlotterer_adjusted_unit_price"] = str(target_row["unit_price"])
    _set_line_item_metadata(target_row, metadata)
    return True


def _apply_schlotterer_pricing_to_line_item_rows(
    rows: list[dict[str, Any]],
    amount_line_rows: list[dict[str, Any]] | None,
    extracted_text: str | None = None,
) -> None:
    if _apply_schlotterer_discount_group_pricing_to_line_item_rows(rows, amount_line_rows, extracted_text):
        return

    target_net = _net_total_from_amount_lines(amount_line_rows)
    if target_net is None:
        return

    eligible_non_alt_indexes: list[int] = []
    eligible_all_indexes: list[int] = []
    unrebated_non_alt_total = Decimal("0.00")
    for index, row in enumerate(rows):
        line_total = row.get("line_total")
        if not isinstance(line_total, Decimal):
            continue
        metadata = _line_item_metadata_dict(row)
        is_unrebated = _is_schlotterer_unrebated_row(row, metadata)
        if is_unrebated and not bool(row.get("is_alternative")):
            unrebated_non_alt_total += line_total
            continue
        if is_unrebated:
            continue
        eligible_all_indexes.append(index)
        if not bool(row.get("is_alternative")):
            eligible_non_alt_indexes.append(index)

    eligible_non_alt_total = sum((rows[index].get("line_total") for index in eligible_non_alt_indexes), Decimal("0.00"))
    if eligible_non_alt_total <= 0:
        return
    adjusted_eligible_target = target_net - unrebated_non_alt_total
    if adjusted_eligible_target <= 0:
        return
    if abs((eligible_non_alt_total + unrebated_non_alt_total) - target_net) <= Decimal("0.01"):
        return

    factor = adjusted_eligible_target / eligible_non_alt_total
    if factor <= 0 or factor > Decimal("2"):
        return

    discount_percent = _money((Decimal("1") - factor) * Decimal("100"))
    operation_metadata = [
        {
            "line_type": "discount" if discount_percent >= 0 else "surcharge",
            "percent": str(abs(discount_percent)),
            "label_raw": "Schlotterer Effektivrabatt aus Nettosumme",
        }
    ]

    rounding_candidates: list[int] = []
    for index in eligible_all_indexes:
        row = rows[index]
        line_total = row.get("line_total")
        if not isinstance(line_total, Decimal):
            continue
        original_line_total = line_total
        original_unit_price = row.get("unit_price")
        adjusted_line_total = _money(original_line_total * factor)
        row["line_total"] = adjusted_line_total
        _update_row_unit_price_from_total(row)

        metadata = _line_item_metadata_dict(row)
        metadata["pricing_adjustment_source"] = "schlotterer_effective_discount"
        metadata["pricing_adjustments_applied"] = True
        metadata["pricing_original_line_total"] = str(original_line_total)
        if isinstance(original_unit_price, Decimal):
            metadata["pricing_original_unit_price"] = str(original_unit_price)
        metadata["pricing_adjusted_line_total"] = str(adjusted_line_total)
        if isinstance(row.get("unit_price"), Decimal):
            metadata["pricing_adjusted_unit_price"] = str(row["unit_price"])
        metadata["pricing_operations"] = operation_metadata
        metadata["schlotterer_pricing_applied"] = True
        metadata["schlotterer_original_line_total"] = str(original_line_total)
        if isinstance(original_unit_price, Decimal):
            metadata["schlotterer_original_unit_price"] = str(original_unit_price)
        metadata["schlotterer_adjusted_line_total"] = str(adjusted_line_total)
        if isinstance(row.get("unit_price"), Decimal):
            metadata["schlotterer_adjusted_unit_price"] = str(row["unit_price"])
        metadata["schlotterer_pricing_operations"] = operation_metadata
        metadata["schlotterer_effective_discount_factor"] = str(factor.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
        _set_line_item_metadata(row, metadata)

        if index in eligible_non_alt_indexes:
            rounding_candidates.append(index)

    adjusted_non_alt_total = sum((rows[index].get("line_total") for index in eligible_non_alt_indexes), Decimal("0.00"))
    delta = _money(adjusted_eligible_target - adjusted_non_alt_total)
    if not rounding_candidates or delta == 0 or abs(delta) > Decimal("0.10"):
        return

    target_row = rows[rounding_candidates[-1]]
    if not isinstance(target_row.get("line_total"), Decimal):
        return
    target_row["line_total"] = _money(target_row["line_total"] + delta)
    _update_row_unit_price_from_total(target_row)
    metadata = _line_item_metadata_dict(target_row)
    metadata["pricing_rounding_delta"] = str(delta)
    metadata["schlotterer_rounding_delta"] = str(delta)
    metadata["pricing_adjusted_line_total"] = str(target_row["line_total"])
    if isinstance(target_row.get("unit_price"), Decimal):
        metadata["pricing_adjusted_unit_price"] = str(target_row["unit_price"])
    metadata["schlotterer_adjusted_line_total"] = str(target_row["line_total"])
    if isinstance(target_row.get("unit_price"), Decimal):
        metadata["schlotterer_adjusted_unit_price"] = str(target_row["unit_price"])
    _set_line_item_metadata(target_row, metadata)


def _apply_schuchter_pricing_to_line_item_rows(
    rows: list[dict[str, Any]],
    amount_line_rows: list[dict[str, Any]] | None,
) -> None:
    _apply_sequential_pricing_to_line_item_rows(
        rows,
        amount_line_rows,
        provider_key="schuchter",
        target_subtotal=_net_total_from_amount_lines(amount_line_rows),
    )


def _prepend_room_label_to_long_text(rows: list[dict[str, Any]], template: str) -> None:
    """Prepend the SCHUCHTER room label (``lv_pos``, e.g. ``EG: T1 Bad/SZ``) as
    the first line of ``description_long``.

    Done once here, at parse time, so the *stored* long text is the single
    source of truth: the app, the Postgres export and the VenDoc export all show
    the same text (no UI-vs-export divergence). Scoped to SCHUCHTER, where the
    room label is wanted; ``lv_pos`` means different things for other suppliers
    (LV codes, section headers), so they are left untouched. No-op when
    ``lv_pos`` is empty or already leads the long text.
    """
    if template != "schuchter":
        return
    for row in rows:
        label = (row.get("lv_pos") or "").strip()
        if not label:
            continue
        long_text = row.get("description_long") or ""
        first_line = long_text.split("\n", 1)[0].strip()
        if first_line == label:
            continue
        # Re-apply the templates' 8000-char description_long cap: the label is
        # prepended after the template already truncated, so cap again here.
        row["description_long"] = (f"{label}\n{long_text}" if long_text else label)[:8000]


def _build_line_item_rows(
    extracted_text: str,
    template: str,
    source_path: Path | None = None,
    amount_line_rows: list[dict[str, Any]] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    items = extract_line_items(extracted_text, template)
    if template == "rieder":
        delivery_item = extract_rieder_delivery_charge_item(extracted_text, items)
        if delivery_item:
            items.append(delivery_item)
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
        if "image_auto_match_allowed" in item:
            metadata["image_auto_match_allowed"] = bool(item.get("image_auto_match_allowed"))
        if "alternative_append_at_end" in item:
            metadata["alternative_append_at_end"] = bool(item.get("alternative_append_at_end"))
        alternative_parent_position_no = _clean_optional_str(item.get("alternative_parent_position_no"))
        if alternative_parent_position_no:
            metadata["alternative_parent_position_no"] = alternative_parent_position_no
        alternative_parent_lv_pos = _clean_optional_str(item.get("alternative_parent_lv_pos"))
        if alternative_parent_lv_pos:
            metadata["alternative_parent_lv_pos"] = alternative_parent_lv_pos
        for key in (
            "pricing_source",
            "manual_price_editable",
            "delivery_charge_detected",
            "delivery_charge_default_amount",
            "delivery_charge_printed_total",
            "delivery_charge_fallback",
            "delivery_charge_lines",
            "schlotterer_pricing_components",
        ):
            if key in item:
                metadata[key] = item.get(key)
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
    if template == "rieder":
        _apply_rieder_pricing_to_line_item_rows(rows, amount_line_rows)
    elif template == "entholzer":
        _apply_entholzer_pricing_to_line_item_rows(rows, amount_line_rows)
    elif template == "rekord_vomp":
        _apply_rekord_vomp_pricing_to_line_item_rows(rows, amount_line_rows)
    elif template == "koch":
        _apply_koch_pricing_to_line_item_rows(rows, amount_line_rows)
    elif template == "schachermayer":
        _apply_schachermayer_line_pricing_to_line_item_rows(rows)
    elif template == "schlotterer":
        _apply_schlotterer_pricing_to_line_item_rows(rows, amount_line_rows, extracted_text=extracted_text)
    elif template == "schuchter":
        _apply_schuchter_pricing_to_line_item_rows(rows, amount_line_rows)
    _prepend_room_label_to_long_text(rows, template)
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
    _bootstrap_auth_user()


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
def assign_line_item_image(document_id: int, line_item_id: int, payload: AssignImageRequest, request: Request):
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

    _audit(
        request,
        "line_item_image_assigned",
        document_id=document_id,
        line_item_id=line_item_id,
        details={"image_id": payload.image_id},
    )
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
def crop_line_item_image(document_id: int, line_item_id: int, payload: PdfCropImageRequest, request: Request):
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

    _audit(
        request,
        "line_item_image_cropped",
        document_id=document_id,
        line_item_id=line_item_id,
        details={"image_id": image_id, "page_ref": payload.page_ref, "width": width, "height": height},
    )
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


@app.post("/documents/{document_id}/line-items/{line_item_id}/screen-crop-image")
def crop_line_item_screen_image(document_id: int, line_item_id: int, payload: ScreenCropImageRequest, request: Request):
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

    image_bytes, width, height, original_mime_type = _screen_crop_data_url_to_png(payload)
    metadata = {
        "source": "ui_screen_crop",
        "layout_source": "manual_screen_crop",
        "crop_page_ref": payload.page_ref,
        "original_mime_type": original_mime_type,
        "line_item_id": line_item_id,
        "position_no": line_item.get("position_no"),
        "lv_pos": line_item.get("lv_pos"),
    }

    digest = sha256(image_bytes).hexdigest()
    output_dir = IMAGE_DUMP_DIR / f"document_{document_id}" / "manual_crops"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"manual_screen_crop_line_{line_item_id}_page_{payload.page_ref}_{uuid4().hex[:10]}.png"
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
                "selection_reason": "ui_screen_crop",
                "strategy_requested": "manual_crop",
                "review_checked": True,
                "review_checked_reason": "ui_screen_crop",
            }
        },
    )
    if updated <= 0:
        raise HTTPException(status_code=500, detail="Manual screen crop could not be assigned to the line item.")

    _audit(
        request,
        "line_item_screen_image_cropped",
        document_id=document_id,
        line_item_id=line_item_id,
        details={"image_id": image_id, "page_ref": payload.page_ref, "width": width, "height": height},
    )
    return {
        "ok": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "image_id": image_id,
        "page_ref": payload.page_ref,
        "width": width,
        "height": height,
        "selection_source": "manual_crop",
        "selection_reason": "ui_screen_crop",
        "review_checked": True,
    }


@app.delete("/documents/{document_id}/line-items/{line_item_id}/assign-image")
def clear_line_item_image_assignment(document_id: int, line_item_id: int, request: Request):
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

    _audit(request, "line_item_image_cleared", document_id=document_id, line_item_id=line_item_id)
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
def check_line_item_review(document_id: int, line_item_id: int, request: Request):
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

    _audit(request, "line_item_review_checked", document_id=document_id, line_item_id=line_item_id)
    return {
        "ok": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "review_checked": True,
        "review_checked_reason": "ui_manual_review",
    }


@app.delete("/documents/{document_id}/line-items/{line_item_id}/review-check")
def clear_line_item_review(document_id: int, line_item_id: int, request: Request):
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

    _audit(request, "line_item_review_cleared", document_id=document_id, line_item_id=line_item_id)
    return {
        "ok": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "review_checked": False,
        "review_checked_reason": "ui_review_reset",
    }


@app.patch("/documents/{document_id}/line-items/{line_item_id}")
def update_line_item(
    document_id: int,
    line_item_id: int,
    payload: LineItemUpdateRequest,
    request: Request,
):
    user = _require_user(request)
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Result for document {document_id} not found.")

    line_items_raw = result_data.get("line_items")
    line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []
    line_item = next((item for item in line_items if _to_int_safe(item.get("id")) == line_item_id), None)
    if not line_item:
        raise HTTPException(status_code=404, detail=f"Line item {line_item_id} for document {document_id} not found.")

    updates = _line_item_update_payload(payload)
    changed = _changed_line_item_updates(line_item, updates)
    if not changed:
        return {
            "ok": True,
            "changed": False,
            "document_id": document_id,
            "line_item_id": line_item_id,
            "result": result_data,
        }

    actor_username = str(user.get("username") or "").strip() or None
    updated = update_line_item_fields(
        document_id,
        line_item_id,
        changed,
        actor_username=actor_username,
    )
    if not updated:
        raise HTTPException(status_code=500, detail="Line item could not be updated.")

    old_values = {field: _json_safe(line_item.get(field)) for field in changed}
    new_values = {field: _json_safe(value) for field, value in changed.items()}
    _audit(
        request,
        "line_item_fields_changed",
        document_id=document_id,
        line_item_id=line_item_id,
        details={
            "changed_fields": sorted(changed.keys()),
            "old_values": old_values,
            "new_values": new_values,
            "approval_reset": True,
        },
    )

    refreshed_result = get_document_result(document_id) or result_data
    return {
        "ok": True,
        "changed": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "line_item": _json_safe(updated),
        "result": refreshed_result,
    }


@app.put("/documents/{document_id}/line-items/{line_item_id}/alternative-append-at-end")
def set_line_item_alternative_append_at_end(
    document_id: int,
    line_item_id: int,
    payload: LineItemAlternativeAppendRequest,
    request: Request,
):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Result for document {document_id} not found.")

    line_items_raw = result_data.get("line_items")
    line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []
    line_item = next((item for item in line_items if _to_int_safe(item.get("id")) == line_item_id), None)
    if not line_item:
        raise HTTPException(status_code=404, detail=f"Line item {line_item_id} for document {document_id} not found.")
    if not bool(line_item.get("is_alternative")):
        raise HTTPException(status_code=400, detail="Only alternative line items can be appended at the end.")

    updated = update_line_item_alternative_append_mode(
        document_id,
        line_item_id,
        append_at_end=payload.append_at_end,
    )
    if updated <= 0:
        raise HTTPException(status_code=500, detail="Alternative append override could not be persisted.")

    _audit(
        request,
        "line_item_alternative_append_changed",
        document_id=document_id,
        line_item_id=line_item_id,
        details={"append_at_end": bool(payload.append_at_end)},
    )
    return {
        "ok": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "alternative_append_at_end": bool(payload.append_at_end),
    }


@app.put("/documents/{document_id}/line-items/{line_item_id}/embedded-alternatives/{alternative_index}/alternative-append-at-end")
def set_line_item_embedded_alternative_append_at_end(
    document_id: int,
    line_item_id: int,
    alternative_index: int,
    payload: LineItemAlternativeAppendRequest,
    request: Request,
):
    if alternative_index < 1:
        raise HTTPException(status_code=400, detail="Embedded alternative index must be at least 1.")

    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Result for document {document_id} not found.")

    line_items_raw = result_data.get("line_items")
    line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []
    line_item = next((item for item in line_items if _to_int_safe(item.get("id")) == line_item_id), None)
    if not line_item:
        raise HTTPException(status_code=404, detail=f"Line item {line_item_id} for document {document_id} not found.")
    if bool(line_item.get("is_alternative")):
        raise HTTPException(status_code=400, detail="Embedded alternatives can only be changed on a main line item.")

    embedded_lines = [
        line
        for line in str(line_item.get("description_long") or "").splitlines()
        if re.match(r"^\s*Alternativ(?:e|position)?\s*:", line, flags=re.IGNORECASE)
    ]
    if alternative_index > len(embedded_lines):
        raise HTTPException(
            status_code=404,
            detail=f"Embedded alternative {alternative_index} for line item {line_item_id} not found.",
        )

    updated = update_line_item_embedded_alternative_append_mode(
        document_id,
        line_item_id,
        alternative_index=alternative_index,
        append_at_end=payload.append_at_end,
    )
    if updated <= 0:
        raise HTTPException(status_code=500, detail="Embedded alternative append override could not be persisted.")

    _audit(
        request,
        "line_item_embedded_alternative_append_changed",
        document_id=document_id,
        line_item_id=line_item_id,
        details={
            "alternative_index": int(alternative_index),
            "append_at_end": bool(payload.append_at_end),
        },
    )
    return {
        "ok": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "alternative_index": int(alternative_index),
        "alternative_append_at_end": bool(payload.append_at_end),
    }


@app.put("/documents/{document_id}/line-items/{line_item_id}/line-total-override")
def set_line_item_line_total_override(
    document_id: int,
    line_item_id: int,
    payload: LineItemLineTotalOverrideRequest,
    request: Request,
):
    result_data = get_document_result(document_id)
    if not result_data:
        raise HTTPException(status_code=404, detail=f"Result for document {document_id} not found.")

    line_items_raw = result_data.get("line_items")
    line_items = list(line_items_raw) if isinstance(line_items_raw, list) else []
    line_item = next((item for item in line_items if _to_int_safe(item.get("id")) == line_item_id), None)
    if not line_item:
        raise HTTPException(status_code=404, detail=f"Line item {line_item_id} for document {document_id} not found.")

    metadata_raw = line_item.get("metadata_json")
    metadata: dict[str, Any] = {}
    if isinstance(metadata_raw, dict):
        metadata = metadata_raw
    elif isinstance(metadata_raw, str) and metadata_raw.strip():
        try:
            parsed = json.loads(metadata_raw)
            metadata = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            metadata = {}

    editable = bool(metadata.get("manual_price_editable")) or metadata.get("pricing_source") == "rieder_delivery_block"
    if not editable:
        raise HTTPException(status_code=400, detail="Line item price is not manually editable.")

    line_total = payload.line_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    updated = update_line_item_line_total_override(document_id, line_item_id, line_total=line_total)
    if not updated:
        raise HTTPException(status_code=500, detail="Line item price override could not be persisted.")

    _audit(
        request,
        "line_item_price_override_changed",
        document_id=document_id,
        line_item_id=line_item_id,
        details={"line_total": str(line_total)},
    )
    return {
        "ok": True,
        "document_id": document_id,
        "line_item_id": line_item_id,
        "unit_price": str(updated.get("unit_price")) if updated.get("unit_price") is not None else None,
        "line_total": str(updated.get("line_total")) if updated.get("line_total") is not None else None,
    }


@app.post("/documents/{document_id}/approval")
def approve_document(document_id: int, payload: DocumentApprovalRequest, request: Request):
    user = _require_user(request)
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
        reviewed_by=str(user.get("username") or user.get("display_name") or "").strip(),
        approval_note=_clean_optional_str(payload.note),
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    _audit(request, "document_approved", document_id=document_id, details={"note_present": bool(_clean_optional_str(payload.note))})
    return {
        "ok": True,
        "document_id": document_id,
        "approval_status": updated["approval_status"],
        "reviewed_by": updated.get("reviewed_by"),
        "reviewed_at": updated.get("reviewed_at"),
        "approval_note": updated.get("approval_note"),
    }


@app.delete("/documents/{document_id}/approval")
def reset_document_approval(document_id: int, request: Request):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    updated = update_document_approval_state(document_id, approval_status="pending")
    if not updated:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    _audit(request, "document_approval_reset", document_id=document_id)
    return {
        "ok": True,
        "document_id": document_id,
        "approval_status": updated["approval_status"],
        "reviewed_by": updated.get("reviewed_by"),
        "reviewed_at": updated.get("reviewed_at"),
        "approval_note": updated.get("approval_note"),
    }


@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
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

    _audit(
        request,
        "document_uploaded",
        document_id=int(doc_row["id"]),
        details={"filename": file.filename, "file_size_bytes": size_bytes},
    )
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
def reset_document(document_id: int, request: Request, delete_logs: bool = Query(default=True)):
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

    _audit(
        request,
        "document_reset",
        document_id=document_id,
        details={
            "delete_logs": delete_logs,
            "deleted_amount_lines": reset_info["deleted_amount_lines"],
            "deleted_line_items": reset_info["deleted_line_items"],
            "deleted_images": reset_info["deleted_images"],
            "deleted_log_files": removed_files,
        },
    )
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


@app.get("/vendoc/customers")
def vendoc_customers():
    config = config_from_env()
    if not config:
        raise HTTPException(status_code=503, detail="VenDoc MSSQL ist nicht konfiguriert.")
    try:
        return list_customer_options(config, view_name=customer_view_from_env())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Kundenliste aus SRTemp konnte nicht geladen werden: {exc}") from exc


@app.put("/documents/{document_id}/vendoc-customer")
def set_document_vendoc_customer(document_id: int, payload: DocumentVendocCustomerRequest, request: Request):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    has_selection = any(
        [
            _clean_optional_str(payload.contact_oid),
            _clean_optional_str(payload.customer_number),
            _clean_optional_str(payload.uid_number),
            _clean_optional_str(payload.display_name),
        ]
    )
    updated = update_document_vendoc_customer(
        document_id,
        customer_name=_clean_optional_str(payload.display_name) if has_selection else None,
        vendoc_customer_oid=_clean_optional_str(payload.contact_oid) if has_selection else None,
        vendoc_customer_number=_clean_optional_str(payload.customer_number) if has_selection else None,
        vendoc_customer_uid_number=_clean_optional_str(payload.uid_number) if has_selection else None,
        vendoc_customer_inactive=bool(payload.inactive) if has_selection and payload.inactive is not None else (False if has_selection else None),
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    _audit(
        request,
        "vendoc_customer_changed",
        document_id=document_id,
        details={
            "has_selection": has_selection,
            "customer_number": updated.get("vendoc_customer_number"),
            "display_name": updated.get("customer_name"),
        },
    )
    return {
        "ok": True,
        "document_id": document_id,
        "customer_name": updated.get("customer_name"),
        "vendoc_customer_oid": updated.get("vendoc_customer_oid"),
        "vendoc_customer_number": updated.get("vendoc_customer_number"),
        "vendoc_customer_uid_number": updated.get("vendoc_customer_uid_number"),
        "vendoc_customer_inactive": updated.get("vendoc_customer_inactive"),
        "updated_at": updated.get("updated_at"),
    }


@app.put("/documents/{document_id}/alternative-position-mode")
def set_document_alternative_position_mode(
    document_id: int,
    payload: DocumentAlternativePositionModeRequest,
    request: Request,
):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    updated = update_document_alternative_position_mode(document_id, mode=payload.mode)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    _audit(
        request,
        "alternative_position_mode_changed",
        document_id=document_id,
        details={"mode": updated.get("alternative_position_mode")},
    )
    return {
        "ok": True,
        "document_id": document_id,
        "alternative_position_mode": updated.get("alternative_position_mode"),
        "updated_at": updated.get("updated_at"),
    }


@app.get("/documents/{document_id}/offer-candidates")
def get_document_offer_candidates(document_id: int):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    candidates = list_offer_candidates(
        supplier_name=document.get("supplier_name"),
        exclude_document_id=document_id,
    )
    items = [
        {
            "id": candidate.get("id"),
            "document_number": candidate.get("document_number"),
            "document_date": candidate.get("document_date"),
            "project_ref": candidate.get("project_ref"),
            "status": candidate.get("status"),
        }
        for candidate in candidates
    ]
    return _json_safe(
        {
            "ok": True,
            "supplier_name": document.get("supplier_name"),
            "linked_offer_document_id": document.get("linked_offer_document_id"),
            "items": items,
            "count": len(items),
        }
    )


@app.put("/documents/{document_id}/linked-offer")
def set_document_linked_offer_endpoint(
    document_id: int,
    payload: DocumentLinkedOfferRequest,
    request: Request,
):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")

    linked_id = payload.linked_offer_document_id
    offer_reference: str | None = None
    if linked_id is not None:
        offer = get_document(linked_id)
        if not offer:
            raise HTTPException(status_code=400, detail=f"Angebot {linked_id} nicht gefunden.")
        if str(offer.get("document_type") or "").strip().lower() != "angebot":
            raise HTTPException(
                status_code=400,
                detail="Das ausgewaehlte Dokument ist kein Angebot.",
            )
        ab_supplier = (document.get("supplier_name") or "").strip().lower()
        offer_supplier = (offer.get("supplier_name") or "").strip().lower()
        if ab_supplier and offer_supplier and ab_supplier != offer_supplier:
            raise HTTPException(
                status_code=400,
                detail="Das Angebot gehoert zu einem anderen Lieferanten.",
            )
        offer_reference = offer.get("document_number")

    updated = set_document_linked_offer(
        document_id,
        linked_offer_document_id=linked_id,
        offer_reference=offer_reference,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    _audit(
        request,
        "linked_offer_changed",
        document_id=document_id,
        details={"linked_offer_document_id": updated.get("linked_offer_document_id")},
    )
    return {
        "ok": True,
        "document_id": document_id,
        "offer_reference": updated.get("offer_reference"),
        "linked_offer_document_id": updated.get("linked_offer_document_id"),
        "updated_at": updated.get("updated_at"),
    }


@app.put("/documents/{document_id}/pricing-adjustments")
def set_document_pricing_adjustments(
    document_id: int,
    payload: DocumentPricingAdjustmentsRequest,
    request: Request,
):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    previous = bool(document.get("apply_pricing_adjustments", True))
    updated = update_document_pricing_adjustments(
        document_id,
        apply_pricing_adjustments=payload.apply_pricing_adjustments,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    _audit(
        request,
        "pricing_adjustments_changed",
        document_id=document_id,
        details={
            "previous_apply_pricing_adjustments": previous,
            "apply_pricing_adjustments": bool(updated.get("apply_pricing_adjustments")),
        },
    )
    return {
        "ok": True,
        "document_id": document_id,
        "apply_pricing_adjustments": bool(updated.get("apply_pricing_adjustments")),
        "updated_at": updated.get("updated_at"),
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
    package_request: DocumentPackageRequest,
    http_request: Request,
    dry_run: bool = Query(default=True),
    include_sql: bool = Query(default=False),
):
    result_data = _load_package_result(package_request)
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
        _audit(
            http_request,
            "vendoc_package_dry_run",
            document_id=document_id,
            details={"status": status, "include_sql": include_sql, "error_count": len(errors)},
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
        _audit(
            http_request,
            "vendoc_package_live_export_failed",
            document_id=document_id,
            details={"error_count": len(live_errors), "message": error_text},
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
        _audit(
            http_request,
            "vendoc_package_live_export_failed",
            document_id=document_id,
            details={"error_count": 1, "message": live_error["message"]},
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
        _audit(
            http_request,
            "vendoc_package_live_export_failed",
            document_id=document_id,
            details={"error_count": 1, "message": live_error["message"]},
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
    _audit(
        http_request,
        "vendoc_package_live_exported",
        document_id=document_id,
        details={"job_id": job.get("id"), "position_count": vendoc_payload.get("summary", {}).get("position_count")},
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
    request: Request,
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
        _audit(
            request,
            "vendoc_dry_run",
            document_id=document_id,
            details={"status": status, "include_sql": include_sql, "error_count": len(errors)},
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
        _audit(
            request,
            "vendoc_live_export_failed",
            document_id=document_id,
            details={"error_count": len(live_errors), "message": error_text},
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
        _audit(
            request,
            "vendoc_live_export_failed",
            document_id=document_id,
            details={"error_count": 1, "message": live_error["message"]},
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
        _audit(
            request,
            "vendoc_live_export_failed",
            document_id=document_id,
            details={"error_count": 1, "message": live_error["message"]},
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
        _audit(
            request,
            "vendoc_live_export_failed",
            document_id=document_id,
            details={"error_count": 1, "message": live_error["message"]},
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
    _audit(
        request,
        "vendoc_live_exported",
        document_id=document_id,
        details={"job_id": job.get("id"), "position_count": vendoc_payload.get("summary", {}).get("position_count")},
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


@app.get("/vendoc/import-state/{document_id}")
def vendoc_import_state(document_id: int):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    return get_vendoc_import_state(document_id)


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
    request: Request,
    process_mode: str | None = Query(default="parser_only"),
    use_ai: bool = Query(default=False, alias="use_llm", include_in_schema=False),
    ai_override: bool = Query(default=False, alias="llm_override", include_in_schema=False),
):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found.")
    if str(document.get("status") or "").strip().lower() == "processing":
        raise HTTPException(status_code=409, detail="Dokument wird bereits verarbeitet.")

    source_path = Path(document["source_file"])
    if not source_path.exists():
        update_document_status(document_id, status="failed", error_message=f"File missing: {source_path}")
        _audit(request, "document_processing_failed", document_id=document_id, details={"message": f"File missing: {source_path}"})
        raise HTTPException(status_code=400, detail=f"Source file does not exist: {source_path}")

    requested_mode = _resolve_process_mode(process_mode=process_mode, use_ai=use_ai, ai_override=ai_override)
    update_document_status(document_id, status="processing", error_message=None)
    update_document_approval_state(document_id, approval_status="pending")
    _audit(request, "document_processing_started", document_id=document_id, details={"mode": requested_mode})

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
            template=template,
        )
        line_item_rows = _build_line_item_rows(
            extracted_text,
            template,
            source_path=source_path,
            amount_line_rows=amount_line_rows,
        )

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
        _audit(request, "document_processing_failed", document_id=document_id, details={"mode": requested_mode, "message": "HTTP error"})
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
        _audit(request, "document_processing_failed", document_id=document_id, details={"mode": requested_mode, "message": str(exc)[:1000]})
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc

    _audit(
        request,
        "document_processed",
        document_id=document_id,
        details={"mode": requested_mode, "line_item_count": len(line_item_rows), "image_count": len(image_rows)},
    )
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
