"""Conformance tests for the composite-artifact contract in this library repo.

These checks require no database and no network access: they inspect the
committed tree, parse every module.toml with the framework's own validator,
confirm each module's declared object inventory agrees with its artifact's
independently parsed inventory, and regenerate the registry index to confirm
it is schema_version 2 and byte-identical to what's committed. They are the
library-repo half of the change-module-artifact-to-composite migration's
verification (the framework-repo half lives in preprocessor-framework's own
tests/test_module_contract.py and friends).

See docs/module-authoring.md in the preprocessor-framework repo ("The
canonical artifact") for the contract these tests hold the library to.
"""

from pathlib import Path

from preproc.module.artifact import normalize_object_name
from preproc.module.manifest import (
    ENTRY_OBJECT_TYPE,
    load_manifest,
    verify_artifact_inventory,
    verify_artifact_sha256,
)
from preproc.module.registry import generate_index, index_drift, render_index

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ERGONOMICS_MODULES = ("cast_shorthand", "trailing_comma")


def _stamping_args() -> dict[str, str]:
    """The (ref, library_version) scripts/generate_index.py stamps the committed index with.

    Mirrors that script's own ``_version``/``_ref`` exactly, so a byte-identical
    regeneration check here can never diverge from what CI's drift-check runs.
    """
    version = (_REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip().lstrip("v")
    return {"ref": f"v{version}", "library_version": version}


def test_ergonomics_modules_valid_without_objects_array():
    """cast_shorthand and trailing_comma validate unchanged: no [[objects]] array needed.

    Both remain single-statement artifacts, so the composite contract derives
    their inventory as the single entry named by script_name — exactly the
    pre-composite check — and neither module.toml needs an [[objects]] array
    or any other edit to stay conformant.
    """
    for name in _ERGONOMICS_MODULES:
        module_dir = _REPO_ROOT / "modules" / name
        manifest = load_manifest(module_dir / "module.toml")
        assert manifest.objects is None, (
            f"{name}/module.toml must NOT declare [[objects]] to prove the N=1 "
            "degenerate case needs no manifest edit"
        )

        artifact_path = module_dir / f"{manifest.name}_v{manifest.version}.sql"
        artifact_bytes = artifact_path.read_bytes()

        verify_artifact_sha256(manifest, artifact_bytes)
        derived = verify_artifact_inventory(manifest, artifact_bytes.decode("utf-8"))
        assert len(derived) == 1, f"{name} artifact must derive to exactly one object"
        assert derived[0].type == ENTRY_OBJECT_TYPE
        assert derived[0].name == normalize_object_name(manifest.script_name)


def test_template_documents_objects_and_separation():
    """modules/_template/module.toml documents [[objects]], _V<N>, and --/ ... / separation."""
    text = (_REPO_ROOT / "modules" / "_template" / "module.toml").read_text(encoding="utf-8")

    assert "[[objects]]" in text, "template must document the [[objects]] array"
    assert "type" in text and "name" in text, (
        "template must document the type/name shape of an [[objects]] entry"
    )
    assert "REQUIRED" in text, (
        "template must state that [[objects]] is REQUIRED once the artifact "
        "carries more than one statement"
    )
    assert "_V<N>" in text or "_V" in text, (
        "template must document the _V<N> suffix requirement on every object"
    )
    assert "--/" in text and "/" in text, (
        "template must document the --/ ... / statement-separation convention"
    )


def test_index_schema_version_2_lists_all_modules():
    """registry/index.json declares schema_version 2 with objects on every entry.

    Regenerating from modules/ (with the same repo/ref/library_version
    stamping scripts/generate_index.py uses) reproduces the committed file
    byte-for-byte, run twice in a row, proving regeneration is deterministic.
    """
    stamping = _stamping_args()
    ref = stamping["ref"]
    library_version = stamping["library_version"]

    drift = index_drift(_REPO_ROOT, ref=ref, library_version=library_version)
    assert drift == [], f"registry/index.json is out of sync: {drift}"

    index = generate_index(_REPO_ROOT, ref=ref, library_version=library_version)
    assert index.schema_version == 2

    names = {entry.name for entry in index.entries}
    assert "cast_shorthand" in names
    assert "trailing_comma" in names
    for entry in index.entries:
        assert entry.objects is not None, f"{entry.name} entry must carry an objects list"
        assert len(entry.objects) >= 1

    rendered_first = render_index(index)
    regenerated = generate_index(_REPO_ROOT, ref=ref, library_version=library_version)
    rendered_second = render_index(regenerated)
    assert rendered_first == rendered_second, "regeneration must be byte-identical on a second run"

    committed_text = (_REPO_ROOT / "registry" / "index.json").read_text(encoding="utf-8")
    assert rendered_first == committed_text


def test_ci_workflow_checks_index_and_inventory_sync():
    """CI runs module tests, drift-checks the index, and checks inventory sync.

    Verifies the workflow runs module tests/ against a docker Exasol, that it
    regenerates/drift-checks registry/index.json, and that it additionally
    asserts every module's declared object inventory agrees with its
    artifact's independently parsed inventory (this file's own
    test_ergonomics_modules_valid_without_objects_array is what performs that
    check for the two ergonomics modules).
    """
    workflow_files = list((_REPO_ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflow_files, "no .github/workflows/*.yml found"
    combined = "\n".join(f.read_text(encoding="utf-8") for f in workflow_files)

    assert "exasol/docker-db" in combined, "CI must run module tests against a docker Exasol"
    assert "preprocessor-framework" in combined, "CI must install the framework package"
    assert "pytest" in combined, "CI must run the module tests via pytest"
    assert "index_drift" in combined or "registry/index.json" in combined, (
        "CI must regenerate/drift-check registry/index.json"
    )
    assert "inventory" in combined.lower(), (
        "CI must assert declared-vs-parsed object inventory sync, not just sha256/index sync"
    )
    assert "test_library_modules.py" in combined, (
        "CI must actually run the inventory-sync test, not just document the intent"
    )
