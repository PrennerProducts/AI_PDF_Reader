import base64
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5


VENDOC_NAMESPACE = UUID("8f0f8c50-0f58-45d8-b8e5-83a0f7e79a11")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "ja", "y"}


def _date_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return _to_str(value)


def external_document_id(document_id: Any) -> str:
    source = _to_str(document_id)
    if not source:
        raise ValueError("Missing document id for VenDoc export.")
    return str(uuid5(VENDOC_NAMESPACE, f"document:{source}"))


def external_line_item_id(document_id: Any, line_item: dict[str, Any], fallback_index: int) -> str:
    source_id = _to_str(line_item.get("id"))
    if not source_id:
        source_id = f"idx:{fallback_index}:pos:{_to_str(line_item.get('position_no')) or ''}"
    return str(uuid5(VENDOC_NAMESPACE, f"document:{document_id}:line-item:{source_id}"))


def _metadata(line_item: dict[str, Any]) -> dict[str, Any]:
    metadata = line_item.get("metadata_json")
    return metadata if isinstance(metadata, dict) else {}


def _primary_image_id(line_item: dict[str, Any]) -> int | None:
    for key in ("image_ids_primary", "image_ids"):
        raw = line_item.get(key)
        if not isinstance(raw, list):
            continue
        for value in raw:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
    return None


def _image_filename(document_id: Any, line_item: dict[str, Any], image: dict[str, Any]) -> str:
    position_no = _to_str(line_item.get("position_no")) or _to_str(line_item.get("id")) or "position"
    image_id = _to_str(image.get("id")) or "image"
    suffix = Path(_to_str(image.get("storage_path")) or "").suffix.lower()
    if not suffix:
        mime_type = _to_str(image.get("mime_type")) or ""
        suffix = ".jpg" if "jpeg" in mime_type or "jpg" in mime_type else ".png"
    safe_position = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in position_no)
    return f"document_{document_id}_position_{safe_position}_image_{image_id}{suffix}"


