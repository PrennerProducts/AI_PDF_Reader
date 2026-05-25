from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5
import re

from vendoc_rtf import build_vendoc_long_text_rtf


VENDOC_NAMESPACE = UUID("8f0f8c50-0f58-45d8-b8e5-83a0f7e79a11")
PRICE_AMOUNT_PATTERN = re.compile(r"(?:€\s*\d{1,3}(?:[ .]\d{3})*,\d{2}|\d{1,3}(?:[ .]\d{3})*,\d{2}\s*€)")
PRICE_LABEL_PATTERN = re.compile(r"\b(?:EP|GP|EK|VK)\s*:\s*(?:€\s*)?\d{1,3}(?:[ .]\d{3})*,\d{2}(?:\s*€)?", re.IGNORECASE)
ALTERNATIVE_LINE_PATTERN = re.compile(r"^\s*Alternativ(?:e|position)?\s*:\s*(?P<text>.+?)\s*$", re.IGNORECASE)
EP_PRICE_PATTERN = re.compile(r"\bEP\s*:\s*(?:€\s*)?(?P<amount>\d{1,3}(?:[ .]\d{3})*,\d{2})(?:\s*€)?", re.IGNORECASE)

SUPPLIER_ID_ALIASES: dict[str, str] = {
    "rieder": "300774",
    "rieder gmbh co kg fenster turen": "300774",
    "newo": "300877",
    "newo sonnen insektenschutz gmbh": "300877",
    "entholzer": "301370",
    "entholzer fenster und turen ges m b h": "301370",
    "schachermayer": "300492",
    "schachermayer gmbh beschlage befestigungstechnik": "300492",
    "rekord vomp": "300798",
    "rekord vomp gmbh kunststoff fenster u turen": "300798",
    "schlotterer": "301347",
    "schlotterer sonnenschutz systeme gmbh": "301347",
    "schuchter": "301595",
    "schuchter fenster gmbh fenster turen sonnenschutz": "301595",
    "koch": "300735",
    "koch turen gmbh": "300735",
    "koch johann tischlerei": "300735",
    "muigg": "300929",
    "muigg schlosserei metallbau gmbh schlosserei metallbau gmbh": "300929",
    "alu one": "301418",
    "alu one metallbaupartner gmbh": "301418",
    "aluone metallbaupartner gmbh": "301418",
}


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


def _normalize_inline_spacing(text: str) -> str:
    compact = re.sub(r"[ \t]{2,}", " ", text)
    compact = re.sub(r"\s+([,:;)\]])", r"\1", compact)
    compact = re.sub(r"([(\[])\s+", r"\1", compact)
    return compact.strip(" -,\t")


def _strip_price_tokens(text: str | None) -> str | None:
    raw = _to_str(text)
    if not raw:
        return raw
    cleaned = PRICE_LABEL_PATTERN.sub("", raw)
    cleaned = PRICE_AMOUNT_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\s*€\s*", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,:;])", r"\1", cleaned)
    return cleaned.strip(" -,\t") or None


def _strip_prices_from_long_text(text: str | None) -> str | None:
    raw = _to_str(text)
    if not raw:
        return raw
    cleaned_lines: list[str] = []
    for original_line in raw.splitlines():
        line = original_line.strip()
        if not line:
            continue
        sanitized = _strip_price_tokens(line)
        if not sanitized:
            continue
        sanitized = _normalize_inline_spacing(sanitized)
        if sanitized:
            cleaned_lines.append(sanitized)
    return "\n".join(cleaned_lines) or None


