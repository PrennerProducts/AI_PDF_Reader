import base64
import csv
import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def _to_json(data: dict[str, Any]) -> str:
    return json.dumps(json_safe(data), ensure_ascii=False, indent=2)


def _to_csv(data: dict[str, Any]) -> str:
    safe_data = json_safe(data)
    document = safe_data.get("document", {})
    line_items = safe_data.get("line_items", [])

    fieldnames = [
        "document_id",
        "document_type",
        "offer_reference",
        "document_number",
        "document_date",
        "supplier_name",
        "project_ref",
        "currency",
        "approval_status",
        "reviewed_by",
        "reviewed_at",
        "approval_note",
        "document_notes",
        "position_no",
        "lv_pos",
        "is_alternative",
        "quantity",
        "unit",
        "width_mm",
        "height_mm",
        "page_ref",
        "description_short",
        "unit_price",
        "line_total",
        "confidence",
        "image_count",
        "image_ids",
        "metadata_json",
    ]

    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for item in line_items:
        metadata = item.get("metadata_json")
        if isinstance(metadata, (dict, list)):
            metadata = json.dumps(metadata, ensure_ascii=False)
        writer.writerow(
            {
                "document_id": document.get("id"),
                "document_type": document.get("document_type"),
                "offer_reference": document.get("offer_reference"),
                "document_number": document.get("document_number"),
                "document_date": document.get("document_date"),
                "supplier_name": document.get("supplier_name"),
                "project_ref": document.get("project_ref"),
                "currency": document.get("currency"),
                "approval_status": document.get("approval_status"),
                "reviewed_by": document.get("reviewed_by"),
                "reviewed_at": document.get("reviewed_at"),
                "approval_note": document.get("approval_note"),
                "document_notes": document.get("document_notes"),
                "position_no": item.get("position_no"),
                "lv_pos": item.get("lv_pos"),
                "is_alternative": item.get("is_alternative"),
                "quantity": item.get("quantity"),
                "unit": item.get("unit"),
                "width_mm": item.get("width_mm"),
                "height_mm": item.get("height_mm"),
                "page_ref": item.get("page_ref"),
                "description_short": item.get("description_short"),
                "unit_price": item.get("unit_price"),
                "line_total": item.get("line_total"),
                "confidence": item.get("confidence"),
                "image_count": item.get("image_count"),
                "image_ids": ",".join(str(val) for val in item.get("image_ids", []) or []),
                "metadata_json": metadata,
            }
        )

    return output.getvalue()


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _insert_sql(table: str, cols: list[str], row: dict[str, Any]) -> str:
    values = ", ".join(_sql_literal(row.get(col)) for col in cols)
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({values});"


def _to_sql(data: dict[str, Any]) -> str:
    safe_data = json_safe(data)
    document = safe_data.get("document", {})
    amount_lines = safe_data.get("amount_lines", [])
    line_items = safe_data.get("line_items", [])
    images = safe_data.get("images", [])
    document_id = document.get("id")

    if document_id is None:
        raise ValueError("Missing document.id for SQL export.")

    lines: list[str] = ["BEGIN;"]

    document_cols = [
        "id",
        "source_file",
        "original_filename",
        "file_size_bytes",
        "content_type",
        "supplier_name",
        "document_type",
        "offer_reference",
        "document_number",
        "document_date",
        "project_ref",
        "currency",
        "net_total",
        "vat_total",
        "gross_total",
        "parse_confidence",
        "approval_status",
        "reviewed_by",
        "reviewed_at",
        "approval_note",
        "document_notes",
        "status",
        "error_message",
        "raw_text_path",
        "created_at",
        "updated_at",
    ]
    values = ", ".join(_sql_literal(document.get(col)) for col in document_cols)
    update_cols = [col for col in document_cols if col != "id"]
    update_stmt = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_cols)
    lines.append(
        "INSERT INTO documents "
        f"({', '.join(document_cols)}) VALUES ({values}) "
        f"ON CONFLICT (id) DO UPDATE SET {update_stmt};"
    )

    lines.append(f"DELETE FROM document_amount_lines WHERE document_id = {_sql_literal(document_id)};")
    amount_cols = ["document_id", "line_type", "label_raw", "percent", "base_amount", "amount", "sort_order"]
    for row in amount_lines:
        payload = dict(row)
        payload["document_id"] = document_id
        lines.append(_insert_sql("document_amount_lines", amount_cols, payload))

    lines.append(f"DELETE FROM line_items WHERE document_id = {_sql_literal(document_id)};")
    item_cols = [
        "document_id",
        "position_no",
        "lv_pos",
        "is_alternative",
        "quantity",
        "unit",
        "width_mm",
        "height_mm",
        "description_short",
        "description_long",
        "unit_price",
        "line_total",
        "page_ref",
        "confidence",
        "metadata_json",
    ]
    for row in line_items:
        payload = dict(row)
        payload["document_id"] = document_id
        metadata = payload.get("metadata_json")
        if isinstance(metadata, (dict, list)):
            payload["metadata_json"] = json.dumps(metadata, ensure_ascii=False)
        row_values: list[str] = []
        for col in item_cols:
            if col == "metadata_json":
                row_values.append(f"{_sql_literal(payload.get(col))}::jsonb")
            else:
                row_values.append(_sql_literal(payload.get(col)))
        lines.append(f"INSERT INTO line_items ({', '.join(item_cols)}) VALUES ({', '.join(row_values)});")

    lines.append(f"DELETE FROM document_images WHERE document_id = {_sql_literal(document_id)};")
    image_cols = [
        "document_id",
        "page_ref",
        "image_index",
        "mime_type",
        "storage_path",
        "sha256",
        "width",
        "height",
        "bytes_size",
        "metadata_json",
        "created_at",
    ]
    for row in images:
        payload = dict(row)
        payload["document_id"] = document_id
        metadata = payload.get("metadata_json")
        if isinstance(metadata, (dict, list)):
            payload["metadata_json"] = json.dumps(metadata, ensure_ascii=False)
        row_values: list[str] = []
        for col in image_cols:
            if col == "metadata_json":
                row_values.append(f"{_sql_literal(payload.get(col))}::jsonb")
            else:
                row_values.append(_sql_literal(payload.get(col)))
        lines.append(f"INSERT INTO document_images ({', '.join(image_cols)}) VALUES ({', '.join(row_values)});")

    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def _with_images_base64(data: dict[str, Any]) -> dict[str, Any]:
    enriched = deepcopy(json_safe(data))
    for image in enriched.get("images", []):
        storage_path = image.get("storage_path")
        if not storage_path:
            image["content_base64"] = None
            image["base64_error"] = "missing_storage_path"
            continue
        path = Path(storage_path)
        if not path.exists() or not path.is_file():
            image["content_base64"] = None
            image["base64_error"] = "file_not_found"
            continue
        payload = path.read_bytes()
        image["content_base64"] = base64.b64encode(payload).decode("ascii")
        image["base64_error"] = None
    return enriched


def build_export_content(
    data: dict[str, Any],
    export_format: str,
    *,
    include_images_base64: bool = False,
) -> tuple[str, str, str]:
    normalized = export_format.lower().strip()
    payload = _with_images_base64(data) if include_images_base64 else data
    if normalized == "json":
        return "json", "application/json; charset=utf-8", _to_json(payload)
    if normalized == "csv":
        return "csv", "text/csv; charset=utf-8", _to_csv(payload)
    if normalized == "sql":
        return "sql", "text/plain; charset=utf-8", _to_sql(payload)
    raise ValueError(f"Unsupported export format: {export_format}")
