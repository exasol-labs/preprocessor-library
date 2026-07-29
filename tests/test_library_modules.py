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

import re
from pathlib import Path

from _stamping import stamping_args

from preproc.module.artifact import normalize_object_name
from preproc.module.manifest import (
    ENTRY_OBJECT_TYPE,
    ArtifactError,
    ModuleManifest,
    load_manifest,
    verify_artifact_inventory,
    verify_artifact_sha256,
)
from preproc.module.registry import generate_index, index_drift, render_index

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ERGONOMICS_MODULES = ("cast_shorthand", "trailing_comma")
_LIBRARY_DEPLOYED = "library-deployed"


def _shippable_modules() -> list[tuple[str, Path, ModuleManifest]]:
    """Every module the registry generator indexes: (directory name, directory, manifest).

    A ``_``-prefixed directory is skipped, exactly as
    ``preproc.module.registry._library_entries`` skips it: those are scaffolding,
    never installable through ``preproc module add``, and never in the
    operator-facing index — so they are not what the gates below are about
    (``modules/_template/`` has its own two tests in this file and in
    test_scaffolding.py).

    Enumerating the committed tree rather than naming modules is the whole point:
    adding a module to this library brings it under every gate built on this
    helper with no test edit, so a gate cannot silently stop covering a module
    someone forgot to add to a list.
    """
    modules = [
        (path.parent.name, path.parent, load_manifest(path))
        for path in sorted((_REPO_ROOT / "modules").glob("*/module.toml"))
        if not path.parent.name.startswith("_")
    ]
    assert modules, "no shippable modules/*/module.toml found"
    return modules


def _artifact_path(module_dir: Path, manifest: ModuleManifest) -> Path:
    """The standard-layout artifact path ``modules/<name>/<name>_v<N>.sql``."""
    return module_dir / f"{manifest.name}_v{manifest.version}.sql"


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

        artifact_bytes = _artifact_path(module_dir, manifest).read_bytes()

        verify_artifact_sha256(manifest, artifact_bytes)
        derived = verify_artifact_inventory(manifest, artifact_bytes.decode("utf-8"))
        assert len(derived) == 1, f"{name} artifact must derive to exactly one object"
        assert derived[0].type == ENTRY_OBJECT_TYPE
        assert derived[0].name == normalize_object_name(manifest.script_name)


