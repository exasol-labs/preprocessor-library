"""Static conformance tests for the preprocessor-library scaffolding itself.

These checks require no database and no network access: they inspect the
committed tree, parse every module.toml with the framework's own validator,
verify sha256s against the artifacts on disk, and regenerate the registry
index to confirm it is byte-identical to what's committed. They are the
library-repo half of the add-module-ecosystem migration's verification (the
framework-repo half is tests/test_ergonomics_migrated.py in
preprocessor-framework).
"""

from pathlib import Path

from _stamping import stamping_args

from preproc.module.manifest import (
    load_manifest,
    verify_artifact_inventory,
    verify_artifact_sha256,
)
from preproc.module.registry import generate_index, index_drift, render_index

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_library_top_level_structure():
    """The repo has every required top-level entry."""
    assert (_REPO_ROOT / "modules").is_dir()
    assert (_REPO_ROOT / "registry" / "index.json").is_file()
    assert (_REPO_ROOT / "registry" / "external").is_dir()
    assert (_REPO_ROOT / "CONTRIBUTING.md").is_file()
    assert (_REPO_ROOT / "README.md").is_file()

    workflows_dir = _REPO_ROOT / ".github" / "workflows"
    assert workflows_dir.is_dir()
    assert list(workflows_dir.glob("*.yml")) or list(workflows_dir.glob("*.yaml"))


def test_template_module_skeleton_present():
    """modules/_template/ has a module.toml and a placeholder artifact."""
    template_dir = _REPO_ROOT / "modules" / "_template"
    assert template_dir.is_dir()
    manifest_path = template_dir / "module.toml"
    assert manifest_path.is_file()

    manifest = load_manifest(manifest_path)
    artifact_path = template_dir / f"{manifest.name}_v{manifest.version}.sql"
    assert artifact_path.is_file(), (
        f"modules/_template/ must contain a placeholder artifact at {artifact_path.name}"
    )


def _assert_conformant_module(name: str, *, script_name: str, phase: str) -> None:
    """A modules/<name>/ directory has the standard layout and a valid manifest.

    ``phase`` is the phase THAT module declares, not a fixed one: the library
    hosts modules in every phase the contract admits (``TRANSLATE``, ``EXPAND``,
    ``REWRITE``), and the layout a module must have is identical in all of them.
    It stays a required argument rather than being read off the manifest so each
    caller still pins its own module's phase — a module silently changing phase
    is a behaviour change, not a layout one.
    """
    module_dir = _REPO_ROOT / "modules" / name
    assert module_dir.is_dir(), f"modules/{name}/ is missing"

    manifest_path = module_dir / "module.toml"
    assert manifest_path.is_file(), f"modules/{name}/module.toml is missing"
    assert (module_dir / "README.md").is_file(), f"modules/{name}/README.md is missing"
    assert (module_dir / "tests").is_dir(), f"modules/{name}/tests/ is missing"

    manifest = load_manifest(manifest_path)
    assert manifest.script_name == script_name
    assert manifest.phase == phase
    assert manifest.deploy_mode == "library-deployed"

    artifact_path = module_dir / f"{manifest.name}_v{manifest.version}.sql"
    assert artifact_path.is_file(), (
        f"modules/{name}/ declares deploy_mode=library-deployed but its artifact "
        f"{artifact_path.name} is missing"
    )
    artifact_bytes = artifact_path.read_bytes()
    verify_artifact_inventory(manifest, artifact_bytes.decode("utf-8"))
    verify_artifact_sha256(manifest, artifact_bytes)


def test_cast_shorthand_module_present_and_conformant():
    """cast_shorthand is a complete module with the expected script identity."""
    _assert_conformant_module(
        "cast_shorthand", script_name="PREPROC_RT.CAST_SHORTHAND_V1", phase="TRANSLATE"
    )


def test_trailing_comma_module_present_and_conformant():
    """trailing_comma is a complete module with the expected script identity."""
    _assert_conformant_module(
        "trailing_comma", script_name="PREPROC_RT.ERGONOMICS_TRAILING_COMMA_V2", phase="TRANSLATE"
    )


