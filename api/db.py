import os
import json
import re
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from image_assignment import (
    focused_image_ids,
    image_aspect_difference,
    image_layout_sort_key,
    image_within_item_vertical_window,
    item_dimension_ratio,
    is_non_visual_line_item,
    is_viable_auto_assignment_image,
    is_viable_auto_assignment_image_for_item,
    metadata_dict,
    metadata_image_assignment,
    metadata_review_state,
    page_visual_slot_image_id,
    spare_carryover_image_ids,
)
from validation import build_document_validation

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return database_url


def _normalize_username(username: str) -> str:
    return re.sub(r"\s+", " ", str(username or "").strip()).lower()


@contextmanager
def get_db() -> psycopg.Connection:
    conn = psycopg.connect(_database_url(), row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    for part in sql_text.split(";"):
        stmt = part.strip()
        if stmt:
            statements.append(f"{stmt};")
    return statements


def _prefer_next_page_for_aspect_fit(
    item: dict[str, Any],
    *,
    current_image_id: int | None,
    next_page_image_ids: list[int],
    image_by_id: dict[int, dict[str, Any]],
) -> bool:
    if current_image_id is None or not next_page_image_ids:
        return False
    if item_dimension_ratio(item) is None:
        return False

    current_image = image_by_id.get(current_image_id)
    if not current_image:
        return False
    current_diff = image_aspect_difference(item, current_image)
    if current_diff is None:
        return False

    next_diffs = [
        image_aspect_difference(item, image_by_id.get(image_id, {}))
        for image_id in next_page_image_ids
    ]
    next_diffs = [diff for diff in next_diffs if diff is not None]
    if not next_diffs:
        return False

    best_next_diff = min(next_diffs)
    return current_diff >= 1.25 and best_next_diff + 0.35 < current_diff


def apply_migrations() -> list[str]:
    if not MIGRATIONS_DIR.exists():
        return []

    applied_now: list[str] = []
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        existing_rows = conn.execute("SELECT version FROM schema_migrations;").fetchall()
        existing_versions = {row["version"] for row in existing_rows}

        for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = migration_path.name
            if version in existing_versions:
                continue

            migration_sql = migration_path.read_text(encoding="utf-8")
            for statement in _split_sql_statements(migration_sql):
                conn.execute(statement)

            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s);", (version,))
            applied_now.append(version)

    return applied_now


def insert_document(
    *,
    source_file: str,
    original_filename: str,
    file_size_bytes: int,
    content_type: str | None,
) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO documents (
                source_file,
                original_filename,
                file_size_bytes,
                content_type,
                status
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, source_file, original_filename, file_size_bytes, content_type, status, created_at;
            """,
            (source_file, original_filename, file_size_bytes, content_type, "uploaded"),
        ).fetchone()
    return dict(row)


def get_app_user_by_username(username: str) -> dict[str, Any] | None:
    normalized = _normalize_username(username)
    if not normalized:
        return None
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                username,
                username_normalized,
                display_name,
                password_hash,
                is_active,
                created_at,
                updated_at
            FROM app_users
            WHERE username_normalized = %s;
            """,
            (normalized,),
        ).fetchone()
    return dict(row) if row else None


def count_app_users() -> int:
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM app_users;").fetchone()
    return int(row["count"] if row else 0)


def create_app_user(
    *,
    username: str,
    password_hash: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    cleaned_username = str(username or "").strip()
    normalized = _normalize_username(cleaned_username)
    if not normalized:
        raise ValueError("username is required")
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO app_users (
                username,
                username_normalized,
                display_name,
                password_hash
            )
            VALUES (%s, %s, %s, %s)
            RETURNING
                id,
                username,
                username_normalized,
                display_name,
                is_active,
                created_at,
                updated_at;
            """,
            (
                cleaned_username,
                normalized,
                (display_name or "").strip() or cleaned_username,
                password_hash,
            ),
        ).fetchone()
    return dict(row)


def ensure_app_user(
    *,
    username: str,
    password_hash: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    existing = get_app_user_by_username(username)
    if existing:
        return existing
    return create_app_user(username=username, password_hash=password_hash, display_name=display_name)


def create_app_session(
    *,
    user_id: int,
    session_token_hash: str,
    expires_at: datetime,
    ip_address: str | None,
    user_agent: str | None,
) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO app_sessions (
                user_id,
                session_token_hash,
                ip_address,
                user_agent,
                expires_at
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING
                id,
                user_id,
                expires_at,
                created_at,
                last_seen_at;
            """,
            (
                user_id,
                session_token_hash,
                (ip_address or "").strip() or None,
                (user_agent or "").strip()[:500] or None,
                expires_at,
            ),
        ).fetchone()
    return dict(row)


def get_app_session_user(session_token_hash: str) -> dict[str, Any] | None:
    if not session_token_hash:
        return None
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                s.id AS session_id,
                s.expires_at,
                u.id,
                u.username,
                u.display_name,
                u.is_active
            FROM app_sessions s
            JOIN app_users u ON u.id = s.user_id
            WHERE s.session_token_hash = %s
              AND s.revoked_at IS NULL
              AND s.expires_at > NOW()
              AND u.is_active = TRUE;
            """,
            (session_token_hash,),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE app_sessions
                SET last_seen_at = NOW()
                WHERE id = %s;
                """,
                (row["session_id"],),
            )
    return dict(row) if row else None


def revoke_app_session(session_token_hash: str) -> int:
    if not session_token_hash:
        return 0
    with get_db() as conn:
        updated = conn.execute(
            """
            UPDATE app_sessions
            SET revoked_at = NOW()
            WHERE session_token_hash = %s
              AND revoked_at IS NULL;
            """,
            (session_token_hash,),
        ).rowcount or 0
    return int(updated)