def test_every_module_declared_inventory_matches_its_artifact():
    """Every shippable module's declared inventory agrees with its parsed artifact.

    Runs over the tree, not over a hardcoded pair, so a module is gated the
    moment it lands. ONE check covers both shapes the contract admits — a
    single-statement module with no ``[[objects]]`` and a composite one that
    declares its whole inventory — because ``verify_artifact_inventory`` is what
    decides which shape it is looking at (``[[objects]]`` is required only once
    the artifact carries more than one statement) and compares declared against
    parsed in BOTH directions either way.

    Nothing here asserts a statement count, an ``[[objects]]`` presence, or a
    phase: each of those legitimately differs per module, and asserting any of
    them would turn this gate into a filter that rejects one of the two legal
    shapes. The one kind-conditional part is the artifact itself — a
    ``self-deployed`` module ships none through the library (index generation
    reads no artifact for one, and its manifest carries no ``sha256``), so there
    is nothing to hash or parse and it is skipped rather than failed.

    Every module is checked before anything is reported, so one run names every
    stale module rather than only the first — the collect-then-raise discipline
    ``preproc.module.manifest`` applies to a single manifest, applied here across
    the library.
    """
    failures: list[str] = []
    for name, module_dir, manifest in _shippable_modules():
        if manifest.deploy_mode != _LIBRARY_DEPLOYED:
            continue
        artifact_path = _artifact_path(module_dir, manifest)
        if not artifact_path.is_file():
            failures.append(
                f"modules/{name}/ is {_LIBRARY_DEPLOYED} but its declared artifact "
                f"{artifact_path.name} is missing"
            )
            continue
        artifact_bytes = artifact_path.read_bytes()
        try:
            verify_artifact_sha256(manifest, artifact_bytes)
            verify_artifact_inventory(manifest, artifact_bytes.decode("utf-8"))
        except ArtifactError as error:
            failures.append(f"modules/{name}/: {error}")

    assert not failures, "declared inventory or sha256 disagrees with the artifact:\n" + "\n".join(
        failures
    )


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
    """registry/index.json declares schema_version 2 and lists every shippable module.

    Every module in the tree must appear, carrying the fields an operator's CLI
    resolves an install from — phase, entry script, function, sha256, artifact
    path — and the full object inventory its manifest declares (one entry for the
    N=1 fallback, all fifteen for a composite such as confd_control). The
    expected values are read back from each manifest rather than written out
    here, so this asserts agreement between the generator and the manifests
    instead of freezing today's module list.

    An entry's inventory is kind-conditional: no artifact travels through the
    registry for a ``self-deployed`` module, so such an entry carries no
    inventory at all and must not be asserted to have one.

    Regenerating from modules/ (with the same repo/ref/library_version stamping
    scripts/generate_index.py uses) reproduces the committed file byte-for-byte,
    run twice in a row, proving regeneration is deterministic.
    """
    stamping = stamping_args(_REPO_ROOT)
    ref = stamping["ref"]
    library_version = stamping["library_version"]

    drift = index_drift(_REPO_ROOT, ref=ref, library_version=library_version)
    assert drift == [], f"registry/index.json is out of sync: {drift}"

    index = generate_index(_REPO_ROOT, ref=ref, library_version=library_version)
    assert index.schema_version == 2

    manifests = {manifest.name: manifest for _name, _dir, manifest in _shippable_modules()}
    listed = {entry.name for entry in index.entries}
    assert manifests.keys() <= listed, (
        f"registry/index.json lists no entry for {sorted(manifests.keys() - listed)}"
    )

    for entry in index.entries:
        if entry.deploy_mode != _LIBRARY_DEPLOYED:
            assert entry.objects is None, (
                f"{entry.name} is {entry.deploy_mode}: no artifact travels through the "
                "registry for one, so it has nothing to inventory"
            )
            continue
        assert entry.objects is not None, f"{entry.name} entry must carry an objects list"
        assert len(entry.objects) >= 1

        manifest = manifests.get(entry.name)
        if manifest is None:
            continue
        assert entry.phase == manifest.phase
        assert entry.script_name == manifest.script_name
        assert entry.function == manifest.function
        assert entry.sha256 == manifest.sha256
        assert entry.artifact_path == (
            f"modules/{manifest.name}/{manifest.name}_v{manifest.version}.sql"
        )
        declared = 1 if manifest.objects is None else len(manifest.objects)
        assert len(entry.objects) == declared, (
            f"{entry.name} entry carries {len(entry.objects)} objects; "
            f"its manifest declares {declared}"
        )

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
    test_every_module_declared_inventory_matches_its_artifact is what performs
    that check, over every shippable module rather than a named few).
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
    # Must match a real run step, not prose. These workflows discuss the gates at
    # length in comments, so any substring search over the raw text is satisfied
    # by documentation alone — which is the very failure this assertion exists to
    # catch. Strip YAML comment lines first, then require an actual pytest
    # invocation: `pytest tests/` (the directory) subsumes the inventory gate and
    # picks up any gate added under tests/ later; an explicit file path counts too.
    executable = "\n".join(
        line for line in combined.splitlines() if not line.lstrip().startswith("#")
    )
    assert re.search(
        r"pytest\s+(?:-\S+\s+)*tests/(?:test_library_modules\.py)?(?:\s|$)", executable
    ), (
        "CI must actually run the inventory-sync gate — a run step invoking "
        "pytest over tests/ — not just document the intent in a comment"
    )


def test_release_workflow_gates_the_tag_against_the_committed_version():
    """A v* tag must be checked against ./VERSION before anything is published.

    The release workflow derives the tarball name from the TAG, while the
    registry/index.json inside that tarball is stamped from ./VERSION (see
    tests/_stamping.py). Nothing else reconciles the two, so a tag that
    disagrees with VERSION publishes a tarball, a GitHub Release and an index
    that all name different versions — and moves the mutable `latest` tag onto
    that state. This asserts the reconciling guard exists and runs on the tag
    event, before the build and publish steps.

    The guard belongs in the workflow rather than here: on a release-prep PR the
    matching tag does not exist yet, so a "the pinned ref resolves" assertion
    would fail on every such PR, and actions/checkout fetches no tags by default.
    """
    release_workflow = _REPO_ROOT / ".github" / "workflows" / "release.yml"
    assert release_workflow.exists(), "release.yml not found"
    text = release_workflow.read_text(encoding="utf-8")

    # Comment-stripped, for the same reason as the gate above: this file explains
    # the invariant at length in prose, and prose must not satisfy the assertion.
    executable = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))

    assert "VERSION" in executable, "the release workflow must read the committed VERSION"
    assert "GITHUB_REF_NAME" in executable, "the guard must compare against the tag name"
    assert re.search(r"exit\s+1", executable), (
        "the tag/VERSION guard must fail the build, not merely warn"
    )

    # The guard must run before the tarball is built, or a mismatched artifact is
    # produced (and possibly uploaded) before anyone notices.
    guard = executable.find("GITHUB_REF_NAME")
    build = executable.find("build_release.py")
    assert build != -1, "release.yml must build the tarball via scripts/build_release.py"
    assert guard < build, (
        "the tag/VERSION guard must precede the tarball build so a mismatch "
        "fails before any artifact is produced"
    )
