"""Tests for trailing-comma: opt-in trailing-comma removal.

Harness approach
----------------
The module under test is deployed from its canonical artifact,
``trailing-comma_v1.sql`` (one ``CREATE OR REPLACE LUA SCRIPT`` statement). To
capture its exact string output we also deploy a thin DB-side Lua harness that
calls the module function and returns the rewritten text as a single-row,
single-column table — the only way to assert byte-for-byte exact output,
since probing through MASTER cannot distinguish the rewritten text from what
the engine received.

The harness (and the module it imports) are deployed and torn down inside a
module-scoped fixture so they cannot pollute any other test in the session.

Fail-closed note
-----------------
trailing-comma has no internal error path that can produce corrupted output:
the scanner only skips or appends characters, and ``is_trailing`` returns a
boolean that selects between two branches that both produce valid results.
The fail-closed test therefore asserts graceful handling of a
pathological-but-valid input (an unclosed string literal) — confirming the
harness returns SOME string and does not raise.
"""

from pathlib import Path

import pytest

from preproc.module.manifest import (
    load_manifest,
    verify_artifact_script_name,
    verify_artifact_sha256,
)

_MODULE_DIR = Path(__file__).resolve().parents[1]
_ARTIFACT = _MODULE_DIR / "trailing-comma_v1.sql"
_MANIFEST_PATH = _MODULE_DIR / "module.toml"
_MODULE_SCRIPT = "PREPROC_RT.ERGONOMICS_TRAILING_COMMA_V1"
_HARNESS_SCRIPT = "PREPROC_RT.TRAILING_COMMA_TEST_HARNESS"


def _create_statement() -> str:
    """Return the artifact's CREATE OR REPLACE statement without the EXAplus delimiters."""
    text = _ARTIFACT.read_text(encoding="utf-8")
    return text.removeprefix("--/\n").rstrip().removesuffix("/").rstrip()


def _sql_escape(text: str) -> str:
    """Escape a Python string for safe embedding in a SQL single-quoted literal."""
    return text.replace("'", "''")


def _harness_call(conn, input_text: str) -> str:
    """Call the trailing-comma harness and return the single string result."""
    escaped = _sql_escape(input_text)
    rows = conn.execute(f"EXECUTE SCRIPT {_HARNESS_SCRIPT}('{escaped}')").fetchall()
    return rows[0][0]


@pytest.fixture(scope="module")
def tc_harness(installed):
    """Deploy the trailing-comma artifact and a thin harness; tear down on exit."""
    conn = installed
    conn.execute(_create_statement())
    harness_body = (
        f"import('{_MODULE_SCRIPT}', 'm')\n"
        'exit({{m.trailing_comma(intext)}}, "result_text VARCHAR(2000000)")\n'
    )
    conn.execute(
        f"CREATE OR REPLACE LUA SCRIPT {_HARNESS_SCRIPT}(intext) RETURNS TABLE AS\n{harness_body}"
    )
    try:
        yield conn
    finally:
        conn.execute(f"DROP SCRIPT IF EXISTS {_HARNESS_SCRIPT}")
        conn.execute(f"DROP SCRIPT IF EXISTS {_MODULE_SCRIPT}")


# ---------------------------------------------------------------------------
# Structural removal: trailing comma before ')'
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_trailing_comma_before_paren(tc_harness):
    """A trailing comma before ')' in a parenthesised list is removed."""
    result = _harness_call(tc_harness, "SELECT * FROM t WHERE col IN (1, 2, 3,)")
    assert result == "SELECT * FROM t WHERE col IN (1, 2, 3)"


@pytest.mark.integration
def test_trailing_comma_values_list(tc_harness):
    """A trailing comma before ')' in a VALUES list is removed."""
    result = _harness_call(tc_harness, "INSERT INTO t VALUES (1, 2,)")
    assert result == "INSERT INTO t VALUES (1, 2)"


@pytest.mark.integration
def test_trailing_comma_function_args(tc_harness):
    """A trailing comma before ')' in a function argument list is removed."""
    result = _harness_call(tc_harness, "SELECT coalesce(a, b,) FROM t")
    assert result == "SELECT coalesce(a, b) FROM t"


@pytest.mark.integration
def test_trailing_comma_whitespace_before_paren(tc_harness):
    """A trailing comma before ')' with intervening whitespace is removed; whitespace preserved."""
    result = _harness_call(tc_harness, "SELECT * FROM t WHERE col IN (1, 2, 3,  )")
    assert result == "SELECT * FROM t WHERE col IN (1, 2, 3  )"