def insert_audit_event(
    *,
    action: str,
    actor_user_id: int | None = None,
    actor_username: str | None = None,
    actor_ip: str | None = None,
    document_id: int | None = None,
    line_item_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload_json = json.dumps(details or {}, ensure_ascii=True, default=str)
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO audit_events (
                actor_user_id,
                actor_username,
                actor_ip,
                action,
                document_id,
                line_item_id,
                details_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING
                id,
                actor_user_id,
                actor_username,
                actor_ip,
                action,
                document_id,
                line_item_id,
                details_json,
                created_at;
            """,
            (
                actor_user_id,
                (actor_username or "").strip() or None,
                (actor_ip or "").strip() or None,
                action,
                document_id,
                line_item_id,
                payload_json,
            ),
        ).fetchone()
    return dict(row)


def list_documents(limit: int = 20) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                source_file,
                original_filename,
                file_size_bytes,
                content_type,
                supplier_name,
                customer_name,
                vendoc_customer_number,
                document_type,
                offer_reference,
                linked_offer_document_id,
                document_number,
                document_date,
                project_ref,
                document_notes,
                alternative_position_mode,
                apply_pricing_adjustments,
                approval_status,
                reviewed_by,
                reviewed_at,
                status,
                created_at
            FROM documents
            ORDER BY id DESC
            LIMIT %s;
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_document(document_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                source_file,
                original_filename,
                file_size_bytes,
                content_type,
                supplier_name,
                customer_name,
                vendoc_customer_oid,
                vendoc_customer_number,
                vendoc_customer_uid_number,
                vendoc_customer_inactive,
                document_type,
                offer_reference,
                linked_offer_document_id,
                document_number,
                document_date,
                project_ref,
                currency,
                net_total,
                vat_total,
                gross_total,
                parse_confidence,
                approval_status,
                reviewed_by,
                reviewed_at,
                approval_note,
                document_notes,
                alternative_position_mode,
                apply_pricing_adjustments,
                status,
                error_message,
                raw_text_path,
                created_at,
                updated_at
            FROM documents
            WHERE id = %s;
            """,
            (document_id,),
        ).fetchone()
    return dict(row) if row else None


def update_document_vendoc_customer(
    document_id: int,
    *,
    customer_name: str | None,
    vendoc_customer_oid: str | None,
    vendoc_customer_number: str | None,
    vendoc_customer_uid_number: str | None,
    vendoc_customer_inactive: bool | None,
) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """
            UPDATE documents
            SET
                customer_name = %s,
                vendoc_customer_oid = %s,
                vendoc_customer_number = %s,
                vendoc_customer_uid_number = %s,
                vendoc_customer_inactive = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING
                id,
                customer_name,
                vendoc_customer_oid,
                vendoc_customer_number,
                vendoc_customer_uid_number,
                vendoc_customer_inactive,
                updated_at;
            """,
            (
                (customer_name or "").strip() or None,
                (vendoc_customer_oid or "").strip() or None,
                (vendoc_customer_number or "").strip() or None,
                (vendoc_customer_uid_number or "").strip() or None,
                vendoc_customer_inactive,
                document_id,
            ),
        ).fetchone()
    return dict(row) if row else None


def update_document_alternative_position_mode(document_id: int, *, mode: str) -> dict[str, Any] | None:
    normalized_mode = "append" if str(mode or "").strip().lower() == "append" else "nested"
    with get_db() as conn:
        row = conn.execute(
            """
            UPDATE documents
            SET
                alternative_position_mode = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING
                id,
                alternative_position_mode,
                updated_at;
            """,
            (normalized_mode, document_id),
        ).fetchone()
    return dict(row) if row else None


def update_document_pricing_adjustments(document_id: int, *, apply_pricing_adjustments: bool) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """
            UPDATE documents
            SET
                apply_pricing_adjustments = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING
                id,
                apply_pricing_adjustments,
                updated_at;
            """,
            (bool(apply_pricing_adjustments), document_id),
        ).fetchone()
    return dict(row) if row else None


def update_document_status(
    document_id: int,
    *,
    status: str,
    error_message: str | None = None,
) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """
            UPDATE documents
            SET
                status = %s,
                error_message = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, status, error_message, updated_at;
            """,
            (status, error_message, document_id),
        ).fetchone()
    return dict(row)


def update_document_parse_result(
    document_id: int,
    *,
    supplier_name: str | None,
    document_type: str | None,
    offer_reference: str | None,
    document_number: str | None,
    document_date: date | None,
    project_ref: str | None,
    currency: str | None,
    net_total: Decimal | None,
    vat_total: Decimal | None,
    gross_total: Decimal | None,
    parse_confidence: Decimal | None,
    raw_text_path: str | None,
    status: str,
    document_notes: str | None = None,
) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """
            UPDATE documents
            SET
                supplier_name = %s,
                document_type = %s,
                offer_reference = %s,
                document_number = %s,
                document_date = %s,
                project_ref = %s,
                currency = %s,
                net_total = %s,
                vat_total = %s,
                gross_total = %s,
                parse_confidence = %s,
                raw_text_path = %s,
                document_notes = %s,
                apply_pricing_adjustments = TRUE,
                approval_status = 'pending',
                reviewed_by = NULL,
                reviewed_at = NULL,
                approval_note = NULL,
                status = %s,
                error_message = NULL,
                updated_at = NOW()
            WHERE id = %s
            RETURNING
                id,
                supplier_name,
                document_type,
                offer_reference,
                linked_offer_document_id,
                document_number,
                document_date,
                project_ref,
                currency,
                net_total,
                vat_total,
                gross_total,
                parse_confidence,
                raw_text_path,
                document_notes,
                approval_status,
                reviewed_by,
                reviewed_at,
                approval_note,
                alternative_position_mode,
                apply_pricing_adjustments,
                status,
                updated_at;
            """,
            (
                supplier_name,
                document_type or "angebot",
                offer_reference,
                document_number,
                document_date,
                project_ref,
                currency,
                net_total,
                vat_total,
                gross_total,
                parse_confidence,
                raw_text_path,
                document_notes,
                status,
                document_id,
            ),
        ).fetchone()
    return dict(row)


def _document_reference_key(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]+", "", str(value).upper())
    return normalized or None


def _compact_document_link(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row.get("id"),
        "supplier_name": row.get("supplier_name"),
        "document_type": row.get("document_type"),
        "document_number": row.get("document_number"),
        "offer_reference": row.get("offer_reference"),
        "document_date": row.get("document_date"),
        "project_ref": row.get("project_ref"),
        "status": row.get("status"),
        "approval_status": row.get("approval_status"),
    }


