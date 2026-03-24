import re
from dataclasses import dataclass
from typing import Any, Callable

from template_common import normalize_text
import template_alu_one
import template_entholzer
import template_newo
import template_rieder
import template_sr_schauraum


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    supplier_name: str
    detector: Callable[[str], bool]
    count_positions: Callable[[str], int]
    extract_line_items: Callable[[str], list[dict[str, Any]]]


TEMPLATES = (
    TemplateSpec(
        key="alu_one",
        supplier_name="alu-one Metallbaupartner GmbH",
        detector=template_alu_one.detect,
        count_positions=template_alu_one.count_positions,
        extract_line_items=template_alu_one.extract_line_items,
    ),
    TemplateSpec(
        key="sr_schauraum",
        supplier_name="Lupre AI Solutions",
        detector=template_sr_schauraum.detect,
        count_positions=template_sr_schauraum.count_positions,
        extract_line_items=template_sr_schauraum.extract_line_items,
    ),
    TemplateSpec(
        key="newo",
        supplier_name="NeWo",
        detector=template_newo.detect,
        count_positions=template_newo.count_positions,
        extract_line_items=template_newo.extract_line_items,
    ),
    TemplateSpec(
        key="entholzer",
        supplier_name="Entholzer",
        detector=template_entholzer.detect,
        count_positions=template_entholzer.count_positions,
        extract_line_items=template_entholzer.extract_line_items,
    ),
    TemplateSpec(
        key="rieder",
        supplier_name="Rieder",
        detector=template_rieder.detect,
        count_positions=template_rieder.count_positions,
        extract_line_items=template_rieder.extract_line_items,
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
