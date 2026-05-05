from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any


HEADER_TABLE = "dbo.vendoc_import_headers"
POSITION_TABLE = "dbo.vendoc_import_positions"
ODBC_DRIVER = "ODBC Driver 18 for SQL Server"

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


@dataclass(frozen=True)
class VendocMssqlConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    encrypt: bool = True
    trust_server_certificate: bool = False
    timeout_seconds: int = 30
    driver: str = ODBC_DRIVER


def _truthy(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "ja", "y", "on"}


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_env(value: Any, *, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def config_from_env() -> VendocMssqlConfig | None:
    host = _clean(os.getenv("VENDOC_MSSQL_HOST"))
    user = _clean(os.getenv("VENDOC_MSSQL_USER"))
    password = _clean(os.getenv("VENDOC_MSSQL_PASSWORD"))
    if not host or not user or not password:
        return None
    return VendocMssqlConfig(
        host=host,
        port=_int_env(os.getenv("VENDOC_MSSQL_PORT"), default=1433),
        database=_clean(os.getenv("VENDOC_MSSQL_DATABASE")) or "SRTemp",
        user=user,
        password=password,
        encrypt=_truthy(os.getenv("VENDOC_MSSQL_ENCRYPT"), default=True),
        trust_server_certificate=_truthy(os.getenv("VENDOC_MSSQL_TRUST_SERVER_CERTIFICATE"), default=False),
        timeout_seconds=_int_env(os.getenv("VENDOC_MSSQL_TIMEOUT_SECONDS"), default=30),
        driver=_clean(os.getenv("VENDOC_MSSQL_DRIVER")) or ODBC_DRIVER,
    )


def driver_status() -> dict[str, Any]:
    try:
        import pyodbc  # type: ignore
    except Exception as exc:
        return {
            "available": False,
            "driver": ODBC_DRIVER,
            "installed_drivers": [],
            "error": str(exc),
        }
    drivers = list(pyodbc.drivers())
    return {
        "available": ODBC_DRIVER in drivers,
        "driver": ODBC_DRIVER,
        "installed_drivers": drivers,
        "error": None if ODBC_DRIVER in drivers else f"{ODBC_DRIVER} not installed",
    }


def _connection_string(config: VendocMssqlConfig, *, database: str | None = None) -> str:
    encrypt = "yes" if config.encrypt else "no"
    trust = "yes" if config.trust_server_certificate else "no"
    return (
        f"DRIVER={{{config.driver}}};"
        f"SERVER={config.host},{config.port};"
        f"DATABASE={database or config.database};"
        f"UID={config.user};"
        f"PWD={config.password};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust};"
        f"Connection Timeout={config.timeout_seconds};"
    )


def _connect(config: VendocMssqlConfig):
    import pyodbc  # type: ignore

    return pyodbc.connect(_connection_string(config), autocommit=False, timeout=config.timeout_seconds)


def check_connection(config: VendocMssqlConfig) -> dict[str, Any]:
    status = driver_status()
    if not status["available"]:
        return {
            "ok": False,
            "status": "driver_missing",
            "message": status["error"],
            "driver": status,
        }
    try:
        with _connect(config) as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT DB_NAME();").fetchone()
            database_name = row[0] if row else None
    except Exception as exc:
        return {
            "ok": False,
            "status": "connection_failed",
            "message": str(exc),
            "driver": status,
        }
    return {
        "ok": True,
        "status": "connected",
        "message": "MSSQL connection ok.",
        "database": database_name,
        "driver": status,
    }


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


def _insert_sql_with_placeholders(table: str, columns: list[str]) -> str:
    placeholders = ", ".join("?" for _ in columns)
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders});"


def _row_values(row: dict[str, Any], columns: list[str]) -> list[Any]:
    return [row.get(column) for column in columns]


def write_srtemp_payload(vendoc_payload: dict[str, Any], config: VendocMssqlConfig) -> dict[str, Any]:
    header = vendoc_payload.get("header") if isinstance(vendoc_payload.get("header"), dict) else {}
    positions = vendoc_payload.get("positions") if isinstance(vendoc_payload.get("positions"), list) else []
    external_document_id = header.get("external_document_id") or vendoc_payload.get("external_document_id")
    if not external_document_id:
        raise ValueError("Missing external_document_id for SRTemp export.")

    status = driver_status()
    if not status["available"]:
        raise RuntimeError(status["error"] or f"{ODBC_DRIVER} not installed")

    with _connect(config) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(f"DELETE FROM {POSITION_TABLE} WHERE external_document_id = ?;", external_document_id)
            cursor.execute(f"DELETE FROM {HEADER_TABLE} WHERE external_document_id = ?;", external_document_id)
            cursor.execute(_insert_sql_with_placeholders(HEADER_TABLE, HEADER_COLUMNS), _row_values(header, HEADER_COLUMNS))
            insert_position_sql = _insert_sql_with_placeholders(POSITION_TABLE, POSITION_COLUMNS)
            for position in positions:
                if isinstance(position, dict):
                    cursor.execute(insert_position_sql, _row_values(position, POSITION_COLUMNS))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "ok": True,
        "target_tables": {
            "header": HEADER_TABLE,
            "positions": POSITION_TABLE,
        },
        "external_document_id": str(external_document_id),
        "position_count": len([position for position in positions if isinstance(position, dict)]),
    }