def _find_linked_offer_document_id(
    conn: psycopg.Connection,
    *,
    source_document_id: int,
    supplier_name: str | None,
    offer_reference: str | None,
) -> int | None:
    reference_key = _document_reference_key(offer_reference)
    if reference_key is None:
        return None

    supplier_filter = (supplier_name or "").strip()
    if supplier_filter:
        rows = conn.execute(
            """
            SELECT id, document_number
            FROM documents
            WHERE id <> %s
              AND document_type = 'angebot'
              AND supplier_name = %s
              AND document_number IS NOT NULL
            ORDER BY document_date DESC NULLS LAST, id DESC;
            """,
            (source_document_id, supplier_filter),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, document_number
            FROM documents
            WHERE id <> %s
              AND document_type = 'angebot'
              AND document_number IS NOT NULL
            ORDER BY document_date DESC NULLS LAST, id DESC;
            """,
            (source_document_id,),
        ).fetchall()

    for row in rows:
        if _document_reference_key(row.get("document_number")) == reference_key:
            return int(row["id"])
    return None


def refresh_document_links(document_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        document = conn.execute(
            """
            SELECT id, supplier_name, document_type, offer_reference, document_number
            FROM documents
            WHERE id = %s;
            """,
            (document_id,),
        ).fetchone()
        if not document:
            return None

        document_type = str(document.get("document_type") or "").strip().lower()
        supplier_name = (document.get("supplier_name") or "").strip() or None

        if document_type == "auftragsbestaetigung":
            linked_offer_id = _find_linked_offer_document_id(
                conn,
                source_document_id=document_id,
                supplier_name=supplier_name,
                offer_reference=document.get("offer_reference"),
            )
            conn.execute(
                """
                UPDATE documents
                SET linked_offer_document_id = %s,
                    updated_at = NOW()
                WHERE id = %s;
                """,
                (linked_offer_id, document_id),
            )
        elif document_type == "angebot":
            offer_key = _document_reference_key(document.get("document_number"))
            conn.execute(
                """
                UPDATE documents
                SET linked_offer_document_id = NULL
                WHERE id = %s;
                """,
                (document_id,),
            )
            if offer_key is not None:
                if supplier_name:
                    candidates = conn.execute(
                        """
                        SELECT id, offer_reference
                        FROM documents
                        WHERE document_type = 'auftragsbestaetigung'
                          AND supplier_name = %s
                          AND offer_reference IS NOT NULL;
                        """,
                        (supplier_name,),
                    ).fetchall()
                else:
                    candidates = conn.execute(
                        """
                        SELECT id, offer_reference
                        FROM documents
                        WHERE document_type = 'auftragsbestaetigung'
                          AND offer_reference IS NOT NULL;
                        """
                    ).fetchall()

                matching_ab_ids = [
                    int(row["id"])
                    for row in candidates
                    if _document_reference_key(row.get("offer_reference")) == offer_key
                ]
                if matching_ab_ids:
                    conn.execute(
                        """
                        UPDATE documents
                        SET linked_offer_document_id = %s,
                            updated_at = NOW()
                        WHERE id = ANY(%s::bigint[]);
                        """,
                        (document_id, matching_ab_ids),
                    )

        row = conn.execute(
            """
            SELECT
                id,
                source_file,
                original_filename,
                file_size_bytes,
                content_type,
                supplier_name,
                document_type,
                offer_reference,
                linked_offer_document_id,
                document_number,
                document_date,
                project_ref,
                currency,
                net_total,
                vat_total,
                gross_total,
                parse_confidence,
                approval_status,
                reviewed_by,
                reviewed_at,
                approval_note,
                status,
                error_message,
                raw_text_path,
                created_at,
                updated_at
            FROM documents
            WHERE id = %s;
            """,
            (document_id,),
        ).fetchone()
    return dict(row) if row else None


def get_document_relations(document_id: int) -> dict[str, Any]:
    document = get_document(document_id)
    if not document:
        return {"linked_offer_document": None, "linked_order_confirmations": []}

    with get_db() as conn:
        linked_offer = None
        linked_offer_id = document.get("linked_offer_document_id")
        if linked_offer_id is not None:
            linked_offer = conn.execute(
                """
                SELECT id, supplier_name, document_type, document_number, offer_reference,
                       document_date, project_ref, status, approval_status
                FROM documents
                WHERE id = %s;
                """,
                (linked_offer_id,),
            ).fetchone()

        linked_abs = conn.execute(
            """
            SELECT id, supplier_name, document_type, document_number, offer_reference,
                   document_date, project_ref, status, approval_status
            FROM documents
            WHERE linked_offer_document_id = %s
            ORDER BY document_date ASC NULLS LAST, id ASC;
            """,
            (document_id,),
        ).fetchall()

    return {
        "linked_offer_document": _compact_document_link(dict(linked_offer)) if linked_offer else None,
        "linked_order_confirmations": [_compact_document_link(dict(row)) for row in linked_abs],
    }


def replace_document_amount_lines(document_id: int, rows: list[dict[str, Any]]) -> int:
    with get_db() as conn:
        conn.execute("DELETE FROM document_amount_lines WHERE document_id = %s;", (document_id,))
        if not rows:
            return 0
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO document_amount_lines (
                    document_id,
                    line_type,
                    label_raw,
                    percent,
                    base_amount,
                    amount,
                    sort_order
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                [
                    (
                        document_id,
                        row["line_type"],
                        row["label_raw"],
                        row.get("percent"),
                        row.get("base_amount"),
                        row["amount"],
                        row.get("sort_order", 0),
                    )
                    for row in rows
                ],
            )
    return len(rows)


def replace_line_items(document_id: int, rows: list[dict[str, Any]]) -> int:
    with get_db() as conn:
        conn.execute("DELETE FROM line_items WHERE document_id = %s;", (document_id,))
        if not rows:
            return 0
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO line_items (
                    document_id,
                    position_no,
                    lv_pos,
                    is_alternative,
                    quantity,
                    unit,
                    width_mm,
                    height_mm,
                    description_short,
                    description_long,
                    unit_price,
                    line_total,
                    page_ref,
                    confidence,
                    metadata_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb);
                """,
                [
                    (
                        document_id,
                        row.get("position_no"),
                        row.get("lv_pos"),
                        row.get("is_alternative", False),
                        row.get("quantity"),
                        row.get("unit"),
                        row.get("width_mm"),
                        row.get("height_mm"),
                        row.get("description_short"),
                        row.get("description_long"),
                        row.get("unit_price"),
                        row.get("line_total"),
                        row.get("page_ref"),
                        row.get("confidence"),
                        row.get("metadata_json", "{}"),
                    )
                    for row in rows
                ],
            )
    return len(rows)