def _image_payload(
    *,
    document_id: Any,
    line_item: dict[str, Any],
    images_by_id: dict[int, dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    image_id = _primary_image_id(line_item)
    if image_id is None:
        return {
            "image_mime_type": None,
            "image_filename": None,
            "image_base64": None,
            "image_is_primary": False,
        }

    image = images_by_id.get(image_id)
    if not image:
        warnings.append(
            {
                "code": "primary_image_missing",
                "message": f"Primary image {image_id} is referenced by a line item but is missing from result images.",
                "line_item_id": line_item.get("id"),
                "position_no": line_item.get("position_no"),
                "image_id": image_id,
            }
        )
        return {
            "image_mime_type": None,
            "image_filename": None,
            "image_base64": None,
            "image_is_primary": False,
        }

    storage_path = _to_str(image.get("storage_path"))
    image_base64 = None
    if storage_path:
        path = Path(storage_path)
        if path.exists() and path.is_file():
            image_base64 = base64.b64encode(path.read_bytes()).decode("ascii")
        else:
            warnings.append(
                {
                    "code": "primary_image_file_missing",
                    "message": f"Primary image file is missing: {storage_path}",
                    "line_item_id": line_item.get("id"),
                    "position_no": line_item.get("position_no"),
                    "image_id": image_id,
                }
            )
    else:
        warnings.append(
            {
                "code": "primary_image_storage_path_missing",
                "message": f"Primary image {image_id} has no storage path.",
                "line_item_id": line_item.get("id"),
                "position_no": line_item.get("position_no"),
                "image_id": image_id,
            }
        )

    return {
        "image_mime_type": _to_str(image.get("mime_type")),
        "image_filename": _image_filename(document_id, line_item, image),
        "image_base64": image_base64,
        "image_is_primary": image_base64 is not None,
    }


def _validate_required(payload: dict[str, Any], required_fields: list[str], scope: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for field in required_fields:
        if payload.get(field) in {None, ""}:
            errors.append(
                {
                    "code": "missing_required_field",
                    "field": field,
                    "message": f"Missing required VenDoc field: {field}",
                    **scope,
                }
            )
    return errors


def build_vendoc_payload(result_data: dict[str, Any], *, exported_at: datetime | None = None) -> dict[str, Any]:
    exported_at = exported_at or _utc_now()
    document = result_data.get("document") if isinstance(result_data.get("document"), dict) else {}
    line_items = result_data.get("line_items") if isinstance(result_data.get("line_items"), list) else []
    images = result_data.get("images") if isinstance(result_data.get("images"), list) else []
    document_id = document.get("id")
    ext_document_id = external_document_id(document_id)

    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    images_by_id: dict[int, dict[str, Any]] = {}
    for image in images:
        if not isinstance(image, dict):
            continue
        try:
            image_id = int(image.get("id"))
        except (TypeError, ValueError):
            continue
        images_by_id[image_id] = image

    non_alternative_items = [item for item in line_items if isinstance(item, dict) and not _to_bool(item.get("is_alternative"))]
    header = {
        "external_document_id": ext_document_id,
        "source_document_id": _to_str(document_id),
        "supplier_name": _to_str(document.get("supplier_name")),
        "supplier_id": None,
        "document_type": _to_str(document.get("document_type")),
        "document_number": _to_str(document.get("document_number")),
        "offer_reference": _to_str(document.get("offer_reference")),
        "document_date": _date_value(document.get("document_date")),
        "project_ref": _to_str(document.get("project_ref")),
        "currency_code": _to_str(document.get("currency")),
        "net_total": _to_float(document.get("net_total")),
        "vat_total": _to_float(document.get("vat_total")),
        "gross_total": _to_float(document.get("gross_total")),
        "is_alternate": bool(line_items and not non_alternative_items),
        "created_at": exported_at.isoformat(),
        "subject": _to_str(document.get("project_ref")),
        "tax_type": None,
    }
    errors.extend(
        _validate_required(
            header,
            ["external_document_id", "source_document_id"],
            {"scope": "header"},
        )
    )

    positions: list[dict[str, Any]] = []
    line_item_ids: dict[str, str] = {}
    for index, raw_item in enumerate(line_items, start=1):
        if not isinstance(raw_item, dict):
            continue
        ext_line_item_id = external_line_item_id(document_id, raw_item, index)
        source_line_item_id = _to_str(raw_item.get("id")) or f"idx:{index}"
        metadata = _metadata(raw_item)
        image_payload = _image_payload(
            document_id=document_id,
            line_item=raw_item,
            images_by_id=images_by_id,
            warnings=warnings,
        )
        line_item_ids[source_line_item_id] = ext_line_item_id
        position = {
            "external_line_item_id": ext_line_item_id,
            "external_document_id": ext_document_id,
            "source_line_item_id": source_line_item_id,
            "position_no": _to_str(raw_item.get("position_no")),
            "item_type": None,
            "is_alternative": _to_bool(raw_item.get("is_alternative")),
            "quantity": _to_float(raw_item.get("quantity")),
            "unit_code": _to_str(raw_item.get("unit")),
            "width_mm": _to_float(raw_item.get("width_mm")),
            "height_mm": _to_float(raw_item.get("height_mm")),
            "description_short": _to_str(raw_item.get("description_short")),
            "description_long": _to_str(raw_item.get("description_long")),
            "unit_price": _to_float(raw_item.get("unit_price")),
            "page_ref": _to_str(raw_item.get("page_ref")),
            **image_payload,
            "created_at": exported_at.isoformat(),
            "article_no": None,
            "discount_1": None,
            "discount_2": None,
            "vat_type": None,
            "unity": None,
            "main_line_item_id": _to_str(metadata.get("referenced_lv_pos")),
        }
        errors.extend(
            _validate_required(
                position,
                ["external_line_item_id", "external_document_id", "source_line_item_id"],
                {
                    "scope": "position",
                    "line_item_id": raw_item.get("id"),
                    "position_no": raw_item.get("position_no"),
                },
            )
        )
        positions.append(position)

    if not positions:
        errors.append(
            {
                "code": "no_positions",
                "scope": "positions",
                "message": "VenDoc export requires at least one line item.",
            }
        )

    return {
        "external_document_id": ext_document_id,
        "exported_at": exported_at.isoformat(),
        "header": header,
        "positions": positions,
        "line_item_external_ids": line_item_ids,
        "warnings": warnings,
        "errors": errors,
        "summary": {
            "position_count": len(positions),
            "warning_count": len(warnings),
            "error_count": len(errors),
            "has_images": any(position.get("image_base64") for position in positions),
        },
    }