def _parse_euro_amount(value: str | None) -> float | None:
    raw = _to_str(value)
    if not raw:
        return None
    normalized = raw.replace(".", "").replace(" ", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def _split_embedded_alternatives(text: str | None) -> tuple[str | None, list[str]]:
    raw = _to_str(text)
    if not raw:
        return raw, []
    main_lines: list[str] = []
    alternatives: list[str] = []
    for original_line in raw.splitlines():
        match = ALTERNATIVE_LINE_PATTERN.match(original_line)
        if match:
            alt_text = match.group("text").strip()
            if alt_text:
                alternatives.append(alt_text)
            continue
        main_lines.append(original_line)
    return ("\n".join(main_lines).strip() or None), alternatives


def _nested_position(parent_position_no: str | None, fallback_parent_index: int, alt_index: int) -> str:
    parent = parent_position_no or str(max(1, fallback_parent_index))
    return f"{parent}.{alt_index}"


def _embedded_alternative_item(parent: dict[str, Any], alt_text: str, alt_index: int) -> dict[str, Any]:
    parent_id = _to_str(parent.get("id")) or _to_str(parent.get("position_no")) or "position"
    price_match = EP_PRICE_PATTERN.search(alt_text)
    unit_price = _parse_euro_amount(price_match.group("amount") if price_match else None)
    metadata = dict(_metadata(parent))
    metadata["alternative_source"] = "embedded_long_text"
    metadata["main_line_item_id"] = parent_id

    item = dict(parent)
    item["id"] = f"{parent_id}:alt:{alt_index}"
    item["is_alternative"] = True
    item["description_short"] = _strip_price_tokens(alt_text)
    item["description_long"] = alt_text
    item["unit_price"] = unit_price
    item["line_total"] = None
    item["metadata_json"] = metadata
    item["image_ids_primary"] = []
    item["image_ids"] = []
    return item


def _alternative_group_label(item: dict[str, Any]) -> str | None:
    label = _strip_price_tokens(item.get("description_short"))
    if label:
        return label
    description_long = _strip_prices_from_long_text(item.get("description_long"))
    if description_long:
        for line in description_long.splitlines():
            cleaned = _strip_price_tokens(line)
            if cleaned:
                return cleaned
    return None


def _alternative_group_key(item: dict[str, Any]) -> str | None:
    label = _alternative_group_label(item)
    if not label:
        return None
    normalized_label = " ".join(_normalize_lookup_key(label).split())
    unit = _normalize_lookup_key(item.get("unit"))
    return f"{normalized_label}|{unit}" if normalized_label else None


def _line_total_for_item(item: dict[str, Any]) -> float | None:
    line_total = _to_float(item.get("line_total"))
    if line_total is not None:
        return line_total
    quantity = _to_float(item.get("quantity"))
    unit_price = _to_float(item.get("unit_price"))
    if quantity is None or unit_price is None:
        return None
    return quantity * unit_price


def _aggregate_append_alternatives(alternatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    passthrough: list[dict[str, Any]] = []

    for item in alternatives:
        key = _alternative_group_key(item)
        if not key:
            passthrough.append(item)
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    aggregated: list[dict[str, Any]] = []
    for group_index, key in enumerate(order, start=1):
        group_items = groups[key]
        if len(group_items) == 1:
            aggregated.append(group_items[0])
            continue

        first = group_items[0]
        label = _alternative_group_label(first) or _to_str(first.get("description_short")) or "Alternative"
        quantity_sum = sum((_to_float(item.get("quantity")) or 0.0) for item in group_items)
        total_values = [_line_total_for_item(item) for item in group_items]
        total_sum = sum(value for value in total_values if value is not None)
        has_total = any(value is not None for value in total_values)
        unit_price = (total_sum / quantity_sum) if has_total and quantity_sum else _to_float(first.get("unit_price"))
        source_ids = [_to_str(item.get("id")) for item in group_items if _to_str(item.get("id"))]
        source_positions = [_to_str(item.get("position_no")) for item in group_items if _to_str(item.get("position_no"))]
        metadata = dict(_metadata(first))
        metadata["alternative_source"] = "aggregated_append"
        metadata["alternative_group_source_count"] = len(group_items)
        metadata["alternative_group_source_ids"] = source_ids
        metadata["alternative_group_source_positions"] = source_positions

        detail_lines = [
            f"Gesammelte Alternative: {label}",
            f"Anzahl Quellpositionen: {len(group_items)}",
        ]
        for item in group_items:
            detail_lines.append(
                " / ".join(
                    part
                    for part in [
                        f"Quelle Pos. {_to_str(item.get('position_no'))}" if _to_str(item.get("position_no")) else None,
                        f"Menge {_to_float(item.get('quantity')):g}" if _to_float(item.get("quantity")) is not None else None,
                        f"EP {_to_float(item.get('unit_price')):.2f}" if _to_float(item.get("unit_price")) is not None else None,
                    ]
                    if part
                )
            )

        aggregate = dict(first)
        aggregate["id"] = f"aggregate:alt:{group_index}:{_normalize_lookup_key(label)[:48]}"
        aggregate["is_alternative"] = True
        aggregate["quantity"] = quantity_sum if quantity_sum else None
        aggregate["description_short"] = label
        aggregate["description_long"] = "\n".join(line for line in detail_lines if line)
        aggregate["unit_price"] = unit_price
        aggregate["line_total"] = total_sum if has_total else None
        aggregate["metadata_json"] = metadata
        aggregate["image_ids_primary"] = []
        aggregate["image_ids"] = []
        aggregated.append(aggregate)

    aggregated.extend(passthrough)
    return aggregated


def _prepare_line_items_for_export(line_items: list[Any], mode: str) -> tuple[list[dict[str, Any]], int]:
    normalized_mode = "append" if str(mode or "").strip().lower() == "append" else "nested"
    prepared: list[dict[str, Any]] = []
    append_alternatives: list[dict[str, Any]] = []
    parent_alt_counts: dict[str, int] = {}
    parent_position_no: str | None = None
    parent_index = 0
    embedded_alternative_count = 0
    existing_alternative_count = 0

    for raw_item in line_items:
        if not isinstance(raw_item, dict):
            continue

        item = dict(raw_item)
        is_alternative = _to_bool(item.get("is_alternative"))

        if not is_alternative:
            main_description, embedded_alternatives = _split_embedded_alternatives(item.get("description_long"))
            item["description_long"] = main_description
            parent_index += 1
            parent_position_no = str(parent_index)
            item["position_no"] = parent_position_no
            prepared.append(item)

            for alt_number, alt_text in enumerate(embedded_alternatives, start=1):
                alt_item = _embedded_alternative_item(item, alt_text, alt_number)
                embedded_alternative_count += 1
                parent_key = parent_position_no or str(parent_index)
                parent_alt_counts[parent_key] = parent_alt_counts.get(parent_key, 0) + 1
                if normalized_mode == "nested":
                    alt_item["position_no"] = _nested_position(parent_position_no, parent_index, parent_alt_counts[parent_key])
                    prepared.append(alt_item)
                else:
                    append_alternatives.append(alt_item)
            continue

        existing_alternative_count += 1
        parent_key = parent_position_no or _to_str(item.get("position_no")) or str(max(1, parent_index))
        parent_alt_counts[parent_key] = parent_alt_counts.get(parent_key, 0) + 1
        if normalized_mode == "nested":
            item["position_no"] = _nested_position(parent_position_no, parent_index, parent_alt_counts[parent_key])
            prepared.append(item)
        else:
            append_alternatives.append(item)

    if normalized_mode == "append" and append_alternatives:
        append_alternatives = _aggregate_append_alternatives(append_alternatives)
        next_position = len(prepared) + 1
        for alt_item in append_alternatives:
            alt_item["position_no"] = str(next_position)
            next_position += 1
        prepared.extend(append_alternatives)

    return prepared, embedded_alternative_count + existing_alternative_count


def _normalize_lookup_key(value: Any) -> str:
    text = _to_str(value) or ""
    lowered = text.lower().replace("&", " ")
    return "".join(ch if ch.isalnum() else " " for ch in lowered).strip()


def _supplier_id_for_document(document: dict[str, Any]) -> str | None:
    supplier_name = document.get("supplier_name")
    lookup = _normalize_lookup_key(supplier_name)
    if not lookup:
        return None
    if lookup in SUPPLIER_ID_ALIASES:
        return SUPPLIER_ID_ALIASES[lookup]
    collapsed = " ".join(lookup.split())
    if collapsed in SUPPLIER_ID_ALIASES:
        return SUPPLIER_ID_ALIASES[collapsed]
    for alias, supplier_id in SUPPLIER_ID_ALIASES.items():
        if alias and alias in collapsed:
            return supplier_id
    return None


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


def _datetime_value(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


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
            "image_bytes": None,
            "image_name": None,
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
            "image_bytes": None,
            "image_name": None,
            "image_is_primary": False,
        }

    storage_path = _to_str(image.get("storage_path"))
    image_bytes = None
    if storage_path:
        path = Path(storage_path)
        if path.exists() and path.is_file():
            image_bytes = path.read_bytes()
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
        "image_bytes": image_bytes,
        "image_name": _image_filename(document_id, line_item, image) if image_bytes is not None else None,
        "image_is_primary": image_bytes is not None,
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
    created_at = _datetime_value(exported_at)
    document = result_data.get("document") if isinstance(result_data.get("document"), dict) else {}
    raw_line_items = result_data.get("line_items") if isinstance(result_data.get("line_items"), list) else []
    alternative_position_mode = "append" if document.get("alternative_position_mode") == "append" else "nested"
    line_items, alternative_position_count = _prepare_line_items_for_export(raw_line_items, alternative_position_mode)
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
        "supplier_id": _supplier_id_for_document(document),
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
        "created_at": created_at,
        "subject": _to_str(document.get("project_ref")),
        "tax_type": None,
        "customer_id": _to_str(document.get("vendoc_customer_number")),
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
        description_short = _strip_price_tokens(raw_item.get("description_short"))
        description_long = _strip_prices_from_long_text(raw_item.get("description_long"))
        image_bytes = image_payload.pop("image_bytes", None)
        image_name = image_payload.pop("image_name", None)
        text_only_rtf = build_vendoc_long_text_rtf(description_long)
        image_only_rtf = None
        if isinstance(image_bytes, bytes):
            try:
                image_only_rtf = build_vendoc_long_text_rtf(
                    "",
                    image_bytes=image_bytes,
                    image_name=_to_str(image_name),
                )
            except Exception as exc:
                warnings.append(
                    {
                        "code": "image_only_rtf_failed",
                        "message": f"Could not build VenDoc image-only RTF: {exc}",
                        "line_item_id": raw_item.get("id"),
                        "position_no": raw_item.get("position_no"),
                    }
                )
                image_only_rtf = None

        try:
            image_long_text_rtf = build_vendoc_long_text_rtf(
                description_long,
                image_bytes=image_bytes if isinstance(image_bytes, bytes) else None,
                image_name=_to_str(image_name),
            )
        except Exception as exc:
            warnings.append(
                {
                    "code": "image_long_text_rtf_failed",
                    "message": f"Could not build VenDoc RTF long text: {exc}",
                    "line_item_id": raw_item.get("id"),
                    "position_no": raw_item.get("position_no"),
                }
            )
            image_payload["image_is_primary"] = False
            image_long_text_rtf = text_only_rtf
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
            "description_short": description_short,
            "description_long": description_long,
            "text_only_rtf": text_only_rtf,
            "image_long_text_rtf": image_long_text_rtf,
            "image_only_rtf": image_only_rtf,
            "unit_price": _to_float(raw_item.get("unit_price")),
            "page_ref": _to_str(raw_item.get("page_ref")),
            **image_payload,
            "created_at": created_at,
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
            "has_images": any(position.get("image_is_primary") for position in positions),
            "alternative_position_mode": alternative_position_mode,
            "alternative_position_count": alternative_position_count,
        },
    }