def replace_document_images(document_id: int, rows: list[dict[str, Any]]) -> int:
    with get_db() as conn:
        conn.execute("DELETE FROM document_images WHERE document_id = %s;", (document_id,))
        if not rows:
            return 0
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO document_images (
                    document_id,
                    page_ref,
                    image_index,
                    mime_type,
                    storage_path,
                    sha256,
                    width,
                    height,
                    bytes_size,
                    metadata_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb);
                """,
                [
                    (
                        document_id,
                        row["page_ref"],
                        row["image_index"],
                        row.get("mime_type"),
                        row["storage_path"],
                        row.get("sha256"),
                        row.get("width"),
                        row.get("height"),
                        row.get("bytes_size"),
                        json.dumps(row.get("metadata_json", {}), ensure_ascii=True),
                    )
                    for row in rows
                ],
            )
    return len(rows)


def insert_document_image(document_id: int, row: dict[str, Any]) -> dict[str, Any]:
    with get_db() as conn:
        current_index = conn.execute(
            """
            SELECT COALESCE(MAX(image_index), 0) AS max_index
            FROM document_images
            WHERE document_id = %s AND page_ref = %s;
            """,
            (document_id, row["page_ref"]),
        ).fetchone()
        next_index = int((current_index["max_index"] if current_index else 0) or 0) + 1
        inserted = conn.execute(
            """
            INSERT INTO document_images (
                document_id,
                page_ref,
                image_index,
                mime_type,
                storage_path,
                sha256,
                width,
                height,
                bytes_size,
                metadata_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING
                id,
                document_id,
                page_ref,
                image_index,
                mime_type,
                storage_path,
                sha256,
                width,
                height,
                metadata_json,
                bytes_size,
                created_at;
            """,
            (
                document_id,
                row["page_ref"],
                next_index,
                row.get("mime_type"),
                row["storage_path"],
                row.get("sha256"),
                row.get("width"),
                row.get("height"),
                row.get("bytes_size"),
                json.dumps(row.get("metadata_json", {}), ensure_ascii=True),
            ),
        ).fetchone()
        _clear_document_approval_state(conn, document_id)
    return dict(inserted)


def _clear_document_approval_state(conn: psycopg.Connection, document_id: int) -> None:
    conn.execute(
        """
        UPDATE documents
        SET
            approval_status = 'pending',
            reviewed_by = NULL,
            reviewed_at = NULL,
            approval_note = NULL,
            updated_at = NOW()
        WHERE id = %s;
        """,
        (document_id,),
    )


def update_line_item_image_assignments(document_id: int, assignments: dict[int, dict[str, Any]]) -> int:
    if not assignments:
        return 0

    updated_rows = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            for line_item_id, assignment in assignments.items():
                image_ids = assignment.get("image_ids") if isinstance(assignment, dict) else None
                if not isinstance(image_ids, list):
                    continue
                clear_assignment = bool(assignment.get("clear_assignment")) if isinstance(assignment, dict) else False
                unique_ids: list[int] = []
                seen: set[int] = set()
                for value in image_ids:
                    try:
                        parsed = int(value)
                    except (TypeError, ValueError):
                        continue
                    if parsed <= 0 or parsed in seen:
                        continue
                    seen.add(parsed)
                    unique_ids.append(parsed)
                if not unique_ids and not clear_assignment:
                    continue

                source_default = "manual" if clear_assignment else "heuristic"
                source = str(assignment.get("selection_source") or assignment.get("source") or source_default).strip()
                reason = str(assignment.get("selection_reason") or assignment.get("reason") or "").strip()
                strategy = str(assignment.get("strategy_requested") or assignment.get("strategy") or "").strip()
                patch_payload: dict[str, Any] = {
                    "image_assignment_ids": unique_ids,
                    "image_assignment_source": source,
                    "image_assignment_reason": reason,
                    "image_assignment_strategy": strategy or None,
                }
                if "review_checked" in assignment:
                    review_checked = bool(assignment.get("review_checked"))
                    patch_payload["review_checked"] = review_checked
                    patch_payload["review_checked_at"] = (
                        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                        if review_checked
                        else None
                    )
                    patch_payload["review_checked_reason"] = (
                        str(assignment.get("review_checked_reason") or "").strip() or None
                    )
                patch = json.dumps(patch_payload, ensure_ascii=True)
                cur.execute(
                    """
                    UPDATE line_items
                    SET metadata_json = COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb
                    WHERE document_id = %s AND id = %s;
                    """,
                    (patch, document_id, line_item_id),
                )
                updated_rows += int(cur.rowcount or 0)
        if updated_rows > 0:
            _clear_document_approval_state(conn, document_id)
    return updated_rows


def update_line_item_review_state(
    document_id: int,
    line_item_id: int,
    *,
    checked: bool,
    reason: str | None = None,
) -> int:
    patch = json.dumps(
        {
            "review_checked": bool(checked),
            "review_checked_at": (
                datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                if checked
                else None
            ),
            "review_checked_reason": (reason or "").strip() or None,
        },
        ensure_ascii=True,
    )
    with get_db() as conn:
        updated = conn.execute(
            """
            UPDATE line_items
            SET metadata_json = COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb
            WHERE document_id = %s AND id = %s;
            """,
            (patch, document_id, line_item_id),
        ).rowcount or 0
        if updated:
            _clear_document_approval_state(conn, document_id)
    return int(updated)


def update_line_item_alternative_append_mode(
    document_id: int,
    line_item_id: int,
    *,
    append_at_end: bool,
) -> int:
    patch = json.dumps(
        {
            "alternative_append_at_end": bool(append_at_end),
            "alternative_append_at_end_source": "ui_manual",
            "alternative_append_at_end_updated_at": (
                datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            ),
        },
        ensure_ascii=True,
    )
    with get_db() as conn:
        updated = conn.execute(
            """
            UPDATE line_items
            SET metadata_json = COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb
            WHERE document_id = %s AND id = %s;
            """,
            (patch, document_id, line_item_id),
        ).rowcount or 0
        if updated:
            _clear_document_approval_state(conn, document_id)
    return int(updated)


def update_line_item_embedded_alternative_append_mode(
    document_id: int,
    line_item_id: int,
    *,
    alternative_index: int,
    append_at_end: bool,
) -> int:
    key = str(max(1, int(alternative_index)))
    patch = json.dumps(
        {
            "embedded_alternative_append_at_end_source": "ui_manual",
            "embedded_alternative_append_at_end_updated_at": (
                datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            ),
        },
        ensure_ascii=True,
    )
    with get_db() as conn:
        updated = conn.execute(
            """
            UPDATE line_items
            SET metadata_json =
                jsonb_set(
                    CASE
                        WHEN jsonb_typeof(COALESCE(metadata_json, '{}'::jsonb)->'embedded_alternative_append_at_end') = 'object'
                            THEN COALESCE(metadata_json, '{}'::jsonb)
                        ELSE COALESCE(metadata_json, '{}'::jsonb) || '{"embedded_alternative_append_at_end": {}}'::jsonb
                    END,
                    ARRAY['embedded_alternative_append_at_end', %s],
                    to_jsonb(%s::boolean),
                    TRUE
                ) || %s::jsonb
            WHERE document_id = %s AND id = %s;
            """,
            (key, bool(append_at_end), patch, document_id, line_item_id),
        ).rowcount or 0
        if updated:
            _clear_document_approval_state(conn, document_id)
    return int(updated)


def update_line_item_line_total_override(
    document_id: int,
    line_item_id: int,
    *,
    line_total: Decimal,
) -> dict[str, Any] | None:
    patch = json.dumps(
        {
            "manual_line_total_override": str(line_total.quantize(Decimal("0.01"))),
            "manual_line_total_override_source": "ui_manual",
            "manual_line_total_override_updated_at": (
                datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            ),
        },
        ensure_ascii=True,
    )
    with get_db() as conn:
        row = conn.execute(
            """
            UPDATE line_items
            SET
                line_total = %s,
                unit_price = CASE
                    WHEN quantity IS NOT NULL AND quantity <> 0 THEN ROUND((%s / quantity)::numeric, 2)
                    ELSE %s
                END,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb) || %s::jsonb
            WHERE document_id = %s AND id = %s
            RETURNING id, unit_price, line_total, metadata_json;
            """,
            (line_total, line_total, line_total, patch, document_id, line_item_id),
        ).fetchone()
        if row:
            _clear_document_approval_state(conn, document_id)
    return dict(row) if row else None


LINE_ITEM_EDITABLE_COLUMNS = {
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
}


def update_line_item_fields(
    document_id: int,
    line_item_id: int,
    updates: dict[str, Any],
    *,
    actor_username: str | None = None,
) -> dict[str, Any] | None:
    clean_updates = {
        key: value
        for key, value in (updates or {}).items()
        if key in LINE_ITEM_EDITABLE_COLUMNS
    }
    if not clean_updates:
        return None

    edited_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    metadata_patch = {
        "manual_edit": True,
        "manual_edit_source": "ui_manual",
        "manual_edit_updated_at": edited_at,
        "manual_edit_fields": sorted(clean_updates.keys()),
    }
    if "line_total" in clean_updates:
        metadata_patch["rieder_original_line_total"] = (
            str(clean_updates["line_total"]) if clean_updates["line_total"] is not None else None
        )
    if "unit_price" in clean_updates:
        metadata_patch["rieder_original_unit_price"] = (
            str(clean_updates["unit_price"]) if clean_updates["unit_price"] is not None else None
        )
    if actor_username:
        metadata_patch["manual_edit_actor"] = actor_username
    values = list(clean_updates.values())
    assignments = ", ".join(f"{key} = %s" for key in clean_updates)
    sql = f"""
        UPDATE line_items
        SET
            {assignments},
            metadata_json = COALESCE(metadata_json, '{{}}'::jsonb) || %s::jsonb
        WHERE document_id = %s AND id = %s
        RETURNING
            id,
            document_id,
            position_no,
            lv_pos,
            is_alternative,
            quantity,
            unit,
            width_mm,
            height_mm,
            description_short,
            description_long,
            unit_price,
            line_total,
            page_ref,
            confidence,
            metadata_json;
    """
    with get_db() as conn:
        row = conn.execute(
            sql,
            (
                *values,
                json.dumps(metadata_patch, ensure_ascii=True),
                document_id,
                line_item_id,
            ),
        ).fetchone()
        if row:
            _clear_document_approval_state(conn, document_id)
    return dict(row) if row else None


def update_document_approval_state(
    document_id: int,
    *,
    approval_status: str,
    reviewed_by: str | None = None,
    approval_note: str | None = None,
) -> dict[str, Any] | None:
    normalized = str(approval_status or "").strip().lower()
    if normalized not in {"pending", "approved"}:
        raise ValueError(f"Unsupported approval_status: {approval_status}")

    reviewed_by_value = (reviewed_by or "").strip() or None
    approval_note_value = (approval_note or "").strip() or None
    reviewed_at_value = datetime.now(timezone.utc) if normalized == "approved" else None

    with get_db() as conn:
        row = conn.execute(
            """
            UPDATE documents
            SET
                approval_status = %s,
                reviewed_by = %s,
                reviewed_at = %s,
                approval_note = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING
                id,
                approval_status,
                reviewed_by,
                reviewed_at,
                approval_note,
                updated_at;
            """,
            (
                normalized,
                reviewed_by_value if normalized == "approved" else None,
                reviewed_at_value,
                approval_note_value if normalized == "approved" else None,
                document_id,
            ),
        ).fetchone()
    return dict(row) if row else None


def insert_vendoc_export_job(
    *,
    document_id: int,
    external_document_id: str,
    dry_run: bool,
    status: str,
    target_server: str | None,
    target_database: str | None,
    line_item_count: int,
    warning_count: int,
    error_count: int,
    error_text: str | None,
    approval_status: str | None,
    reviewed_by: str | None,
    reviewed_at: Any | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    payload_json = json.dumps(payload, ensure_ascii=True, default=str)
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO vendoc_export_jobs (
                document_id,
                external_document_id,
                dry_run,
                status,
                target_server,
                target_database,
                line_item_count,
                warning_count,
                error_count,
                error_text,
                approval_status,
                reviewed_by,
                reviewed_at,
                payload_json
            )
            VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING
                id,
                document_id,
                external_document_id,
                dry_run,
                status,
                target_server,
                target_database,
                line_item_count,
                warning_count,
                error_count,
                error_text,
                approval_status,
                reviewed_by,
                reviewed_at,
                payload_json,
                created_at,
                updated_at;
            """,
            (
                document_id,
                external_document_id,
                dry_run,
                status,
                target_server,
                target_database,
                line_item_count,
                warning_count,
                error_count,
                error_text,
                approval_status,
                reviewed_by,
                reviewed_at,
                payload_json,
            ),
        ).fetchone()
    return dict(row)


