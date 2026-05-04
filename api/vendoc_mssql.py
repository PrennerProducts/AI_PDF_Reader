from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


HEADER_TABLE = "dbo.vendoc_import_headers"
POSITION_TABLE = "dbo.vendoc_import_positions"

HEADER_COLUMNS = [
    "external_document_id",
    "source_document_id",
    "supplier_name",
    "supplier_id",
    "document_type",
    "document_number",
    "offer_reference",
    "document_date",
    "project_ref",
    "currency_code",
    "net_total",
    "vat_total",
    "gross_total",
    "is_alternate",
    "created_at",
    "subject",
    "tax_type",
]

POSITION_COLUMNS = [
    "external_line_item_id",
    "external_document_id",
    "source_line_item_id",
    "position_no",
    "item_type",
    "is_alternative",
    "quantity",
    "unit_code",
    "width_mm",
    "height_mm",
    "description_short",
    "description_long",
    "unit_price",
    "page_ref",
    "image_long_text_rtf",
    "image_is_primary",
    "created_at",
    "article_no",
    "discount_1",
    "discount_2",
    "vat_type",
    "unity",
    "main_line_item_id",
]


def _mssql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (datetime, date)):
        value = value.isoformat()
    text = str(value).replace("'", "''")
    return f"N'{text}'"


def _insert_statement(table: str, columns: list[str], row: dict[str, Any]) -> str:
    values = ", ".join(_mssql_literal(row.get(column)) for column in columns)
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({values});"


def build_srtemp_insert_script(vendoc_payload: dict[str, Any]) -> str:
    header = vendoc_payload.get("header") if isinstance(vendoc_payload.get("header"), dict) else {}
    positions = vendoc_payload.get("positions") if isinstance(vendoc_payload.get("positions"), list) else []
    external_document_id = header.get("external_document_id") or vendoc_payload.get("external_document_id")
    if not external_document_id:
        raise ValueError("Missing external_document_id for SRTemp export.")

    lines = [
        "SET XACT_ABORT ON;",
        "BEGIN TRANSACTION;",
        "",
        f"DELETE FROM {POSITION_TABLE} WHERE external_document_id = {_mssql_literal(external_document_id)};",
        f"DELETE FROM {HEADER_TABLE} WHERE external_document_id = {_mssql_literal(external_document_id)};",
        "",
        _insert_statement(HEADER_TABLE, HEADER_COLUMNS, header),
    ]
    for position in positions:
        if isinstance(position, dict):
            lines.append(_insert_statement(POSITION_TABLE, POSITION_COLUMNS, position))
    lines.extend(["", "COMMIT TRANSACTION;"])
    return "\n".join(lines) + "\n"


def build_srtemp_export_preview(vendoc_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_tables": {
            "header": HEADER_TABLE,
            "positions": POSITION_TABLE,
        },
        "header_columns": HEADER_COLUMNS,
        "position_columns": POSITION_COLUMNS,
        "sql_script": build_srtemp_insert_script(vendoc_payload),
    }
