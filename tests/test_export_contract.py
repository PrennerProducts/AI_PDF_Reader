"""Vertrags-/Freeze-Test fuer alles, was in die Export-DBs geschrieben wird.

Hintergrund
-----------
Auf den Export-Strukturen dieser App triggert ein anderer Entwickler (Dragan)
den Import nach VenDoc. Aenderungen an Spaltennamen, Spalten-Reihenfolge oder
Tabellennamen brechen diesen Import - auch wenn die wertorientierten Tests in
``test_vendoc_exporter.py`` weiter gruen sind.

Dieser Test friert daher die *Struktur* der beiden Export-Ziele ein:

1. VenDoc/MSSQL  -> ``dbo.vendoc_import_headers`` + ``dbo.vendoc_import_positions``
2. Postgres-Export -> ``documents`` / ``line_items`` /
   ``document_amount_lines`` / ``document_images`` (via ``exporter.py``)

Schlaegt ein Assert hier fehl, ist das KEIN Bug im Test: Es bedeutet, dass sich
der Export-Vertrag geaendert hat. Vorgehen dann:

  * Aenderung war beabsichtigt? -> erwartete Liste unten anpassen UND mit Dragan
    abstimmen (siehe ``docs/VENDOC_DRAGAN_HANDOVER.md``), bevor live exportiert
    wird.
  * Aenderung war unbeabsichtigt? -> zurueckrollen.
"""

import re
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from exporter import build_export_content
from vendoc_exporter import build_vendoc_payload
from vendoc_mssql import (
    HEADER_COLUMNS,
    HEADER_TABLE,
    POSITION_COLUMNS,
    POSITION_TABLE,
    build_srtemp_insert_script,
)


# ---------------------------------------------------------------------------
# Eingefrorener Vertrag - bei jeder bewussten Aenderung hier nachziehen.
# ---------------------------------------------------------------------------

EXPECTED_HEADER_TABLE = "dbo.vendoc_import_headers"
EXPECTED_POSITION_TABLE = "dbo.vendoc_import_positions"