def list_vendoc_export_jobs(document_id: int, limit: int = 20) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                document_id,
                external_document_id,
                dry_run,
                status,
                target_server,
                target_database,
                line_item_count,
                warning_count,
                error_count,
                error_text,
                approval_status,
                reviewed_by,
                reviewed_at,
                payload_json,
                created_at,
                updated_at
            FROM vendoc_export_jobs
            WHERE document_id = %s
            ORDER BY id DESC
            LIMIT %s;
            """,
            (document_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_latest_vendoc_export_job(document_id: int) -> dict[str, Any] | None:
    rows = list_vendoc_export_jobs(document_id, limit=1)
    return rows[0] if rows else None


def get_vendoc_import_state(document_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1
                    FROM vendoc_export_jobs
                    WHERE document_id = %s
                      AND dry_run = FALSE
                      AND status = 'exported'
                ) AS already_imported,
                MAX(created_at) FILTER (
                    WHERE dry_run = FALSE
                      AND status = 'exported'
                ) AS latest_imported_at
            FROM vendoc_export_jobs
            WHERE document_id = %s;
            """,
            (document_id, document_id),
        ).fetchone()
    return {
        "document_id": document_id,
        "already_imported": bool(row.get("already_imported")) if row else False,
        "latest_imported_at": row.get("latest_imported_at") if row else None,
    }


def reset_document_results(document_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        document = conn.execute(
            """
            SELECT id, source_file, raw_text_path
            FROM documents
            WHERE id = %s;
            """,
            (document_id,),
        ).fetchone()
        if not document:
            return None

        amount_lines_deleted = conn.execute(
            "DELETE FROM document_amount_lines WHERE document_id = %s;",
            (document_id,),
        ).rowcount or 0
        line_items_deleted = conn.execute(
            "DELETE FROM line_items WHERE document_id = %s;",
            (document_id,),
        ).rowcount or 0
        images_deleted = conn.execute(
            "DELETE FROM document_images WHERE document_id = %s;",
            (document_id,),
        ).rowcount or 0
        conn.execute(
            """
            UPDATE documents
            SET linked_offer_document_id = NULL,
                updated_at = NOW()
            WHERE linked_offer_document_id = %s;
            """,
            (document_id,),
        )

        updated = conn.execute(
            """
            UPDATE documents
            SET
                supplier_name = NULL,
                document_type = 'angebot',
                offer_reference = NULL,
                linked_offer_document_id = NULL,
                document_number = NULL,
                document_date = NULL,
                project_ref = NULL,
                document_notes = NULL,
                currency = NULL,
                net_total = NULL,
                vat_total = NULL,
                gross_total = NULL,
                parse_confidence = NULL,
                apply_pricing_adjustments = TRUE,
                approval_status = 'pending',
                reviewed_by = NULL,
                reviewed_at = NULL,
                approval_note = NULL,
                status = 'uploaded',
                error_message = NULL,
                raw_text_path = NULL,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, status, updated_at;
            """,
            (document_id,),
        ).fetchone()

    return {
        "id": updated["id"],
        "status": updated["status"],
        "updated_at": updated["updated_at"],
        "previous_raw_text_path": document["raw_text_path"],
        "deleted_amount_lines": amount_lines_deleted,
        "deleted_line_items": line_items_deleted,
        "deleted_images": images_deleted,
    }


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _metadata_dict(item: dict[str, Any]) -> dict[str, Any]:
    return metadata_dict(item)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _pricing_adjustments_enabled(document: dict[str, Any] | None) -> bool:
    if not document:
        return True
    value = document.get("apply_pricing_adjustments")
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "ja", "y", "on"}