@pytest.mark.integration
def test_trailing_comma_comment_before_paren(tc_harness):
    """A trailing comma before ')' with an intervening comment is removed."""
    result = _harness_call(tc_harness, "SELECT * FROM t WHERE col IN (1, 2 /* last */ ,)")
    assert result == "SELECT * FROM t WHERE col IN (1, 2 /* last */ )"


# ---------------------------------------------------------------------------
# Keyword-terminated removal
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_trailing_comma_before_from(tc_harness):
    """A trailing comma before FROM in a SELECT list is removed."""
    result = _harness_call(tc_harness, "SELECT a, b, FROM t")
    assert result == "SELECT a, b FROM t"


@pytest.mark.integration
def test_trailing_comma_before_group_by(tc_harness):
    """A trailing comma before GROUP BY is removed; trailing in GROUP BY list also removed."""
    result = _harness_call(tc_harness, "SELECT a, b, FROM t GROUP BY a, b,")
    assert result == "SELECT a, b FROM t GROUP BY a, b"


# ---------------------------------------------------------------------------
# Passthrough (byte-for-byte unchanged) scenarios
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_trailing_comma_passthrough_no_trailing(tc_harness):
    """A statement with no trailing commas is returned byte-for-byte unchanged."""
    input_text = "SELECT a, b FROM t"
    result = _harness_call(tc_harness, input_text)
    assert result == input_text


@pytest.mark.integration
def test_trailing_comma_inside_single_quoted_string(tc_harness):
    """A comma inside a single-quoted string literal is NOT removed."""
    input_text = "SELECT 'a,b,c,' AS x FROM t"
    result = _harness_call(tc_harness, input_text)
    assert result == input_text


@pytest.mark.integration
def test_trailing_comma_inside_double_quoted_identifier(tc_harness):
    """A comma inside a double-quoted identifier is NOT removed."""
    input_text = 'SELECT "col,name" FROM t'
    result = _harness_call(tc_harness, input_text)
    assert result == input_text


@pytest.mark.integration
def test_trailing_comma_inside_line_comment(tc_harness):
    """A comma inside a line comment is NOT removed."""
    input_text = "SELECT a, b FROM t -- trailing comma not here,"
    result = _harness_call(tc_harness, input_text)
    assert result == input_text


@pytest.mark.integration
def test_trailing_comma_inside_block_comment(tc_harness):
    """A comma inside a block comment is NOT removed."""
    input_text = "SELECT a FROM t /* col, b, */ WHERE x = 1"
    result = _harness_call(tc_harness, input_text)
    assert result == input_text


@pytest.mark.integration
def test_trailing_comma_escaped_string_mixed(tc_harness):
    """A string with '' escapes is scanned correctly; only the real trailing comma is removed."""
    input_text = "SELECT 'it''s,ok' AS x, col FROM t WHERE col IN (1, 2,)"
    result = _harness_call(tc_harness, input_text)
    assert result == "SELECT 'it''s,ok' AS x, col FROM t WHERE col IN (1, 2)"


# ---------------------------------------------------------------------------
# Multi-occurrence and fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_trailing_comma_multiple_in_one_statement(tc_harness):
    """Multiple trailing commas in one statement are all removed in a single pass."""
    result = _harness_call(
        tc_harness,
        "SELECT a, b, FROM t WHERE col IN (1, 2,) AND y IN (3,)",
    )
    assert result == "SELECT a, b FROM t WHERE col IN (1, 2) AND y IN (3)"


@pytest.mark.integration
def test_trailing_comma_fail_closed(tc_harness):
    """Graceful handling: any input returns a string and does not raise."""
    input_text = "SELECT 'unclosed"
    result = _harness_call(tc_harness, input_text)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Static conformance assertion (no DB fixture needed)
# ---------------------------------------------------------------------------


def test_trailing_comma_manifest_and_artifact_conform():
    """module.toml parses, and the artifact's script name and sha256 match it."""
    manifest = load_manifest(_MANIFEST_PATH)
    artifact_bytes = _ARTIFACT.read_bytes()
    verify_artifact_script_name(manifest, artifact_bytes.decode("utf-8"))
    verify_artifact_sha256(manifest, artifact_bytes)