def test_every_module_has_the_layout_contributing_requires():
    """EVERY modules/<name>/ carries the README and tests/ CONTRIBUTING.md mandates.

    The two tests above pin the script identity of two NAMED modules, which is
    what makes them identity tests rather than layout tests. Neither says
    anything about a module added later: before this gate, a new module could
    merge with an empty README.md and no tests/ directory at all and every
    check in the repo — `preproc module validate` included — stayed green,
    while CONTRIBUTING.md step 4 and step 5 require both. A requirement no gate
    enforces is a suggestion.

    Every module in the tree is covered, `_template` included: the template is
    the shape an author copies, so it must satisfy the same layout it teaches.
    """
    module_dirs = sorted(p.parent for p in (_REPO_ROOT / "modules").glob("*/module.toml"))
    assert module_dirs, "no modules/*/module.toml found"

    failures: list[str] = []
    for module_dir in module_dirs:
        name = module_dir.name

        readme = module_dir / "README.md"
        if not readme.is_file():
            failures.append(f"modules/{name}/README.md is missing (CONTRIBUTING.md step 4)")
        elif not readme.read_text(encoding="utf-8").strip():
            failures.append(f"modules/{name}/README.md is empty (CONTRIBUTING.md step 4)")

        tests_dir = module_dir / "tests"
        if not tests_dir.is_dir():
            failures.append(f"modules/{name}/tests/ is missing (CONTRIBUTING.md step 5)")
        elif not list(tests_dir.glob("test_*.py")):
            failures.append(
                f"modules/{name}/tests/ contains no test_*.py (CONTRIBUTING.md step 5)"
            )

    assert not failures, "module layout does not match CONTRIBUTING.md:\n" + "\n".join(failures)


def test_every_library_deployed_module_sha_matches_its_artifact():
    """Every modules/*/module.toml with deploy_mode=library-deployed has a correct sha256."""
    module_dirs = sorted(p.parent for p in (_REPO_ROOT / "modules").glob("*/module.toml"))
    assert module_dirs, "no modules/*/module.toml found"

    for module_dir in module_dirs:
        manifest = load_manifest(module_dir / "module.toml")
        if manifest.deploy_mode != "library-deployed":
            continue
        artifact_path = module_dir / f"{manifest.name}_v{manifest.version}.sql"
        verify_artifact_sha256(manifest, artifact_path.read_bytes())


def test_index_lists_cast_shorthand_and_trailing_comma():
    """registry/index.json contains both migrated ergonomics modules."""
    index = generate_index(_REPO_ROOT)
    names = {entry.name for entry in index.entries}
    assert "cast_shorthand" in names
    assert "trailing_comma" in names


def test_index_regeneration_is_byte_identical_to_committed():
    """Regenerating registry/index.json from modules/ reproduces the committed file exactly."""
    stamping = stamping_args(_REPO_ROOT)
    ref = stamping["ref"]
    library_version = stamping["library_version"]

    drift = index_drift(_REPO_ROOT, ref=ref, library_version=library_version)
    assert drift == [], f"registry/index.json is out of sync: {drift}"

    fresh_text = render_index(generate_index(_REPO_ROOT, ref=ref, library_version=library_version))
    committed_text = (_REPO_ROOT / "registry" / "index.json").read_text(encoding="utf-8")
    assert fresh_text == committed_text


def test_ci_workflow_tests_modules_and_checks_index_sync():
    """The CI workflow runs module tests against a docker Exasol and drift-checks the index."""
    workflow_files = list((_REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflow_files, "no .github/workflows/*.yml found"
    combined = "\n".join(f.read_text(encoding="utf-8") for f in workflow_files)

    assert "exasol/docker-db" in combined, "CI must run module tests against a docker Exasol"
    assert "preprocessor-framework" in combined, "CI must install the framework package"
    assert "pytest" in combined, "CI must run the module tests via pytest"
    assert "index_drift" in combined or "registry/index.json" in combined, (
        "CI must regenerate/drift-check registry/index.json"
    )


def test_contributing_documents_both_paths():
    """CONTRIBUTING.md documents adding a module here AND registering an external repo."""
    text = (_REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "modules/" in text
    assert "module.toml" in text
    assert "registry/external" in text
    assert "self-deployed" in text or "external" in text.lower()
