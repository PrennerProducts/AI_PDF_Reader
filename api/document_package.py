from copy import deepcopy
from typing import Any

from validation import build_document_validation


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _position_key(value: Any) -> str:
    return str(value or "").strip()


def _source_positions(image: dict[str, Any]) -> list[str]:
    metadata = image.get("metadata_json")
    if not isinstance(metadata, dict):
        return []
    raw_positions = metadata.get("source_position_numbers") or metadata.get("position_numbers") or []
    if not isinstance(raw_positions, list):
        return []
    positions: list[str] = []
    for value in raw_positions:
        position = _position_key(value)
        if position and position not in positions:
            positions.append(position)
    return positions


def _detail_priority(image: dict[str, Any], document: dict[str, Any]) -> tuple[int, int, int]:
    metadata = image.get("metadata_json")
    metadata = metadata if isinstance(metadata, dict) else {}
    source_type = _norm(metadata.get("source_detail_type") or document.get("project_ref") or document.get("original_filename"))
    if "visualisierung" in source_type:
        source_priority = 0
    elif "system" in source_type:
        source_priority = 1
    else:
        source_priority = 2
    page_ref = int(image.get("page_ref") or 0)
    image_index = int(image.get("image_index") or 0)
    return (source_priority, page_ref, image_index)


def infer_main_document_id(results: list[dict[str, Any]], explicit_main_document_id: int | None = None) -> int:
    if explicit_main_document_id:
        return explicit_main_document_id

    candidates: list[dict[str, Any]] = []
    for result in results:
        document = result.get("document") if isinstance(result.get("document"), dict) else {}
        line_items = result.get("line_items") if isinstance(result.get("line_items"), list) else []
        if _norm(document.get("document_type")) in {"angebot", "auftragsbestaetigung"} and line_items:
            candidates.append(document)

    if len(candidates) == 1:
        return int(candidates[0]["id"])
    if not candidates:
        raise ValueError("Kein Hauptdokument im Paket gefunden. Erwartet wird ein Angebot oder eine Auftragsbestätigung mit Positionen.")
    raise ValueError("Mehrere mögliche Hauptdokumente gefunden. Bitte main_document_id explizit angeben.")


def build_document_package_result(
    results: list[dict[str, Any]],
    *,
    main_document_id: int | None = None,
) -> dict[str, Any]:
    if not results:
        raise ValueError("Dokumentpaket ist leer.")

    main_id = infer_main_document_id(results, main_document_id)
    main_result = next(
        (result for result in results if int((result.get("document") or {}).get("id") or 0) == main_id),
        None,
    )
    if main_result is None:
        raise ValueError(f"Hauptdokument #{main_id} ist nicht im Paket enthalten.")

    combined = deepcopy(main_result)
    combined_document = combined.get("document") if isinstance(combined.get("document"), dict) else {}
    combined_document["package_mode"] = True
    combined_document["package_main_document_id"] = main_id

    package_images: list[dict[str, Any]] = []
    image_candidates_by_position: dict[str, list[dict[str, Any]]] = {}
    package_documents: list[dict[str, Any]] = []

    for result in results:
        document = result.get("document") if isinstance(result.get("document"), dict) else {}
        document_id = int(document.get("id") or 0)
        package_documents.append(
            {
                "id": document_id,
                "original_filename": document.get("original_filename"),
                "supplier_name": document.get("supplier_name"),
                "document_type": document.get("document_type"),
                "document_number": document.get("document_number"),
                "project_ref": document.get("project_ref"),
                "is_main": document_id == main_id,
            }
        )
        if document_id == main_id:
            continue
        for image in result.get("images") or []:
            if not isinstance(image, dict):
                continue
            positions = _source_positions(image)
            if not positions:
                continue
            image_copy = deepcopy(image)
            metadata = image_copy.get("metadata_json")
            metadata = metadata if isinstance(metadata, dict) else {}
            metadata["package_source_document_id"] = document_id
            metadata["package_source_filename"] = document.get("original_filename")
            image_copy["metadata_json"] = metadata
            package_images.append(image_copy)
            for position in positions:
                image_candidates_by_position.setdefault(position, []).append(
                    {
                        "image": image_copy,
                        "priority": _detail_priority(image_copy, document),
                        "source_document_id": document_id,
                    }
                )

    for candidates in image_candidates_by_position.values():
        candidates.sort(key=lambda row: row["priority"])

    combined_images = list(combined.get("images") or [])
    existing_ids = {int(image.get("id")) for image in combined_images if isinstance(image, dict) and image.get("id") is not None}
    for image in package_images:
        try:
            image_id = int(image.get("id"))
        except (TypeError, ValueError):
            continue
        if image_id not in existing_ids:
            combined_images.append(image)
            existing_ids.add(image_id)
    combined["images"] = combined_images

    assigned_positions = []
    missing_positions = []
    assigned_image_to_positions: dict[int, list[str]] = {}
    for item in combined.get("line_items") or []:
        if not isinstance(item, dict):
            continue
        position = _position_key(item.get("position_no"))
        candidates = image_candidates_by_position.get(position, [])
        if not position or not candidates:
            if position:
                missing_positions.append(position)
            continue
        primary_image = candidates[0]["image"]
        primary_id = int(primary_image["id"])
        candidate_ids = []
        for candidate in candidates:
            image_id = int(candidate["image"]["id"])
            if image_id not in candidate_ids:
                candidate_ids.append(image_id)
        item["image_ids"] = [primary_id]
        item["image_ids_primary"] = [primary_id]
        item["image_count"] = 1
        item["image_candidate_ids"] = candidate_ids
        item["image_candidate_count"] = len(candidate_ids)
        item["image_assignment_source"] = "document_package"
        item["image_assignment_reason"] = "matched_detail_pdf_position_number"
        item["image_assignment_has_decision"] = True
        item["image_assignment_is_final"] = True
        metadata = item.get("metadata_json") if isinstance(item.get("metadata_json"), dict) else {}
        metadata = {**metadata, "package_image_source": "detail_pdf", "package_candidate_image_ids": candidate_ids}
        item["metadata_json"] = metadata
        assigned_positions.append(position)
        assigned_image_to_positions.setdefault(primary_id, [])
        if position not in assigned_image_to_positions[primary_id]:
            assigned_image_to_positions[primary_id].append(position)

    for image in combined_images:
        if not isinstance(image, dict):
            continue
        image_id = int(image.get("id") or 0)
        assigned_positions_for_image = assigned_image_to_positions.get(image_id, [])
        image["is_assigned"] = bool(assigned_positions_for_image)
        image["assigned_position_nos"] = assigned_positions_for_image
        image["assigned_match_count"] = len(assigned_positions_for_image)

    combined["package"] = {
        "main_document_id": main_id,
        "document_count": len(results),
        "documents": package_documents,
        "detail_image_count": len(package_images),
        "assigned_position_count": len(set(assigned_positions)),
        "missing_position_numbers": missing_positions,
    }
    combined["validation"] = build_document_validation(
        document=combined_document,
        amount_lines=combined.get("amount_lines") if isinstance(combined.get("amount_lines"), list) else [],
        line_items=combined.get("line_items") if isinstance(combined.get("line_items"), list) else [],
        images=combined_images,
        enforce_image_validation=True,
    )
    return combined
