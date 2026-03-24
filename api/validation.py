from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SUM_TOLERANCE = Decimal("0.02")
CONFIDENCE_AUTO_ACCEPT = Decimal("0.85")
CONFIDENCE_REVIEW = Decimal("0.60")


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


def _has_text(value: Any) -> bool:
    if value is None:
        return False
    return bool(str(value).strip())


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
    required_fields = {
        "supplier_name": _has_text(document.get("supplier_name")),
        "document_number": _has_text(document.get("document_number")),
        "document_date": document.get("document_date") is not None,
        "currency": _has_text(document.get("currency")),
        "gross_total": _to_decimal(document.get("gross_total")) is not None,
    }
    recommended_fields = {
        "project_ref": _has_text(document.get("project_ref")),
        "net_total": _to_decimal(document.get("net_total")) is not None,
        "vat_total": _to_decimal(document.get("vat_total")) is not None,
    }
    return required_fields, recommended_fields


def build_document_validation(
    *,
    document: dict[str, Any],
    amount_lines: list[dict[str, Any]],
    line_items: list[dict[str, Any]],
    images: list[dict[str, Any]],
) -> dict[str, Any]:
    document_issues: list[dict[str, Any]] = []
    required_fields, recommended_fields = _build_required_field_summary(document)

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

    net_total = _to_decimal(document.get("net_total"))
    vat_total = _to_decimal(document.get("vat_total"))
    gross_total = _to_decimal(document.get("gross_total"))

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
    discount_sum = Decimal("0.00")
    surcharge_sum = Decimal("0.00")

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
        elif quantity <= 0 and not is_alternative:
            issues.append(
                _make_issue(
                    code="non_positive_quantity",
                    severity="warning",
                    field="quantity",
                    message="Menge ist 0 oder negativ.",
                    actual=quantity,
                )
            )
        if unit_price is None:
            issues.append(
                _make_issue(
                    code="missing_unit_price",
                    severity="warning",
                    field="unit_price",
                    message="Einzelpreis fehlt.",
                )
            )
        if line_total is None and not is_alternative:
            issues.append(
                _make_issue(
                    code="missing_line_total",
                    severity="error",
                    field="line_total",
                    message="Positionsgesamtpreis fehlt.",
                )
            )
        elif line_total == 0 and not is_alternative:
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

        if quantity is not None and unit_price is not None and line_total is not None:
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
        item["validation_issue_count"] = len(issues)
        item["validation_status"] = _validation_status_from_issues(issues)

        if issues:
            line_items_with_issues += 1
            line_item_issue_count += len(issues)
            line_item_error_count += len([issue for issue in issues if issue.get("severity") == "error"])
            line_item_warning_count += len([issue for issue in issues if issue.get("severity") == "warning"])

        if line_total is not None and not is_alternative:
            non_alternative_item_sum += line_total

    for amount_line in amount_lines:
        amount = _to_decimal(amount_line.get("amount"))
        if amount is None:
            continue
        line_type = str(amount_line.get("line_type") or "").strip().lower()
        if line_type == "discount":
            discount_sum += amount
        elif line_type == "surcharge":
            surcharge_sum += amount

    computed_net_from_components = (non_alternative_item_sum + discount_sum + surcharge_sum).quantize(SUM_TOLERANCE)
    totals_summary["non_alternative_line_item_sum"] = non_alternative_item_sum.quantize(SUM_TOLERANCE)
    totals_summary["discount_sum"] = discount_sum.quantize(SUM_TOLERANCE)
    totals_summary["surcharge_sum"] = surcharge_sum.quantize(SUM_TOLERANCE)
    totals_summary["computed_net_from_components"] = computed_net_from_components

    if net_total is not None:
        totals_summary["net_delta_from_components"] = net_total - computed_net_from_components
        totals_summary["component_sum_matches_net"] = abs(net_total - computed_net_from_components) <= SUM_TOLERANCE
        if line_items and not totals_summary["component_sum_matches_net"]:
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

    confidence_policy = _confidence_policy(document.get("parse_confidence"))
    if confidence_policy.get("status") == "review":
        document_issues.append(
            _make_issue(
                code="confidence_review",
                severity="warning",
                field="parse_confidence",
                message="Parse-Confidence liegt im Review-Bereich.",
                actual=confidence_policy.get("value"),
            )
        )
    elif confidence_policy.get("status") == "reject":
        document_issues.append(
            _make_issue(
                code="confidence_low",
                severity="error",
                field="parse_confidence",
                message="Parse-Confidence ist zu niedrig fuer Auto-Accept.",
                actual=confidence_policy.get("value"),
            )
        )

    document_error_count = len([issue for issue in document_issues if issue.get("severity") == "error"])
    document_warning_count = len([issue for issue in document_issues if issue.get("severity") == "warning"])
    error_count = document_error_count + line_item_error_count
    warning_count = document_warning_count + line_item_warning_count

    if error_count > 0:
        status = "reject"
    elif warning_count > 0:
        status = "review"
    else:
        status = "auto_accept"

    return {
        "status": status,
        "issue_count": error_count + warning_count,
        "error_count": error_count,
        "warning_count": warning_count,
        "required_fields": required_fields,
        "recommended_fields": recommended_fields,
        "missing_required_fields": [field for field, present in required_fields.items() if not present],
        "missing_recommended_fields": [field for field, present in recommended_fields.items() if not present],
        "document_issues": document_issues,
        "confidence_policy": confidence_policy,
        "totals": totals_summary,
        "line_item_summary": {
            "total": len(line_items),
            "with_issues": line_items_with_issues,
            "issue_count": line_item_issue_count,
            "error_count": line_item_error_count,
            "warning_count": line_item_warning_count,
            "non_alternative_total_sum": non_alternative_item_sum.quantize(SUM_TOLERANCE),
        },
        "image_summary": {
            "total": len(images),
        },
    }
