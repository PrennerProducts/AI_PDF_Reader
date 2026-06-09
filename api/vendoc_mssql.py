from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any


HEADER_TABLE = "dbo.vendoc_import_headers"
POSITION_TABLE = "dbo.vendoc_import_positions"
ODBC_DRIVER = "ODBC Driver 18 for SQL Server"
DEFAULT_CUSTOMER_VIEW = "dbo.Kundendaten"

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
    "customer_id",
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
    "text_only_rtf",
    "unit_price",
    "page_ref",
    "image_long_text_rtf",
    "image_only_rtf",
    "image_hex",
    "image_is_primary",
    "created_at",
    "article_no",
    "discount_1",
    "discount_2",
    "vat_type",
    "unity",
    "main_line_item_id",
]

REQUIRED_HEADER_COLUMNS = {
    "external_document_id",
    "source_document_id",
}

REQUIRED_POSITION_COLUMNS = {
    "external_line_item_id",
    "external_document_id",
    "source_line_item_id",
}

COLUMN_ALIASES: dict[str, dict[str, list[str]]] = {
    HEADER_TABLE: {
        "is_alternate": ["is_alternative"],
    },
    POSITION_TABLE: {
        "is_alternative": ["is_alternate"],
        "text_only_rtf": ["long_text_rtf", "text_rtf"],
        "image_only_rtf": ["image_rtf", "img_rtf"],
    },
}

DATE_COLUMNS: dict[str, set[str]] = {
    HEADER_TABLE: {"document_date"},
    POSITION_TABLE: set(),
}

DATETIME_COLUMNS: dict[str, set[str]] = {
    HEADER_TABLE: {"created_at"},
    POSITION_TABLE: {"created_at"},
}


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


def _to_str(value: Any) -> str | None:
    return _clean(value)


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


def customer_view_from_env() -> str:
    return _clean(os.getenv("VENDOC_MSSQL_CUSTOMER_VIEW")) or DEFAULT_CUSTOMER_VIEW


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


def _validated_sql_object_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Missing MSSQL object name.")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,2}", text):
        raise ValueError(f"Unsupported MSSQL object name: {value!r}")
    return text


def list_customer_options(config: VendocMssqlConfig, *, view_name: str | None = None) -> dict[str, Any]:
    status = driver_status()
    if not status["available"]:
        raise RuntimeError(status["error"] or f"{ODBC_DRIVER} not installed")

    resolved_view = _validated_sql_object_name(view_name or customer_view_from_env())
    query = f"""
        SELECT
            KontaktOid,
            Inaktiv,
            UIDNummer,
            Kundennummer,
            Anzeigename
        FROM {resolved_view}
        ORDER BY
            CASE WHEN COALESCE(Inaktiv, 0) = 0 THEN 0 ELSE 1 END,
            Anzeigename,
            Kundennummer;
    """

    items: list[dict[str, Any]] = []
    with _connect(config) as conn:
        cursor = conn.cursor()
        rows = cursor.execute(query).fetchall()
        for row in rows:
            contact_oid = _to_str(row[0])
            inactive_raw = row[1]
            uid_number = _to_str(row[2])
            customer_number = _to_str(row[3])
            display_name = _to_str(row[4])
            items.append(
                {
                    "contact_oid": contact_oid,
                    "inactive": bool(inactive_raw) if inactive_raw is not None else False,
                    "uid_number": uid_number,
                    "customer_number": customer_number,
                    "display_name": display_name,
                }
            )

    return {
        "view_name": resolved_view,
        "items": items,
        "count": len(items),
    }


def _mssql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime):
            text = value.strftime("%Y-%m-%dT%H:%M:%S")
            return f"CAST('{text}' AS datetime2)"
        text = value.strftime("%Y%m%d")
        return f"CONVERT(datetime, '{text}', 112)"
    text = str(value).replace("'", "''")
    return f"N'{text}'"


def _insert_statement(table: str, columns: list[str], row: dict[str, Any]) -> str:
    values = ", ".join(_mssql_literal(row.get(column)) for column in columns)
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({values});"


def _split_table_name(table: str) -> tuple[str, str]:
    if "." in table:
        schema, name = table.split(".", 1)
        return schema, name
    return "dbo", table


