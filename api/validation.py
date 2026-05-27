import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from image_assignment import is_non_visual_line_item, metadata_review_state

SUM_TOLERANCE = Decimal("0.02")
CONFIDENCE_AUTO_ACCEPT = Decimal("0.85")
CONFIDENCE_REVIEW = Decimal("0.60")
COMPLEX_PRICING_TERMS = (
    "rabatt",
    "zuschlag",
    "teuerungszuschlag",
    "objektrabatt",
    "sonderrabatt",
    "händlerrabatt",
    "haendlerrabatt",
)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))

    text = str(value).strip()
    if not text:
        return None

    cleaned = text.upper().replace("EUR", "").replace("\u20ac", "")
    cleaned = cleaned.replace("−", "-").replace("–", "-").replace(" ", "")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_text(value: Any) -> bool:
    if value is None:
        return False
    return bool(str(value).strip())


def _normalized_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _make_issue(
    *,
    code: str,
    severity: str,
    message: str,
    field: str | None = None,
    expected: Any = None,
    actual: Any = None,
) -> dict[str, Any]:
    payload = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    if field is not None:
        payload["field"] = field
    if expected is not None:
        payload["expected"] = expected
    if actual is not None:
        payload["actual"] = actual
    return payload


def _validation_status_from_issues(issues: list[dict[str, Any]]) -> str:
    severities = {issue.get("severity") for issue in issues}
    if "error" in severities:
        return "reject"
    if "warning" in severities:
        return "review"
    return "auto_accept"


def _count_pages(raw_text_path: str | None) -> int | None:
    if not raw_text_path:
        return None
    path = Path(raw_text_path)
    if not path.exists() or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return None
    return stripped.count("\f") + 1


def _provider_key(document: dict[str, Any]) -> str:
    supplier_name = _normalized_text(document.get("supplier_name"))
    if supplier_name == "alu-one metallbaupartner gmbh":
        return "alu_one"
    if supplier_name == "entholzer":
        return "entholzer"
    if supplier_name == "lupre ai solutions":
        return "sr_schauraum"
    if supplier_name == "newo":
        return "newo"
    if supplier_name == "muigg":
        return "muigg"
    if supplier_name == "schachermayer gmbh":
        return "schachermayer"
    if supplier_name == "schlotterer sonnenschutz systeme gmbh":
        return "schlotterer"
    if supplier_name == "schuchter fenster gmbh":
        return "schuchter"
    if supplier_name == "rekord vomp gmbh":
        return "rekord_vomp"
    if supplier_name == "rieder":
        return "rieder"
    if supplier_name == "koch türen gmbh":
        return "koch"
    return supplier_name or "generic"