def _line_item_with_document_pricing_mode(item: dict[str, Any], *, apply_pricing_adjustments: bool) -> dict[str, Any]:
    if apply_pricing_adjustments:
        return item
    metadata = _metadata_dict(item)
    if metadata.get("pricing_source") == "rieder_delivery_block":
        return item

    original_line_total = None
    for key in ("pricing_original_line_total", "rieder_original_line_total", "entholzer_original_line_total"):
        original_line_total = _to_decimal(metadata.get(key))
        if original_line_total is not None:
            break
    original_unit_price = None
    for key in ("pricing_original_unit_price", "rieder_original_unit_price", "entholzer_original_unit_price"):
        original_unit_price = _to_decimal(metadata.get(key))
        if original_unit_price is not None:
            break
    if original_line_total is None and original_unit_price is None:
        return item

    adjusted = dict(item)
    adjusted_metadata = dict(metadata)
    adjusted_metadata["pricing_effective_applied"] = False
    adjusted_metadata["pricing_disabled_by_document"] = True
    for provider_key in ("rieder", "entholzer", "rekord_vomp", "koch"):
        if adjusted_metadata.get(f"{provider_key}_pricing_applied"):
            adjusted_metadata[f"{provider_key}_pricing_effective_applied"] = False
            adjusted_metadata[f"{provider_key}_pricing_disabled_by_document"] = True
    adjusted["metadata_json"] = adjusted_metadata
    if original_line_total is not None:
        adjusted["line_total"] = original_line_total
    if original_unit_price is not None:
        adjusted["unit_price"] = original_unit_price
    elif original_line_total is not None:
        quantity = _to_decimal(adjusted.get("quantity"))
        if quantity is not None and quantity != 0:
            adjusted["unit_price"] = (original_line_total / quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            adjusted["unit_price"] = original_line_total
    return adjusted


def _line_items_with_document_pricing_mode(
    document: dict[str, Any],
    line_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    apply_pricing_adjustments = _pricing_adjustments_enabled(document)
    return [
        _line_item_with_document_pricing_mode(item, apply_pricing_adjustments=apply_pricing_adjustments)
        for item in line_items
    ]


def _metadata_image_ids(item: dict[str, Any], valid_ids: set[int]) -> list[int]:
    return list(metadata_image_assignment(item, valid_ids).get("image_ids") or [])


def _line_item_sort_key(item: dict[str, Any]) -> tuple[int, int, int]:
    item_id = _to_int(item.get("id"))
    if item_id is not None:
        return (0, item_id, 0)

    position_no = item.get("position_no")
    position_int = _to_int(position_no)
    if position_int is not None:
        return (1, position_int, 0)
    return (2, 0, 0)


def _image_sort_key(image: dict[str, Any]) -> tuple[int, float, float, int, int]:
    return image_layout_sort_key(image)


def _is_probably_decorative_image(image: dict[str, Any], repeated_hashes: set[str]) -> bool:
    width = _to_int(image.get("width")) or 0
    height = _to_int(image.get("height")) or 0
    bytes_size = _to_int(image.get("bytes_size")) or 0
    area = width * height
    ratio = (max(width, height) / min(width, height)) if width and height else 0.0
    repeated = bool(image.get("sha256") and image.get("sha256") in repeated_hashes)

    # Small assets (logos/icons) tend to be tiny in both area and bytes.
    if area and area < 45_000 and bytes_size < 20_000:
        # Keep compact but non-repeated near-square sketches as non-decorative.
        if not repeated and min(width, height) >= 60 and ratio <= 3.0:
            return False
        return True
    if max(width, height) and max(width, height) < 180 and bytes_size < 12_000:
        return True

    # Repeated strip-like images across pages are usually headers/footers.
    if repeated and ratio >= 4.0 and min(width, height) <= 360:
        return True
    # Single-page ultra-wide strips are also usually separators or footer bars.
    if ratio >= 4.5 and min(width, height) <= 90 and bytes_size < 30_000:
        return True
    return False


def _has_image_geometry(image: dict[str, Any]) -> bool:
    width = _to_int(image.get("width")) or 0
    height = _to_int(image.get("height")) or 0
    return width > 0 and height > 0


def _pick_candidate_images_for_page(
    page_images: list[dict[str, Any]],
    repeated_hashes: set[str],
) -> list[dict[str, Any]]:
    filtered = [img for img in page_images if not _is_probably_decorative_image(img, repeated_hashes)]
    if not filtered:
        return []
    return sorted(filtered, key=_image_sort_key)


def _dedupe_ints(values: list[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def get_document_result(document_id: int) -> dict[str, Any] | None:
    document = get_document(document_id)
    if not document:
        return None
    document_relations = get_document_relations(document_id)

    with get_db() as conn:
        amount_lines = conn.execute(
            """
            SELECT
                id,
                line_type,
                label_raw,
                percent,
                base_amount,
                amount,
                sort_order
            FROM document_amount_lines
            WHERE document_id = %s
            ORDER BY sort_order ASC, id ASC;
            """,
            (document_id,),
        ).fetchall()

        line_items = conn.execute(
            """
            SELECT
                id,
                position_no,
                lv_pos,
                is_alternative,
                quantity,
                unit,
                width_mm,
                height_mm,
                description_short,
                description_long,
                unit_price,
                line_total,
                page_ref,
                confidence,
                metadata_json
            FROM line_items
            WHERE document_id = %s
            ORDER BY id ASC;
            """,
            (document_id,),
        ).fetchall()

        images = conn.execute(
            """
            SELECT
                id,
                page_ref,
                image_index,
                mime_type,
                storage_path,
                sha256,
                width,
                height,
                metadata_json,
                bytes_size,
                created_at
            FROM document_images
            WHERE document_id = %s
            ORDER BY page_ref ASC, image_index ASC;
            """,
            (document_id,),
        ).fetchall()

    image_list = [dict(row) for row in images]
    hash_pages: dict[str, set[int]] = {}
    images_by_page: dict[int, list[dict[str, Any]]] = {}
    for image in image_list:
        page_ref = _to_int(image.get("page_ref"))
        if page_ref is not None:
            images_by_page.setdefault(page_ref, []).append(image)
        sha256 = image.get("sha256")
        if sha256 and page_ref is not None:
            hash_pages.setdefault(sha256, set()).add(page_ref)

    repeated_hashes = {sha for sha, pages in hash_pages.items() if len(pages) >= 2}
    valid_image_ids = {
        image_id for image_id in (_to_int(image.get("id")) for image in image_list) if image_id is not None
    }
    image_by_id = {
        image_id: image for image_id, image in (( _to_int(image.get("id")), image) for image in image_list) if image_id is not None
    }

    for image in image_list:
        image["is_repeated_across_pages"] = bool(image.get("sha256") in repeated_hashes if image.get("sha256") else False)
        image["is_probably_decorative"] = _is_probably_decorative_image(image, repeated_hashes)

    line_item_list: list[dict[str, Any]] = [dict(row) for row in line_items]
    items_by_page: dict[int, list[int]] = {}
    candidate_ids_by_page: dict[int, list[int]] = {}
    all_ids_by_page: dict[int, list[int]] = {}
    for page_ref, page_images in images_by_page.items():
        ordered_page_images = sorted(page_images, key=_image_sort_key)
        all_ids_by_page[page_ref] = [img["id"] for img in ordered_page_images if img.get("id") is not None]
        candidates = _pick_candidate_images_for_page(ordered_page_images, repeated_hashes)
        candidate_ids_by_page[page_ref] = [img["id"] for img in candidates if img.get("id") is not None]

    for idx, item in enumerate(line_item_list):
        item["image_ids"] = []
        item["image_count"] = 0
        item["image_ids_primary"] = []
        item["image_candidate_ids"] = []
        item["image_candidate_count"] = 0
        item["image_ids_page_all"] = []
        item["image_count_page_all"] = 0
        item["image_next_page_allowed"] = False
        item["image_prefers_next_page"] = False
        item["image_auto_match_allowed"] = True
        assignment_meta = metadata_image_assignment(item, valid_image_ids)
        review_meta = metadata_review_state(item)
        item["_image_assignment_meta"] = assignment_meta
        item["_review_meta"] = review_meta
        item["image_assignment_source"] = assignment_meta.get("source")
        item["image_assignment_reason"] = assignment_meta.get("reason")
        item["image_assignment_has_decision"] = bool(assignment_meta.get("has_decision"))
        item["image_assignment_is_final"] = bool(assignment_meta.get("is_final"))
        item["review_checked"] = bool(review_meta.get("checked"))
        item["review_checked_at"] = review_meta.get("checked_at")
        item["review_checked_reason"] = review_meta.get("reason")
        item["alternative_append_at_end"] = bool(metadata_dict(item).get("alternative_append_at_end"))
        page_ref = _to_int(item.get("page_ref"))
        page_end_ref = _to_int((metadata_dict(item) or {}).get("page_end_ref"))
        if page_ref is not None and (page_end_ref is None or page_end_ref < page_ref):
            page_end_ref = page_ref
        item["page_end_ref"] = page_end_ref
        item["spans_page_break"] = bool(page_ref is not None and page_end_ref is not None and page_end_ref > page_ref)
        if page_ref is None:
            continue
        items_by_page.setdefault(page_ref, []).append(idx)

    for page_ref, item_indexes in items_by_page.items():
        all_page_image_ids = all_ids_by_page.get(page_ref, [])
        current_candidates = candidate_ids_by_page.get(page_ref, [])
        next_candidates = candidate_ids_by_page.get(page_ref + 1, [])
        prev_candidates = candidate_ids_by_page.get(page_ref - 1, [])
        prev_item_indexes = items_by_page.get(page_ref - 1, [])
        next_item_indexes = items_by_page.get(page_ref + 1, [])

        sorted_item_indexes = sorted(item_indexes, key=lambda idx: _line_item_sort_key(line_item_list[idx]))
        visual_item_indexes = [idx for idx in sorted_item_indexes if not is_non_visual_line_item(line_item_list[idx])]
        visual_item_order = {idx: order for order, idx in enumerate(visual_item_indexes)}
        last_visual_item_idx = visual_item_indexes[-1] if visual_item_indexes else None
        visual_item_count = len(visual_item_indexes)
        prev_visual_item_count = len(
            [
                idx
                for idx in sorted(prev_item_indexes, key=lambda idx: _line_item_sort_key(line_item_list[idx]))
                if not is_non_visual_line_item(line_item_list[idx])
            ]
        )
        next_visual_item_count = len(
            [
                idx
                for idx in sorted(next_item_indexes, key=lambda idx: _line_item_sort_key(line_item_list[idx]))
                if not is_non_visual_line_item(line_item_list[idx])
            ]
        )
        current_viable_page_ids = [
            image_id
            for image_id in current_candidates
            if is_viable_auto_assignment_image(image_by_id.get(image_id, {}))
        ]
        next_viable_page_ids = [
            image_id
            for image_id in next_candidates
            if is_viable_auto_assignment_image(image_by_id.get(image_id, {}))
        ]
        prev_viable_page_ids = [
            image_id
            for image_id in prev_candidates
            if is_viable_auto_assignment_image(image_by_id.get(image_id, {}))
        ]
        current_page_pool_ids = [
            image_id
            for image_id in current_candidates
            if _has_image_geometry(image_by_id.get(image_id, {}))
        ]
        next_page_pool_ids = [
            image_id
            for image_id in next_candidates
            if _has_image_geometry(image_by_id.get(image_id, {}))
        ]
        incoming_carryover_ids = (
            spare_carryover_image_ids(current_viable_page_ids, next_page_visual_item_count=visual_item_count)
            if prev_visual_item_count > len(prev_viable_page_ids)
            else []
        )
        own_current_viable_page_ids = current_viable_page_ids[len(incoming_carryover_ids) :]
        own_current_page_pool_ids = [
            image_id
            for image_id in current_page_pool_ids
            if image_id not in set(incoming_carryover_ids)
        ]
        current_page_needs_carryover = bool(visual_item_indexes and len(own_current_viable_page_ids) < visual_item_count)
        carryover_neighbor_ids = (
            spare_carryover_image_ids(next_viable_page_ids, next_page_visual_item_count=next_visual_item_count)
            if current_page_needs_carryover
            else []
        )
        for item_offset, item_idx in enumerate(sorted_item_indexes):
            item = line_item_list[item_idx]
            visual_item_offset = visual_item_order.get(item_idx)
            item_scoped_current_viable_page_ids = [
                image_id
                for image_id in own_current_page_pool_ids
                if is_viable_auto_assignment_image_for_item(item, image_by_id.get(image_id, {}))
            ]
            item_scoped_next_viable_page_ids = [
                image_id
                for image_id in next_page_pool_ids
                if is_viable_auto_assignment_image_for_item(item, image_by_id.get(image_id, {}))
            ]
            slot_image_id = page_visual_slot_image_id(item_scoped_current_viable_page_ids, visual_item_offset)
            if slot_image_id is None and len(item_scoped_current_viable_page_ids) == 1:
                slot_image_id = item_scoped_current_viable_page_ids[0]
            item_page_end_ref = _to_int(item.get("page_end_ref"))
            spans_to_next_page = bool(item_page_end_ref is not None and item_page_end_ref > page_ref)
            aspect_prefers_next_page = _prefer_next_page_for_aspect_fit(
                item,
                current_image_id=slot_image_id,
                next_page_image_ids=item_scoped_next_viable_page_ids,
                image_by_id=image_by_id,
            )
            window_prefers_next_page = bool(
                item_dimension_ratio(item) is not None
                and not item_scoped_current_viable_page_ids
                and item_scoped_next_viable_page_ids
            )
            carryover_window_prefers_next_page = bool(
                metadata_dict(item).get("next_page_first_item_top_ratio") is not None
                and not item_scoped_current_viable_page_ids
                and item_scoped_next_viable_page_ids
            )
            neighbor_pool_ids = carryover_neighbor_ids
            if spans_to_next_page or aspect_prefers_next_page or window_prefers_next_page or carryover_window_prefers_next_page:
                neighbor_pool_ids = _dedupe_ints(carryover_neighbor_ids + item_scoped_next_viable_page_ids)
            allow_next_page_candidates = bool(
                neighbor_pool_ids
                and (
                    spans_to_next_page
                    or item_idx == last_visual_item_idx
                    or aspect_prefers_next_page
                    or window_prefers_next_page
                    or carryover_window_prefers_next_page
                )
            )
            item["image_next_page_allowed"] = allow_next_page_candidates
            if is_non_visual_line_item(item):
                item["image_ids"] = []
                item["image_count"] = 0
                item["image_ids_primary"] = []
                item["image_candidate_ids"] = []
                item["image_candidate_count"] = 0
                item["image_ids_page_all"] = all_page_image_ids
                item["image_count_page_all"] = len(all_page_image_ids)
                item["image_auto_match_allowed"] = False
                item["image_assignment_source"] = "unmatched"
                item["image_assignment_reason"] = "non_visual_line_item"
                continue
            assignment_meta = item.get("_image_assignment_meta") if isinstance(item.get("_image_assignment_meta"), dict) else {}
            persisted_image_ids = list(assignment_meta.get("image_ids") or [])
            has_assignment_decision = bool(assignment_meta.get("has_decision"))

            focused_current = focused_image_ids(
                item_scoped_current_viable_page_ids,
                item_count=max(1, visual_item_count),
                item_index=visual_item_offset if visual_item_offset is not None else item_offset,
                max_candidates=4,
            )
            viable_current = [
                slot_image_id
            ] if slot_image_id is not None else []
            manual_candidate_current = [
                image_id
                for image_id in focused_current
                if image_id != slot_image_id and is_viable_auto_assignment_image_for_item(item, image_by_id.get(image_id, {}))
            ]
            focused_neighbor = focused_image_ids(
                neighbor_pool_ids if allow_next_page_candidates else [],
                item_count=max(1, visual_item_count),
                item_index=0 if spans_to_next_page else (visual_item_offset if visual_item_offset is not None else item_offset),
                max_candidates=3,
            )
            viable_neighbor = [
                image_id
                for image_id in focused_neighbor
                if is_viable_auto_assignment_image_for_item(item, image_by_id.get(image_id, {}))
            ]
            focused_fallback = focused_image_ids(
                []
                if (viable_current or viable_neighbor)
                else _dedupe_ints(
                    all_page_image_ids
                    + (neighbor_pool_ids if allow_next_page_candidates else [])
                ),
                item_count=max(1, visual_item_count),
                item_index=visual_item_offset if visual_item_offset is not None else item_offset,
                max_candidates=3,
            )
            prefers_next_page = bool(
                allow_next_page_candidates
                and viable_neighbor
                and (
                    spans_to_next_page
                    or
                    aspect_prefers_next_page
                    or window_prefers_next_page
                    or carryover_window_prefers_next_page
                    or (
                        visual_item_offset is not None
                        and slot_image_id is None
                    )
                )
            )
            item["image_prefers_next_page"] = prefers_next_page
            if prefers_next_page:
                candidate_ids = _dedupe_ints(viable_neighbor + manual_candidate_current + focused_neighbor + focused_fallback)
            else:
                candidate_ids = _dedupe_ints(viable_current + manual_candidate_current + focused_neighbor + focused_fallback)

            if persisted_image_ids:
                final_ids = persisted_image_ids
                item["image_assignment_source"] = item.get("image_assignment_source") or "persisted_assignment"
                item["image_assignment_reason"] = item.get("image_assignment_reason") or "stored_assignment"
            elif has_assignment_decision:
                final_ids = []
                item["image_assignment_source"] = item.get("image_assignment_source") or "unmatched"
                item["image_assignment_reason"] = item.get("image_assignment_reason") or "stored_no_assignment"
                if item.get("image_assignment_source") == "unmatched" and item.get("image_assignment_reason") in {
                    "no_candidate_images",
                    "no_confident_candidate",
                    "no_unique_image_slot",
                }:
                    item["image_auto_match_allowed"] = False
            elif prefers_next_page and viable_neighbor:
                final_ids = viable_neighbor[:1]
                item["image_assignment_source"] = "page_neighbor_fallback"
                item["image_assignment_reason"] = "overflow_to_next_page_visual"
            elif viable_current:
                final_ids = viable_current[:1]
                item["image_assignment_source"] = "page_layout"
                item["image_assignment_reason"] = "same_page_image_distribution"
            elif viable_neighbor and allow_next_page_candidates:
                final_ids = viable_neighbor[:1]
                item["image_assignment_source"] = "page_neighbor_fallback"
                item["image_assignment_reason"] = "adjacent_page_visual_carryover"
            else:
                final_ids = []
                item["image_assignment_source"] = "unmatched"
                if focused_fallback or manual_candidate_current:
                    item["image_assignment_reason"] = "no_unique_image_slot"
                else:
                    item["image_assignment_reason"] = "no_candidate_images"
                item["image_auto_match_allowed"] = False

            item["image_ids"] = final_ids
            item["image_count"] = len(final_ids)
            item["image_ids_primary"] = final_ids[:1]
            item["image_candidate_ids"] = candidate_ids
            item["image_candidate_count"] = len(candidate_ids)
            item["image_ids_page_all"] = all_page_image_ids
            item["image_count_page_all"] = len(all_page_image_ids)

    assigned_image_to_items: dict[int, list[int]] = {}
    assigned_image_to_positions: dict[int, list[str]] = {}
    for item in line_item_list:
        item_id = _to_int(item.get("id"))
        assigned_image_ids = [
            image_id
            for image_id in (_to_int(image_id) for image_id in (item.get("image_ids") or []))
            if image_id is not None
        ]
        if item_id is None or not assigned_image_ids:
            continue
        position_no = str(item.get("position_no") or "").strip()
        for image_id in assigned_image_ids:
            if image_id not in assigned_image_to_items:
                assigned_image_to_items[image_id] = []
            assigned_image_to_items[image_id].append(item_id)
            if position_no:
                if image_id not in assigned_image_to_positions:
                    assigned_image_to_positions[image_id] = []
                if position_no not in assigned_image_to_positions[image_id]:
                    assigned_image_to_positions[image_id].append(position_no)

    for image in image_list:
        image_id = _to_int(image.get("id"))
        matched_item_ids = assigned_image_to_items.get(image_id, []) if image_id is not None else []
        matched_positions = assigned_image_to_positions.get(image_id, []) if image_id is not None else []
        image["is_assigned"] = bool(matched_item_ids)
        image["assigned_line_item_ids"] = matched_item_ids
        image["assigned_match_count"] = len(matched_item_ids)
        image["assigned_position_nos"] = matched_positions

    for item in line_item_list:
        item.pop("_image_assignment_meta", None)
        item.pop("_review_meta", None)

    line_item_list = _line_items_with_document_pricing_mode(document, line_item_list)

    validation = build_document_validation(
        document=document,
        amount_lines=[dict(row) for row in amount_lines],
        line_items=line_item_list,
        images=image_list,
        enforce_image_validation=True,
    )

    return {
        "document": document,
        "document_relations": document_relations,
        "amount_lines": [dict(row) for row in amount_lines],
        "line_items": line_item_list,
        "images": image_list,
        "validation": validation,
    }


def get_document_image(document_id: int, image_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                document_id,
                page_ref,
                image_index,
                mime_type,
                storage_path,
                sha256,
                width,
                height,
                metadata_json,
                bytes_size,
                created_at
            FROM document_images
            WHERE document_id = %s AND id = %s;
            """,
            (document_id, image_id),
        ).fetchone()
    return dict(row) if row else None