def _fetch_table_columns(cursor: Any, table: str) -> list[str]:
    schema, name = _split_table_name(table)
    rows = cursor.execute(
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION;
        """,
        schema,
        name,
    ).fetchall()
    return [str(row[0]) for row in rows]


def _resolve_column_bindings(
    table: str,
    desired_columns: list[str],
    required_columns: set[str],
    available_columns: list[str] | None = None,
) -> list[tuple[str, str]]:
    if available_columns is None:
        return [(column, column) for column in desired_columns]

    available_lookup = {column.lower(): column for column in available_columns}
    aliases = COLUMN_ALIASES.get(table, {})
    bindings: list[tuple[str, str]] = []
    missing_required: list[str] = []

    for source_column in desired_columns:
        candidates = [source_column, *aliases.get(source_column, [])]
        actual_column = next((available_lookup.get(candidate.lower()) for candidate in candidates if available_lookup.get(candidate.lower())), None)
        if actual_column:
            bindings.append((actual_column, source_column))
            continue
        if source_column in required_columns:
            missing_required.append(source_column)

    if missing_required:
        raise RuntimeError(
            f"Missing required MSSQL columns in {table}: {', '.join(sorted(missing_required))}"
        )

    return bindings


def _resolve_table_bindings(cursor: Any | None = None) -> dict[str, list[tuple[str, str]]]:
    if cursor is None:
        return {
            HEADER_TABLE: _resolve_column_bindings(HEADER_TABLE, HEADER_COLUMNS, REQUIRED_HEADER_COLUMNS),
            POSITION_TABLE: _resolve_column_bindings(POSITION_TABLE, POSITION_COLUMNS, REQUIRED_POSITION_COLUMNS),
        }

    header_columns = _fetch_table_columns(cursor, HEADER_TABLE)
    position_columns = _fetch_table_columns(cursor, POSITION_TABLE)
    return {
        HEADER_TABLE: _resolve_column_bindings(HEADER_TABLE, HEADER_COLUMNS, REQUIRED_HEADER_COLUMNS, header_columns),
        POSITION_TABLE: _resolve_column_bindings(POSITION_TABLE, POSITION_COLUMNS, REQUIRED_POSITION_COLUMNS, position_columns),
    }


def _binding_target_columns(bindings: list[tuple[str, str]]) -> list[str]:
    return [target_column for target_column, _source_column in bindings]


def _parse_date_like(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime_like(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _coerce_value_for_column(table: str, target_column: str, value: Any) -> Any:
    if target_column in DATE_COLUMNS.get(table, set()):
        parsed = _parse_date_like(value)
        return parsed if parsed is not None else value
    if target_column in DATETIME_COLUMNS.get(table, set()):
        parsed = _parse_datetime_like(value)
        return parsed if parsed is not None else value
    return value


def _binding_row_values(table: str, row: dict[str, Any], bindings: list[tuple[str, str]]) -> list[Any]:
    return [_coerce_value_for_column(table, target_column, row.get(source_column)) for target_column, source_column in bindings]


def _insert_statement_with_bindings(table: str, bindings: list[tuple[str, str]], row: dict[str, Any]) -> str:
    values = ", ".join(
        _mssql_literal(_coerce_value_for_column(table, target_column, row.get(source_column)))
        for target_column, source_column in bindings
    )
    return f"INSERT INTO {table} ({', '.join(_binding_target_columns(bindings))}) VALUES ({values});"


def build_srtemp_insert_script(
    vendoc_payload: dict[str, Any],
    config: VendocMssqlConfig | None = None,
) -> str:
    header = vendoc_payload.get("header") if isinstance(vendoc_payload.get("header"), dict) else {}
    positions = vendoc_payload.get("positions") if isinstance(vendoc_payload.get("positions"), list) else []
    external_document_id = header.get("external_document_id") or vendoc_payload.get("external_document_id")
    if not external_document_id:
        raise ValueError("Missing external_document_id for SRTemp export.")

    bindings = _resolve_table_bindings()
    if config is not None:
        status = driver_status()
        if status["available"]:
            try:
                with _connect(config) as conn:
                    bindings = _resolve_table_bindings(conn.cursor())
            except Exception:
                bindings = _resolve_table_bindings()

    lines = [
        "SET XACT_ABORT ON;",
        "BEGIN TRANSACTION;",
        "",
        f"DELETE FROM {POSITION_TABLE} WHERE external_document_id = {_mssql_literal(external_document_id)};",
        f"DELETE FROM {HEADER_TABLE} WHERE external_document_id = {_mssql_literal(external_document_id)};",
        "",
        _insert_statement_with_bindings(HEADER_TABLE, bindings[HEADER_TABLE], header),
    ]
    for position in positions:
        if isinstance(position, dict):
            lines.append(_insert_statement_with_bindings(POSITION_TABLE, bindings[POSITION_TABLE], position))
    lines.extend(["", "COMMIT TRANSACTION;"])
    return "\n".join(lines) + "\n"


def build_srtemp_export_preview(
    vendoc_payload: dict[str, Any],
    config: VendocMssqlConfig | None = None,
) -> dict[str, Any]:
    bindings = _resolve_table_bindings()
    if config is not None:
        status = driver_status()
        if status["available"]:
            try:
                with _connect(config) as conn:
                    bindings = _resolve_table_bindings(conn.cursor())
            except Exception:
                bindings = _resolve_table_bindings()

    return {
        "target_tables": {
            "header": HEADER_TABLE,
            "positions": POSITION_TABLE,
        },
        "header_columns": _binding_target_columns(bindings[HEADER_TABLE]),
        "position_columns": _binding_target_columns(bindings[POSITION_TABLE]),
        "sql_script": build_srtemp_insert_script(vendoc_payload, config=config),
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
            bindings = _resolve_table_bindings(cursor)
            cursor.execute(f"DELETE FROM {POSITION_TABLE} WHERE external_document_id = ?;", external_document_id)
            cursor.execute(f"DELETE FROM {HEADER_TABLE} WHERE external_document_id = ?;", external_document_id)
            cursor.execute(
                _insert_sql_with_placeholders(HEADER_TABLE, _binding_target_columns(bindings[HEADER_TABLE])),
                _binding_row_values(HEADER_TABLE, header, bindings[HEADER_TABLE]),
            )
            insert_position_sql = _insert_sql_with_placeholders(
                POSITION_TABLE,
                _binding_target_columns(bindings[POSITION_TABLE]),
            )
            for position in positions:
                if isinstance(position, dict):
                    cursor.execute(insert_position_sql, _binding_row_values(POSITION_TABLE, position, bindings[POSITION_TABLE]))
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