def _is_informational_item(provider_key: str, item: dict[str, Any]) -> bool:
    description = _normalized_text(item.get("description_short"))
    lv_pos = _normalized_text(item.get("lv_pos"))
    position_no = _normalized_text(item.get("position_no"))
    unit_price = _to_decimal(item.get("unit_price"))
    line_total = _to_decimal(item.get("line_total"))

    if provider_key == "alu_one":
        return (
            description == "vorbemerkungen"
            or description.startswith("info ")
            or (line_total == Decimal("0") and bool(re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", description)))
        )
    if provider_key == "entholzer":
        return lv_pos == "system" and unit_price is None and line_total is None
    if provider_key == "newo":
        return description.startswith("diese position")
    if provider_key == "rekord_vomp":
        return lv_pos == "umfang" or "summe-umfang" in description or "summe-rahmen" in description
    if provider_key == "schlotterer":
        return description == "auftragsinfo"
    if provider_key == "schuchter":
        return bool(re.fullmatch(r"\d+[a-z]", position_no)) and unit_price is None and line_total is None
    return False


def _counts_towards_component_sum(provider_key: str, item: dict[str, Any]) -> bool:
    description = _normalized_text(item.get("description_short"))
    if provider_key == "sr_schauraum":
        return True
    if provider_key == "alu_one" and description.startswith("az - "):
        return False
    if _is_informational_item(provider_key, item):
        return False
    return not bool(item.get("is_alternative"))


def _component_check_mode(provider_key: str, amount_lines: list[dict[str, Any]]) -> tuple[str, str | None]:
    discount_count = 0
    surcharge_count = 0
    subtotal_count = 0
    embedded_complexity = False

    for amount_line in amount_lines:
        line_type = _normalized_text(amount_line.get("line_type"))
        label_raw = _normalized_text(amount_line.get("label_raw"))
        if line_type == "discount":
            discount_count += 1
        elif line_type == "surcharge":
            surcharge_count += 1
        elif line_type == "subtotal":
            subtotal_count += 1
        if line_type not in {"discount", "surcharge"} and any(term in label_raw for term in COMPLEX_PRICING_TERMS):
            embedded_complexity = True

    if provider_key in {"entholzer", "rekord_vomp", "rieder", "schlotterer"}:
        return "heuristic", "provider_complex_pricing"
    if discount_count > 0 or surcharge_count > 0 or subtotal_count > 1 or embedded_complexity:
        return "heuristic", "complex_pricing_breakdown"
    return "strict", None


def _confidence_policy(parse_confidence: Any) -> dict[str, Any]:
    confidence = _to_decimal(parse_confidence)
    if confidence is None:
        return {"status": "unknown", "thresholds": {"auto_accept": "0.85", "review": "0.60"}}
    if confidence >= CONFIDENCE_AUTO_ACCEPT:
        status = "auto_accept"
    elif confidence >= CONFIDENCE_REVIEW:
        status = "review"
    else:
        status = "reject"
    return {
        "value": confidence,
        "status": status,
        "thresholds": {"auto_accept": "0.85", "review": "0.60"},
    }


def _build_required_field_summary(document: dict[str, Any]) -> tuple[dict[str, bool], dict[str, bool]]:
    document_type = _normalized_text(document.get("document_type"))
    provider_key = _provider_key(document)
    net_present = _to_decimal(document.get("net_total")) is not None
    koch_offer_net_only = (
        provider_key == "koch"
        and document_type == "angebot"
        and net_present
        and _to_decimal(document.get("vat_total")) is None
        and _to_decimal(document.get("gross_total")) is None
    )
    required_fields = {
        "supplier_name": _has_text(document.get("supplier_name")),
        "document_type": document_type in {"angebot", "auftragsbestaetigung"},
        "document_number": _has_text(document.get("document_number")),
        "document_date": document.get("document_date") is not None,
        "currency": _has_text(document.get("currency")),
        "gross_total": koch_offer_net_only or _to_decimal(document.get("gross_total")) is not None,
    }
    if document_type == "auftragsbestaetigung":
        required_fields["offer_reference"] = _has_text(document.get("offer_reference"))
    recommended_fields = {
        "project_ref": _has_text(document.get("project_ref")),
        "net_total": _to_decimal(document.get("net_total")) is not None,
        "vat_total": koch_offer_net_only or _to_decimal(document.get("vat_total")) is not None,
    }
    return required_fields, recommended_fields


def _item_status_from_issue_sets(
    open_issues: list[dict[str, Any]],
    resolved_issues: list[dict[str, Any]],
) -> str:
    status = _validation_status_from_issues(open_issues)
    if status == "auto_accept" and resolved_issues:
        return "manual_checked"
    return status


def build_document_validation(
    *,
    document: dict[str, Any],
    amount_lines: list[dict[str, Any]],
    line_items: list[dict[str, Any]],
    images: list[dict[str, Any]],
    enforce_image_validation: bool = False,
) -> dict[str, Any]:
    document_issues: list[dict[str, Any]] = []
    required_fields, recommended_fields = _build_required_field_summary(document)
    provider_key = _provider_key(document)
    document_type = _normalized_text(document.get("document_type"))
    net_total = _to_decimal(document.get("net_total"))
    vat_total = _to_decimal(document.get("vat_total"))
    gross_total = _to_decimal(document.get("gross_total"))
    koch_offer_net_only = (
        provider_key == "koch"
        and document_type == "angebot"
        and net_total is not None
        and vat_total is None
        and gross_total is None
    )
    field_policies: dict[str, dict[str, Any]] = {}
    if koch_offer_net_only:
        field_policies["gross_total"] = {
            "level": "optional",
            "status": "not_expected",
            "reason": "koch_offer_net_only",
        }
        field_policies["vat_total"] = {
            "level": "optional",
            "status": "not_expected",
            "reason": "koch_offer_net_only",
        }
    component_check_mode, component_check_reason = _component_check_mode(provider_key, amount_lines)

    if (
        enforce_image_validation
        and provider_key == "koch"
        and document_type in {"angebot", "auftragsbestaetigung"}
        and line_items
        and not images
    ):
        document_issues.append(
            _make_issue(
                code="koch_detail_drawings_missing",
                severity="warning",
                field="images",
                message="Koch-Dokument hat keine Detailzeichnungen im Haupt-PDF. Zusatz-PDFs mit Zeichnungen sollten dem Dokumentpaket zugeordnet werden.",
            )
        )

    if document_type not in {"angebot", "auftragsbestaetigung"}:
        document_issues.append(
            _make_issue(
                code="invalid_document_type",
                severity="error",
                field="document_type",
                message="Dokumenttyp ist unbekannt oder fehlt.",
                actual=document.get("document_type"),
            )
        )

    for field_name, present in required_fields.items():
        if not present:
            document_issues.append(
                _make_issue(
                    code=f"missing_{field_name}",
                    severity="error",
                    field=field_name,
                    message=f"Pflichtfeld {field_name} fehlt.",
                )
            )

    for field_name, present in recommended_fields.items():
        if not present:
            document_issues.append(
                _make_issue(
                    code=f"missing_{field_name}",
                    severity="warning",
                    field=field_name,
                    message=f"Empfohlenes Feld {field_name} fehlt.",
                )
            )

    totals_summary: dict[str, Any] = {
        "tolerance": SUM_TOLERANCE,
        "net_total": net_total,
        "vat_total": vat_total,
        "gross_total": gross_total,
    }
    if net_total is not None and vat_total is not None and gross_total is not None:
        expected_gross = (net_total + vat_total).quantize(SUM_TOLERANCE)
        totals_summary["computed_gross_from_net_vat"] = expected_gross
        totals_summary["gross_delta"] = gross_total - expected_gross
        totals_summary["net_plus_vat_matches_gross"] = abs(gross_total - expected_gross) <= SUM_TOLERANCE
        if not totals_summary["net_plus_vat_matches_gross"]:
            document_issues.append(
                _make_issue(
                    code="gross_mismatch",
                    severity="error",
                    field="gross_total",
                    message="Netto + USt stimmt nicht mit Brutto ueberein.",
                    expected=expected_gross,
                    actual=gross_total,
                )
            )
    else:
        totals_summary["net_plus_vat_matches_gross"] = None

    page_count = _count_pages(document.get("raw_text_path"))
    if page_count is not None:
        totals_summary["page_count"] = page_count

    non_alternative_item_sum = Decimal("0.00")
    component_item_sum = Decimal("0.00")
    discount_sum = Decimal("0.00")
    surcharge_sum = Decimal("0.00")
    image_page_by_id: dict[int, int] = {}
    for image in images:
        try:
            image_id = int(image.get("id"))
            image_page = int(image.get("page_ref"))
        except (TypeError, ValueError):
            continue
        image_page_by_id[image_id] = image_page

    line_item_issue_count = 0
    line_item_error_count = 0
    line_item_warning_count = 0
    line_items_with_issues = 0

    for item in line_items:
        issues: list[dict[str, Any]] = []
        quantity = _to_decimal(item.get("quantity"))
        unit_price = _to_decimal(item.get("unit_price"))
        line_total = _to_decimal(item.get("line_total"))
        is_alternative = bool(item.get("is_alternative"))
        page_ref = item.get("page_ref")
        is_informational_item = _is_informational_item(provider_key, item)
        counts_towards_component_sum = _counts_towards_component_sum(provider_key, item)
        is_visual_item = not is_non_visual_line_item(item) and not is_informational_item
        image_auto_match_allowed = item.get("image_auto_match_allowed") is not False

        if not _has_text(item.get("position_no")):
            issues.append(
                _make_issue(
                    code="missing_position_no",
                    severity="error",
                    field="position_no",
                    message="Positionsnummer fehlt.",
                )
            )
        if not _has_text(item.get("description_short")):
            issues.append(
                _make_issue(
                    code="missing_description_short",
                    severity="warning",
                    field="description_short",
                    message="Kurzbeschreibung fehlt.",
                )
            )
        if quantity is None:
            issues.append(
                _make_issue(
                    code="missing_quantity",
                    severity="warning",
                    field="quantity",
                    message="Menge fehlt.",
                )
            )
        elif quantity <= 0 and not is_alternative and not is_informational_item:
            issues.append(
                _make_issue(
                    code="non_positive_quantity",
                    severity="warning",
                    field="quantity",
                    message="Menge ist 0 oder negativ.",
                    actual=quantity,
                )
            )
        if unit_price is None and not is_informational_item:
            issues.append(
                _make_issue(
                    code="missing_unit_price",
                    severity="warning",
                    field="unit_price",
                    message="Einzelpreis fehlt.",
                )
            )
        if line_total is None and not is_alternative and not is_informational_item:
            issues.append(
                _make_issue(
                    code="missing_line_total",
                    severity="error",
                    field="line_total",
                    message="Positionsgesamtpreis fehlt.",
                )
            )
        elif line_total == 0 and not is_alternative and not is_informational_item:
            issues.append(
                _make_issue(
                    code="zero_line_total",
                    severity="warning",
                    field="line_total",
                    message="Positionsgesamtpreis ist 0,00.",
                )
            )

        if page_ref is None:
            issues.append(
                _make_issue(
                    code="missing_page_ref",
                    severity="warning",
                    field="page_ref",
                    message="Seitenreferenz fehlt.",
                )
            )
        elif page_count is not None and (not isinstance(page_ref, int) or page_ref < 1 or page_ref > page_count):
            issues.append(
                _make_issue(
                    code="invalid_page_ref",
                    severity="error",
                    field="page_ref",
                    message="Seitenreferenz liegt ausserhalb des Dokuments.",
                    expected=f"1..{page_count}",
                    actual=page_ref,
                )
            )

        assigned_image_ids: list[int] = []
        raw_image_ids = item.get("image_ids")
        if isinstance(raw_image_ids, list):
            for value in raw_image_ids:
                try:
                    assigned_image_ids.append(int(value))
                except (TypeError, ValueError):
                    continue
        assigned_image_ids = list(dict.fromkeys(assigned_image_ids))
        if is_visual_item and image_auto_match_allowed and (images or enforce_image_validation) and not assigned_image_ids:
            issues.append(
                _make_issue(
                    code="missing_image_assignment",
                    severity="warning",
                    field="image_ids",
                    message="Für diese Position ist noch kein finales Bild zugeordnet.",
                )
            )
        skip_same_document_page_check = item.get("image_assignment_source") == "document_package"
        if isinstance(page_ref, int) and not skip_same_document_page_check:
            preceding_pages = [
                image_page
                for image_page in (image_page_by_id.get(image_id) for image_id in assigned_image_ids)
                if image_page is not None and image_page < page_ref
            ]
            if preceding_pages:
                issues.append(
                    _make_issue(
                        code="image_before_item_page",
                        severity="warning",
                        field="image_ids",
                        message="Ein zugeordnetes Bild liegt auf einer frueheren Seite als die Position.",
                        expected=page_ref,
                        actual=min(preceding_pages),
                    )
                )

        if (
            component_check_mode == "strict"
            and quantity is not None
            and unit_price is not None
            and line_total is not None
            and not is_informational_item
        ):
            expected_line_total = (quantity * unit_price).quantize(SUM_TOLERANCE)
            if abs(line_total - expected_line_total) > SUM_TOLERANCE:
                issues.append(
                    _make_issue(
                        code="line_total_mismatch",
                        severity="warning",
                        field="line_total",
                        message="Menge x Einzelpreis stimmt nicht mit Positionssumme ueberein.",
                        expected=expected_line_total,
                        actual=line_total,
                    )
                )

        item["validation_issues"] = issues
        item["validation_total_issue_count"] = len(issues)

        if line_total is not None and not is_alternative:
            non_alternative_item_sum += line_total
        if line_total is not None and counts_towards_component_sum:
            component_item_sum += line_total

    image_to_positions: dict[int, list[str]] = {}
    for item in line_items:
        position_no = str(item.get("position_no") or "").strip()
        raw_image_ids = item.get("image_ids")
        if not position_no or not isinstance(raw_image_ids, list):
            continue
        for value in raw_image_ids:
            try:
                image_id = int(value)
            except (TypeError, ValueError):
                continue
            image_to_positions.setdefault(image_id, [])
            if position_no not in image_to_positions[image_id]:
                image_to_positions[image_id].append(position_no)

    duplicate_image_assignments: dict[int, list[str]] = {}
    for image_id, position_nos in image_to_positions.items():
        if len(position_nos) <= 1:
            continue
        duplicate_items = [
            item
            for item in line_items
            if image_id in [
                parsed
                for parsed in (_to_int(value) for value in (item.get("image_ids") or []))
                if parsed is not None
            ]
        ]
        duplicate_image_assignments[image_id] = position_nos
    if duplicate_image_assignments:
        duplicate_summary = ", ".join(
            f"#{image_id} -> Pos. {', '.join(position_nos[:3])}{' +' + str(len(position_nos) - 3) if len(position_nos) > 3 else ''}"
            for image_id, position_nos in list(duplicate_image_assignments.items())[:4]
        )
        document_issues.append(
            _make_issue(
                code="duplicate_image_assignments",
                severity="error",
                field="image_ids",
                message=f"Mindestens ein finales Bild ist mehrfach zugeordnet ({duplicate_summary}).",
            )
        )
        for item in line_items:
            raw_image_ids = item.get("image_ids")
            if not isinstance(raw_image_ids, list):
                continue
            duplicate_ids_for_item: list[int] = []
            for value in raw_image_ids:
                try:
                    image_id = int(value)
                except (TypeError, ValueError):
                    continue
                if image_id in duplicate_image_assignments:
                    duplicate_ids_for_item.append(image_id)
            duplicate_ids_for_item = list(dict.fromkeys(duplicate_ids_for_item))
            if not duplicate_ids_for_item:
                continue
            item_issues = item.get("validation_issues")
            if not isinstance(item_issues, list):
                item_issues = []
                item["validation_issues"] = item_issues
            duplicate_descriptions = ", ".join(
                f"#{image_id} (Pos. {', '.join(duplicate_image_assignments[image_id][:3])}{' +' + str(len(duplicate_image_assignments[image_id]) - 3) if len(duplicate_image_assignments[image_id]) > 3 else ''})"
                for image_id in duplicate_ids_for_item
            )
            item_issues.append(
                _make_issue(
                    code="duplicate_image_assignment",
                    severity="error",
                    field="image_ids",
                    message=f"Bild mehrfach zugeordnet: {duplicate_descriptions}.",
                )
            )
            item["validation_issue_count"] = len(item_issues)
            item["validation_status"] = _validation_status_from_issues(item_issues)

    line_item_issue_count = 0
    line_item_error_count = 0
    line_item_warning_count = 0
    line_items_with_issues = 0
    line_items_with_resolved_issues = 0
    line_items_manually_checked = 0
    resolved_warning_count = 0
    for item in line_items:
        issues = item.get("validation_issues")
        if not isinstance(issues, list):
            issues = []
            item["validation_issues"] = issues
        review_state = metadata_review_state(item)
        review_checked = bool(item.get("review_checked") is True or review_state.get("checked"))
        review_checked_at = item.get("review_checked_at") or review_state.get("checked_at")
        review_checked_reason = item.get("review_checked_reason") or review_state.get("reason")

        annotated_issues: list[dict[str, Any]] = []
        open_issues: list[dict[str, Any]] = []
        resolved_issues: list[dict[str, Any]] = []
        for issue in issues:
            annotated_issue = dict(issue)
            if review_checked and annotated_issue.get("severity") == "warning":
                annotated_issue["resolved_by_review"] = True
                annotated_issue["resolved_at"] = review_checked_at
                annotated_issue["resolved_reason"] = review_checked_reason or "manual_review"
                resolved_issues.append(annotated_issue)
            else:
                open_issues.append(annotated_issue)
            annotated_issues.append(annotated_issue)

        item["review_checked"] = review_checked
        item["review_checked_at"] = review_checked_at
        item["review_checked_reason"] = review_checked_reason
        item["validation_issues"] = annotated_issues
        item["validation_open_issues"] = open_issues
        item["validation_resolved_issues"] = resolved_issues
        item["validation_total_issue_count"] = len(annotated_issues)
        item["validation_issue_count"] = len(open_issues)
        item["validation_open_issue_count"] = len(open_issues)
        item["validation_resolved_issue_count"] = len(resolved_issues)
        item["validation_status"] = _item_status_from_issue_sets(open_issues, resolved_issues)

        if resolved_issues:
            line_items_with_resolved_issues += 1
        if review_checked:
            line_items_manually_checked += 1
        resolved_warning_count += len(
            [issue for issue in resolved_issues if issue.get("severity") == "warning"]
        )

        if not open_issues:
            continue
        line_items_with_issues += 1
        line_item_issue_count += len(open_issues)
        line_item_error_count += len([issue for issue in open_issues if issue.get("severity") == "error"])
        line_item_warning_count += len([issue for issue in open_issues if issue.get("severity") == "warning"])

    for amount_line in amount_lines:
        amount = _to_decimal(amount_line.get("amount"))
        if amount is None:
            continue
        line_type = str(amount_line.get("line_type") or "").strip().lower()
        if line_type == "discount":
            discount_sum += amount
        elif line_type == "surcharge":
            surcharge_sum += amount

    computed_net_from_components = (component_item_sum + discount_sum + surcharge_sum).quantize(SUM_TOLERANCE)
    totals_summary["non_alternative_line_item_sum"] = non_alternative_item_sum.quantize(SUM_TOLERANCE)
    totals_summary["component_included_line_item_sum"] = component_item_sum.quantize(SUM_TOLERANCE)
    totals_summary["discount_sum"] = discount_sum.quantize(SUM_TOLERANCE)
    totals_summary["surcharge_sum"] = surcharge_sum.quantize(SUM_TOLERANCE)
    totals_summary["computed_net_from_components"] = computed_net_from_components
    totals_summary["component_check_mode"] = component_check_mode
    if component_check_reason is not None:
        totals_summary["component_check_reason"] = component_check_reason

    if net_total is not None:
        totals_summary["net_delta_from_components"] = net_total - computed_net_from_components
        totals_summary["component_sum_matches_net"] = abs(net_total - computed_net_from_components) <= SUM_TOLERANCE
        if line_items and component_check_mode == "strict" and not totals_summary["component_sum_matches_net"]:
            document_issues.append(
                _make_issue(
                    code="net_component_mismatch",
                    severity="warning",
                    field="net_total",
                    message="Positionen plus Zu-/Abschlaege stimmen nicht mit Nettosumme ueberein.",
                    expected=computed_net_from_components,
                    actual=net_total,
                )
            )
    else:
        totals_summary["component_sum_matches_net"] = None

    # Diagnostic only: release decisions use concrete field, total, position and image checks.
    confidence_policy = _confidence_policy(document.get("parse_confidence"))

    document_error_count = len([issue for issue in document_issues if issue.get("severity") == "error"])
    document_warning_count = len([issue for issue in document_issues if issue.get("severity") == "warning"])
    error_count = document_error_count + line_item_error_count
    warning_count = document_warning_count + line_item_warning_count

    if error_count > 0:
        status = "reject"
    elif warning_count > 0:
        status = "review"
    elif resolved_warning_count > 0:
        status = "manual_checked"
    else:
        status = "auto_accept"

    approval_status = _normalized_text(document.get("approval_status")) or "pending"
    approval_eligible = status in {"auto_accept", "manual_checked"}
    approval_reviewed_by = document.get("reviewed_by")
    approval_reviewed_at = document.get("reviewed_at")
    approval_note = document.get("approval_note")

    return {
        "status": status,
        "issue_count": error_count + warning_count,
        "error_count": error_count,
        "warning_count": warning_count,
        "required_fields": required_fields,
        "recommended_fields": recommended_fields,
        "field_policies": field_policies,
        "missing_required_fields": [field for field, present in required_fields.items() if not present],
        "missing_recommended_fields": [field for field, present in recommended_fields.items() if not present],
        "document_issues": document_issues,
        "confidence_policy": confidence_policy,
        "totals": totals_summary,
        "line_item_summary": {
            "total": len(line_items),
            "with_issues": line_items_with_issues,
            "with_resolved_issues": line_items_with_resolved_issues,
            "manual_checked_count": line_items_manually_checked,
            "issue_count": line_item_issue_count,
            "error_count": line_item_error_count,
            "warning_count": line_item_warning_count,
            "resolved_warning_count": resolved_warning_count,
            "non_alternative_total_sum": non_alternative_item_sum.quantize(SUM_TOLERANCE),
            "component_included_total_sum": component_item_sum.quantize(SUM_TOLERANCE),
        },
        "image_summary": {
            "total": len(images),
            "assigned_duplicate_count": len(duplicate_image_assignments),
            "assigned_duplicate_images": sorted(duplicate_image_assignments.keys()),
        },
        "approval": {
            "status": approval_status,
            "approved": approval_status == "approved",
            "eligible": approval_eligible,
            "reviewed_by": approval_reviewed_by,
            "reviewed_at": approval_reviewed_at,
            "approval_note": approval_note,
        },
    }
