#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class ProviderPaths:
    repo_root: Path
    provider_slug: str

    @property
    def template_module(self) -> Path:
        return self.repo_root / "api" / f"template_{self.provider_slug}.py"

    @property
    def registry(self) -> Path:
        return self.repo_root / "api" / "template_registry.py"

    @property
    def regression_dir(self) -> Path:
        return self.repo_root / "samples" / "pdfs" / "regression" / "offers" / self.provider_slug

    @property
    def candidate_dir(self) -> Path:
        return self.repo_root / "samples" / "pdfs" / "candidates" / "offers" / self.provider_slug

    @property
    def onboarding_doc(self) -> Path:
        return self.repo_root / "samples" / "providers" / self.provider_slug / "ONBOARDING.md"


def _validate_slug(provider_slug: str) -> None:
    if not SLUG_RE.fullmatch(provider_slug):
        raise ValueError("provider slug must match ^[a-z][a-z0-9_]*$")


def render_template_module(provider_slug: str) -> str:
    return f"""import re
from typing import Any

from template_common import normalize_text


def detect(normalized_lower: str) -> bool:
    return "todo-{provider_slug}" in normalized_lower


def count_positions(text: str) -> int:
    return 0


def refine_headers(normalized_text: str, headers: dict[str, str | None]) -> dict[str, str | None]:
    return dict(headers)


def extract_line_items(text: str) -> list[dict[str, Any]]:
    normalized_text = normalize_text(text)
    items: list[dict[str, Any]] = []

    # TODO: replace the placeholder detector and implement provider-specific parsing.
    _ = normalized_text
    return items
"""


def render_onboarding_doc(provider_slug: str, supplier_name: str) -> str:
    return f"""# Provider Onboarding: {supplier_name}

Provider key: `{provider_slug}`

## Created paths
- `api/template_{provider_slug}.py`
- `samples/pdfs/regression/offers/{provider_slug}/`
- `samples/pdfs/candidates/offers/{provider_slug}/`

## Next steps
1. Put 1 to 3 canonical offer PDFs into `samples/pdfs/regression/offers/{provider_slug}/`.
2. Put extra variants into `samples/pdfs/candidates/offers/{provider_slug}/`.
3. Replace the placeholder detector and parsing logic in `api/template_{provider_slug}.py`.
4. Add exact expectations for the new provider to `tests/test_offer_corpus_smoke.py`.
5. Add a stronger canonical regression to `tests/test_template_regression.py`.
6. Update `samples/OFFER_PROVIDER_MATRIX.md` after the provider is green.

## Verification
```bash
python -m pytest tests/test_template_regression.py tests/test_offer_corpus_smoke.py -q
./infra/api-canary.sh
```
"""


def patch_template_registry(registry_text: str, provider_slug: str, supplier_name: str) -> str:
    module_name = f"template_{provider_slug}"
    import_line = f"import {module_name}\n"

    if import_line not in registry_text:
        lines = registry_text.splitlines(keepends=True)
        insert_after = max(idx for idx, line in enumerate(lines) if line.startswith("import template_"))
        lines.insert(insert_after + 1, import_line)
        registry_text = "".join(lines)

    if f'key="{provider_slug}"' in registry_text:
        return registry_text

    spec_block = (
        "    TemplateSpec(\n"
        f'        key="{provider_slug}",\n'
        f"        supplier_name={supplier_name!r},\n"
        f"        detector={module_name}.detect,\n"
        f"        count_positions={module_name}.count_positions,\n"
        f"        extract_line_items={module_name}.extract_line_items,\n"
        f"        refine_headers={module_name}.refine_headers,\n"
        "    ),\n"
    )
    needle = "\n)\n\nTEMPLATES_BY_KEY ="
    if needle not in registry_text:
        raise ValueError("template_registry.py does not contain the expected TEMPLATES block terminator")
    return registry_text.replace(needle, f"\n{spec_block})\n\nTEMPLATES_BY_KEY =", 1)


def scaffold_provider(repo_root: Path, provider_slug: str, supplier_name: str, *, force: bool = False) -> ProviderPaths:
    _validate_slug(provider_slug)
    paths = ProviderPaths(repo_root=repo_root, provider_slug=provider_slug)

    if not paths.registry.exists():
        raise FileNotFoundError(f"template registry not found: {paths.registry}")
    if paths.template_module.exists() and not force:
        raise FileExistsError(f"template module already exists: {paths.template_module}")

    paths.template_module.parent.mkdir(parents=True, exist_ok=True)
    paths.regression_dir.mkdir(parents=True, exist_ok=True)
    paths.candidate_dir.mkdir(parents=True, exist_ok=True)
    paths.onboarding_doc.parent.mkdir(parents=True, exist_ok=True)

    paths.template_module.write_text(render_template_module(provider_slug), encoding="utf-8")
    (paths.regression_dir / ".gitkeep").write_text("", encoding="utf-8")
    (paths.candidate_dir / ".gitkeep").write_text("", encoding="utf-8")
    paths.onboarding_doc.write_text(render_onboarding_doc(provider_slug, supplier_name), encoding="utf-8")

    registry_text = paths.registry.read_text(encoding="utf-8")
    patched_registry = patch_template_registry(registry_text, provider_slug, supplier_name)
    paths.registry.write_text(patched_registry, encoding="utf-8")
    return paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scaffold a new PDF provider template.")
    parser.add_argument("provider_slug", help="provider key, for example alu_one")
    parser.add_argument("supplier_name", help="supplier display name")
    parser.add_argument("--repo-root", default=None, help="override repo root for testing")
    parser.add_argument("--force", action="store_true", help="overwrite an existing template module")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]

    try:
        paths = scaffold_provider(repo_root, args.provider_slug, args.supplier_name, force=args.force)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        parser.error(str(exc))

    print(f"[ok] provider scaffold created: {args.provider_slug}")
    print(f" - template: {paths.template_module.relative_to(repo_root)}")
    print(f" - regression dir: {paths.regression_dir.relative_to(repo_root)}")
    print(f" - candidate dir: {paths.candidate_dir.relative_to(repo_root)}")
    print(f" - onboarding doc: {paths.onboarding_doc.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
