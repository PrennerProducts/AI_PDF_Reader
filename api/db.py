import os
import json
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from image_assignment import (
    focused_image_ids,
    image_layout_sort_key,
    is_non_visual_line_item,
    metadata_dict,
    metadata_image_assignment,
    metadata_review_state,
)
from validation import build_document_validation

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return database_url


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
                document_type,
                offer_reference,
                document_number,
                document_date,
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
                document_type,
                offer_reference,
                document_number,
                document_date,
                project_ref,
                currency,
                net_total,
                vat_total,
                gross_total,
                parse_confidence,
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
                status = %s,
                error_message = NULL,
                updated_at = NOW()
            WHERE id = %s
            RETURNING
                id,
                supplier_name,
                document_type,
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
                status,
                document_id,
            ),
        ).fetchone()
    return dict(row)


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
                    "llm_image_ids": unique_ids,
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
    return int(updated)


def update_line_item_llm_image_ids(document_id: int, assignments: dict[int, list[int]]) -> int:
    normalized: dict[int, dict[str, Any]] = {}
    for line_item_id, image_ids in assignments.items():
        normalized[line_item_id] = {"image_ids": image_ids, "selection_source": "vlm"}
    return update_line_item_image_assignments(document_id, normalized)


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

        updated = conn.execute(
            """
            UPDATE documents
            SET
                supplier_name = NULL,
                document_type = 'angebot',
                offer_reference = NULL,
                document_number = NULL,
                document_date = NULL,
                project_ref = NULL,
                currency = NULL,
                net_total = NULL,
                vat_total = NULL,
                gross_total = NULL,
                parse_confidence = NULL,
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


def _metadata_image_ids(item: dict[str, Any], valid_ids: set[int]) -> list[int]:
    return list(metadata_image_assignment(item, valid_ids).get("image_ids") or [])


def _line_item_sort_key(item: dict[str, Any]) -> tuple[int, int, int]:
    position_no = item.get("position_no")
    position_int = _to_int(position_no)
    if position_int is not None:
        return (0, position_int, _to_int(item.get("id")) or 0)
    return (1, _to_int(item.get("id")) or 0, 0)


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
    return False


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
        page_ref = _to_int(item.get("page_ref"))
        if page_ref is None:
            continue
        items_by_page.setdefault(page_ref, []).append(idx)

    for page_ref, item_indexes in items_by_page.items():
        all_page_image_ids = all_ids_by_page.get(page_ref, [])
        current_candidates = candidate_ids_by_page.get(page_ref, [])
        next_candidates = candidate_ids_by_page.get(page_ref + 1, [])

        sorted_item_indexes = sorted(item_indexes, key=lambda idx: _line_item_sort_key(line_item_list[idx]))
        visual_item_indexes = [idx for idx in sorted_item_indexes if not is_non_visual_line_item(line_item_list[idx])]
        last_visual_item_idx = visual_item_indexes[-1] if visual_item_indexes else None
        item_count = len(sorted_item_indexes)
        for item_offset, item_idx in enumerate(sorted_item_indexes):
            item = line_item_list[item_idx]
            allow_next_page_candidates = item_idx == last_visual_item_idx
            item["image_next_page_allowed"] = allow_next_page_candidates
            if is_non_visual_line_item(item):
                item["image_ids"] = []
                item["image_count"] = 0
                item["image_ids_primary"] = []
                item["image_candidate_ids"] = []
                item["image_candidate_count"] = 0
                item["image_ids_page_all"] = all_page_image_ids
                item["image_count_page_all"] = len(all_page_image_ids)
                item["image_assignment_source"] = "unmatched"
                item["image_assignment_reason"] = "non_visual_line_item"
                continue
            assignment_meta = item.get("_image_assignment_meta") if isinstance(item.get("_image_assignment_meta"), dict) else {}
            persisted_image_ids = list(assignment_meta.get("image_ids") or [])
            has_assignment_decision = bool(assignment_meta.get("has_decision"))

            focused_current = focused_image_ids(
                current_candidates,
                item_count=item_count,
                item_index=item_offset,
                max_candidates=4,
            )
            focused_neighbor = focused_image_ids(
                next_candidates if allow_next_page_candidates else [],
                item_count=item_count,
                item_index=item_offset,
                max_candidates=3,
            )
            focused_fallback = focused_image_ids(
                _dedupe_ints(
                    all_page_image_ids
                    + (all_ids_by_page.get(page_ref + 1, []) if allow_next_page_candidates else [])
                ),
                item_count=item_count,
                item_index=item_offset,
                max_candidates=3,
            )
            candidate_ids = _dedupe_ints(focused_current + focused_neighbor + focused_fallback)

            if persisted_image_ids:
                final_ids = persisted_image_ids
                item["image_assignment_source"] = item.get("image_assignment_source") or "persisted_assignment"
                item["image_assignment_reason"] = item.get("image_assignment_reason") or "stored_assignment"
            elif has_assignment_decision:
                final_ids = []
                item["image_assignment_source"] = item.get("image_assignment_source") or "unmatched"
                item["image_assignment_reason"] = item.get("image_assignment_reason") or "stored_no_assignment"
            elif focused_current:
                final_ids = focused_current[:2] if len(focused_current) > 1 and item_count <= len(current_candidates) else focused_current[:1]
                item["image_assignment_source"] = "page_layout"
                item["image_assignment_reason"] = "same_page_image_distribution"
            elif focused_neighbor:
                final_ids = focused_neighbor[:1]
                item["image_assignment_source"] = "page_neighbor_fallback"
                item["image_assignment_reason"] = "adjacent_page_candidates"
            elif focused_fallback:
                final_ids = focused_fallback[:1]
                item["image_assignment_source"] = "page_fallback"
                item["image_assignment_reason"] = "page_image_fallback"
            else:
                final_ids = []
                item["image_assignment_source"] = "unmatched"
                item["image_assignment_reason"] = "no_candidate_images"

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
        image["is_llm_matched"] = bool(matched_item_ids)
        image["llm_matched_line_item_ids"] = matched_item_ids
        image["llm_match_count"] = len(matched_item_ids)
        image["is_assigned"] = bool(matched_item_ids)
        image["assigned_line_item_ids"] = matched_item_ids
        image["assigned_match_count"] = len(matched_item_ids)
        image["assigned_position_nos"] = matched_positions

    for item in line_item_list:
        item.pop("_image_assignment_meta", None)
        item.pop("_review_meta", None)

    validation = build_document_validation(
        document=document,
        amount_lines=[dict(row) for row in amount_lines],
        line_items=line_item_list,
        images=image_list,
    )

    return {
        "document": document,
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
