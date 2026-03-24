import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def _load_provider_scaffold_module():
    module_path = ROOT / "infra" / "provider_scaffold.py"
    spec = importlib.util.spec_from_file_location("provider_scaffold", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_provider_scaffold_creates_template_dirs_and_registry_entry(tmp_path: Path) -> None:
    module = _load_provider_scaffold_module()
    repo_root = tmp_path / "repo"
    registry_target = repo_root / "api" / "template_registry.py"
    registry_target.parent.mkdir(parents=True, exist_ok=True)
    registry_target.write_text((ROOT / "api" / "template_registry.py").read_text(encoding="utf-8"), encoding="utf-8")

    module.scaffold_provider(repo_root, "muster_anbieter", "Muster Anbieter GmbH")

    template_path = repo_root / "api" / "template_muster_anbieter.py"
    regression_dir = repo_root / "samples" / "pdfs" / "regression" / "offers" / "muster_anbieter"
    candidate_dir = repo_root / "samples" / "pdfs" / "candidates" / "offers" / "muster_anbieter"
    onboarding_doc = repo_root / "samples" / "providers" / "muster_anbieter" / "ONBOARDING.md"
    patched_registry = registry_target.read_text(encoding="utf-8")

    assert template_path.exists()
    assert regression_dir.joinpath(".gitkeep").exists()
    assert candidate_dir.joinpath(".gitkeep").exists()
    assert onboarding_doc.exists()
    assert "def detect(normalized_lower: str) -> bool:" in template_path.read_text(encoding="utf-8")
    assert 'import template_muster_anbieter' in patched_registry
    assert 'key="muster_anbieter"' in patched_registry
    assert "Muster Anbieter GmbH" in patched_registry