EXPECTED_HEADER_COLUMNS = [
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

EXPECTED_POSITION_COLUMNS = [
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
    "purchase_price",
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

# Postgres-Export (exporter.py -> _to_sql). Reihenfolge ist Teil des Vertrags.
EXPECTED_DOCUMENTS_COLUMNS = [
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

EXPECTED_AMOUNT_LINE_COLUMNS = [
    "document_id",
    "line_type",
    "label_raw",
    "percent",
    "base_amount",
    "amount",
    "sort_order",
]

EXPECTED_LINE_ITEM_COLUMNS = [
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

EXPECTED_DOCUMENT_IMAGE_COLUMNS = [
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

# CSV-Export (exporter.py -> _to_csv). Header-Zeile ist Teil des Vertrags.
EXPECTED_CSV_FIELDNAMES = [
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


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def _write_png(path: Path) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (2, 1), (255, 0, 0, 255)).save(output, format="PNG")
    payload = output.getvalue()
    path.write_bytes(payload)
    return payload


def _vendoc_sample(image_path: Path) -> dict:
    return {
        "document": {
            "id": 33,
            "supplier_name": "alu-one Metallbaupartner GmbH",
            "document_type": "angebot",
            "document_number": "C2509283TB",
            "document_date": "2025-11-10",
            "project_ref": "Kinderhotel Felben",
            "currency": "EUR",
            "net_total": "16984.29",
            "vat_total": "3396.86",
            "gross_total": "20381.15",
            "vendoc_customer_number": "K-1001",
        },
        "line_items": [
            {
                "id": 77,
                "position_no": "001",
                "is_alternative": False,
                "quantity": "1.0000",
                "unit": "Stk",
                "width_mm": "860.00",
                "height_mm": "2180.00",
                "page_ref": 3,
                "description_short": "Tuerelement",
                "description_long": "Tuerelement mit Seitenteil",
                "unit_price": "1900.59",
                "line_total": "1900.59",
                "image_ids_primary": [2952],
                "image_ids": [2952],
                "metadata_json": {"referenced_lv_pos": "57.05.21.A"},
            }
        ],
        "images": [
            {
                "id": 2952,
                "page_ref": 3,
                "image_index": 1,
                "mime_type": "image/png",
                "storage_path": str(image_path),
            }
        ],
    }


def _postgres_sample() -> dict:
    return {
        "document": {
            "id": 33,
            "source_file": "/tmp/sample.pdf",
            "supplier_name": "alu-one Metallbaupartner GmbH",
            "document_type": "angebot",
            "document_number": "C2509283TB",
            "currency": "EUR",
        },
        "amount_lines": [
            {"line_type": "net", "label_raw": "Nettosumme", "amount": "16984.29", "sort_order": 1}
        ],
        "line_items": [
            {
                "position_no": "001",
                "is_alternative": False,
                "quantity": "1.0000",
                "unit": "Stk",
                "description_short": "Tuerelement",
                "unit_price": "1900.59",
                "line_total": "1900.59",
                "metadata_json": {"review_checked": True},
            }
        ],
        "images": [
            {
                "id": 1,
                "page_ref": 3,
                "image_index": 1,
                "mime_type": "image/png",
                "storage_path": "/tmp/img.png",
            }
        ],
        "validation": {},
    }


def _insert_columns(sql: str, table: str) -> list[str]:
    """Liest die Spaltenliste des ersten ``INSERT INTO <table> (...)`` aus."""
    pattern = re.compile(rf"INSERT INTO {re.escape(table)} \(([^)]*)\)")
    match = pattern.search(sql)
    assert match, f"Kein INSERT INTO {table} im erzeugten SQL gefunden."
    return [column.strip() for column in match.group(1).split(",")]


# ---------------------------------------------------------------------------
# VenDoc / MSSQL - das Ziel, auf dem Dragans Import triggert
# ---------------------------------------------------------------------------

def test_vendoc_target_tables_are_frozen() -> None:
    assert HEADER_TABLE == EXPECTED_HEADER_TABLE
    assert POSITION_TABLE == EXPECTED_POSITION_TABLE


def test_vendoc_header_columns_are_frozen() -> None:
    assert HEADER_COLUMNS == EXPECTED_HEADER_COLUMNS


def test_vendoc_position_columns_are_frozen() -> None:
    assert POSITION_COLUMNS == EXPECTED_POSITION_COLUMNS


def test_vendoc_payload_header_keys_match_db_columns(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    payload = build_vendoc_payload(_vendoc_sample(image_path))

    # is_alternate ist die DB-Spalte; im Payload heisst das Feld is_alternate
    # (Header), waehrend Positionen is_alternative fuehren.
    assert set(payload["header"].keys()) == set(EXPECTED_HEADER_COLUMNS)


def test_vendoc_payload_position_keys_match_db_columns(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    payload = build_vendoc_payload(_vendoc_sample(image_path))

    assert payload["positions"], "Erwartet mindestens eine Position."
    for position in payload["positions"]:
        assert set(position.keys()) == set(EXPECTED_POSITION_COLUMNS)


def test_vendoc_srtemp_insert_script_uses_frozen_columns(tmp_path: Path) -> None:
    image_path = tmp_path / "position.png"
    _write_png(image_path)
    payload = build_vendoc_payload(_vendoc_sample(image_path))

    script = build_srtemp_insert_script(payload)

    assert _insert_columns(script, EXPECTED_HEADER_TABLE) == EXPECTED_HEADER_COLUMNS
    assert _insert_columns(script, EXPECTED_POSITION_TABLE) == EXPECTED_POSITION_COLUMNS
    # Loeschen-vor-Einfuegen-Reihenfolge: erst Positionen, dann Header.
    assert script.index(f"DELETE FROM {EXPECTED_POSITION_TABLE}") < script.index(
        f"DELETE FROM {EXPECTED_HEADER_TABLE}"
    )


# ---------------------------------------------------------------------------
# Postgres-Export (exporter.py SQL)
# ---------------------------------------------------------------------------

def test_postgres_sql_export_columns_are_frozen() -> None:
    _ext, _media_type, sql = build_export_content(_postgres_sample(), "sql")

    assert _insert_columns(sql, "documents") == EXPECTED_DOCUMENTS_COLUMNS
    assert _insert_columns(sql, "document_amount_lines") == EXPECTED_AMOUNT_LINE_COLUMNS
    assert _insert_columns(sql, "line_items") == EXPECTED_LINE_ITEM_COLUMNS
    assert _insert_columns(sql, "document_images") == EXPECTED_DOCUMENT_IMAGE_COLUMNS


def test_postgres_csv_export_header_is_frozen() -> None:
    _ext, _media_type, csv_content = build_export_content(_postgres_sample(), "csv")

    header_line = csv_content.splitlines()[0]
    assert header_line.split(",") == EXPECTED_CSV_FIELDNAMES
