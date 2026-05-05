import re
from dataclasses import dataclass
from typing import Any, Callable

from template_common import normalize_text
import template_alu_one
import template_entholzer
import template_koch
import template_koch_detail
import template_muigg
import template_newo
import template_rekord_vomp
import template_rieder
import template_schlotterer
import template_schachermayer
import template_sr_schauraum
import template_schuchter

HeaderFields = dict[str, str | None]


def _identity_headers(_: str, headers: HeaderFields) -> HeaderFields:
    return dict(headers)


def _no_document_notes(_: str) -> str | None:
    return None


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    supplier_name: str
    detector: Callable[[str], bool]
    count_positions: Callable[[str], int]
    extract_line_items: Callable[[str], list[dict[str, Any]]]
    refine_headers: Callable[[str, HeaderFields], HeaderFields] = _identity_headers
    extract_document_notes: Callable[[str], str | None] = _no_document_notes


TEMPLATES = (
    TemplateSpec(
        key="alu_one",
        supplier_name="alu-one Metallbaupartner GmbH",
        detector=template_alu_one.detect,
        count_positions=template_alu_one.count_positions,
        extract_line_items=template_alu_one.extract_line_items,
        refine_headers=template_alu_one.refine_headers,
    ),
    TemplateSpec(
        key="sr_schauraum",
        supplier_name="Lupre AI Solutions",
        detector=template_sr_schauraum.detect,
        count_positions=template_sr_schauraum.count_positions,
        extract_line_items=template_sr_schauraum.extract_line_items,
    ),
    TemplateSpec(
        key="rekord_vomp",
        supplier_name="Rekord Vomp GmbH",
        detector=template_rekord_vomp.detect,
        count_positions=template_rekord_vomp.count_positions,
        extract_line_items=template_rekord_vomp.extract_line_items,
        refine_headers=template_rekord_vomp.refine_headers,
    ),
    TemplateSpec(
        key="newo",
        supplier_name="NeWo",
        detector=template_newo.detect,
        count_positions=template_newo.count_positions,
        extract_line_items=template_newo.extract_line_items,
        refine_headers=template_newo.refine_headers,
    ),
    TemplateSpec(
        key="muigg",
        supplier_name="Muigg",
        detector=template_muigg.detect,
        count_positions=template_muigg.count_positions,
        extract_line_items=template_muigg.extract_line_items,
        refine_headers=template_muigg.refine_headers,
    ),
    TemplateSpec(
        key="entholzer",
        supplier_name="Entholzer",
        detector=template_entholzer.detect,
        count_positions=template_entholzer.count_positions,
        extract_line_items=template_entholzer.extract_line_items,
        refine_headers=template_entholzer.refine_headers,
    ),
    TemplateSpec(
        key="koch",
        supplier_name="Koch Türen GmbH",
        detector=template_koch.detect,
        count_positions=template_koch.count_positions,
        extract_line_items=template_koch.extract_line_items,
        refine_headers=template_koch.refine_headers,
        extract_document_notes=template_koch.extract_document_notes,
    ),
    TemplateSpec(
        key="koch_detail",
        supplier_name="Koch Türen GmbH",
        detector=template_koch_detail.detect,
        count_positions=template_koch_detail.count_positions,
        extract_line_items=template_koch_detail.extract_line_items,
        refine_headers=template_koch_detail.refine_headers,
    ),
    TemplateSpec(
        key="schachermayer",
        supplier_name="Schachermayer GmbH",
        detector=template_schachermayer.detect,
        count_positions=template_schachermayer.count_positions,
        extract_line_items=template_schachermayer.extract_line_items,
        refine_headers=template_schachermayer.refine_headers,
    ),
    TemplateSpec(
        key="rieder",
        supplier_name="Rieder",
        detector=template_rieder.detect,
        count_positions=template_rieder.count_positions,
        extract_line_items=template_rieder.extract_line_items,
        refine_headers=template_rieder.refine_headers,
    ),
    TemplateSpec(
        key="schuchter",
        supplier_name='SCHUCHTER Fenster GmbH',
        detector=template_schuchter.detect,
        count_positions=template_schuchter.count_positions,
        extract_line_items=template_schuchter.extract_line_items,
        refine_headers=template_schuchter.refine_headers,
    ),
    TemplateSpec(
        key="schlotterer",
        supplier_name="Schlotterer Sonnenschutz Systeme GmbH",
        detector=template_schlotterer.detect,
        count_positions=template_schlotterer.count_positions,
        extract_line_items=template_schlotterer.extract_line_items,
        refine_headers=template_schlotterer.refine_headers,
    ),
)

TEMPLATES_BY_KEY = {spec.key: spec for spec in TEMPLATES}


def detect_template(text: str) -> str:
    normalized_lower = normalize_text(text).lower()
    for spec in TEMPLATES:
        if spec.detector(normalized_lower):
            return spec.key
    return "generic"


def supplier_name_for_template(template: str) -> str | None:
    spec = TEMPLATES_BY_KEY.get(template)
    if spec is None:
        return None
    return spec.supplier_name


def count_positions(template: str, text: str) -> int:
    spec = TEMPLATES_BY_KEY.get(template)
    normalized_text = normalize_text(text)
    if spec is None:
        return len(re.findall(r"^Pos", normalized_text, flags=re.MULTILINE))
    return spec.count_positions(normalized_text)


def extract_line_items_for_template(text: str, template: str) -> list[dict[str, Any]]:
    spec = TEMPLATES_BY_KEY.get(template)
    if spec is None:
        return []
    return spec.extract_line_items(normalize_text(text))


def refine_headers_for_template(template: str, text: str, headers: HeaderFields) -> HeaderFields:
    spec = TEMPLATES_BY_KEY.get(template)
    normalized_text = normalize_text(text)
    if spec is None:
        return dict(headers)
    return spec.refine_headers(normalized_text, dict(headers))


def extract_document_notes_for_template(template: str, text: str) -> str | None:
    spec = TEMPLATES_BY_KEY.get(template)
    normalized_text = normalize_text(text)
    if spec is None:
        return None
    return spec.extract_document_notes(normalized_text)
