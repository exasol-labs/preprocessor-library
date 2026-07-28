"""Tests for the _template placeholder module.

Copy this file alongside your own module's artifact and replace these tests
with your module's real scenarios. What's demonstrated here is the minimum
shape every module's tests/ directory needs: a static manifest/artifact
conformance check (no DB required) and one integration test that deploys the
artifact and calls its entry function through a thin harness script.
"""

from pathlib import Path

import pytest

from preproc.module.manifest import (
    load_manifest,
    verify_artifact_inventory,
    verify_artifact_sha256,
)

_MODULE_DIR = Path(__file__).resolve().parents[1]
_ARTIFACT = _MODULE_DIR / "my_module_v1.sql"
_MANIFEST = _MODULE_DIR / "module.toml"


def test_template_manifest_and_artifact_conform():
    """module.toml parses, and the artifact's script name and sha256 match it."""
    manifest = load_manifest(_MANIFEST)
    artifact_bytes = _ARTIFACT.read_bytes()
    verify_artifact_inventory(manifest, artifact_bytes.decode("utf-8"))
    verify_artifact_sha256(manifest, artifact_bytes)


@pytest.mark.integration
def test_template_passthrough(installed):
    """Deployed, my_module(sqltext) returns its input unchanged."""
    conn = installed
    manifest = load_manifest(_MANIFEST)
    statement = _ARTIFACT.read_text(encoding="utf-8")
    conn.execute(statement.removeprefix("--/\n").rstrip().removesuffix("/").rstrip())
    harness = f"PREPROC_RT.TEMPLATE_TEST_HARNESS"
    try:
        conn.execute(
            f"CREATE OR REPLACE LUA SCRIPT {harness}(intext) RETURNS TABLE AS\n"
            f"import('{manifest.script_name}', 'm')\n"
            f'exit({{{{m.{manifest.function}(intext)}}}}, "result_text VARCHAR(2000000)")\n'
        )
        rows = conn.execute(f"EXECUTE SCRIPT {harness}('SELECT 1')").fetchall()
        assert rows[0][0] == "SELECT 1"
    finally:
        conn.execute(f"DROP SCRIPT IF EXISTS {harness}")
        conn.execute(f"DROP SCRIPT IF EXISTS {manifest.script_name}")
