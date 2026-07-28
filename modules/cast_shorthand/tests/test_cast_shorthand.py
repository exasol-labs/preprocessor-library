"""Tests for cast_shorthand: PostgreSQL-style expr::type cast shorthand.

Harness approach
----------------
The module under test is deployed from its canonical artifact,
``cast_shorthand_v1.sql`` (one ``CREATE OR REPLACE LUA SCRIPT`` statement). To
capture its exact string output we also deploy a thin DB-side Lua harness that
calls the module function and returns the rewritten text as a single-row,
single-column table — the only way to assert byte-for-byte exact output,
since probing through MASTER cannot distinguish the rewritten text from what
the engine received.

The harness (and the module it imports) are deployed and torn down inside a
module-scoped fixture so they cannot pollute any other test in the session.
"""

from pathlib import Path

import pytest

from preproc.module.manifest import (
    load_manifest,
    verify_artifact_inventory,
    verify_artifact_sha256,
)

_MODULE_DIR = Path(__file__).resolve().parents[1]
_ARTIFACT = _MODULE_DIR / "cast_shorthand_v1.sql"
_MANIFEST_PATH = _MODULE_DIR / "module.toml"
_MODULE_SCRIPT = "PREPROC_RT.CAST_SHORTHAND_V1"
_HARNESS_SCRIPT = "PREPROC_RT.CAST_SHORTHAND_TEST_HARNESS"


def _create_statement() -> str:
    """Return the artifact's CREATE OR REPLACE statement without the EXAplus delimiters."""
    text = _ARTIFACT.read_text(encoding="utf-8")
    return text.removeprefix("--/\n").rstrip().removesuffix("/").rstrip()


def _sql_escape(text: str) -> str:
    """Escape a Python string for safe embedding in a SQL single-quoted literal."""
    return text.replace("'", "''")


def _harness_call(conn, input_text: str) -> str:
    """Call the cast_shorthand harness and return the single string result."""
    escaped = _sql_escape(input_text)
    rows = conn.execute(f"EXECUTE SCRIPT {_HARNESS_SCRIPT}('{escaped}')").fetchall()
    return rows[0][0]


@pytest.fixture(scope="module")
def cast_harness(installed):
    """Deploy the cast_shorthand artifact and a thin harness; tear down on exit."""
    conn = installed
    conn.execute(_create_statement())
    harness_body = (
        f"import('{_MODULE_SCRIPT}', 'm')\n"
        'exit({{m.cast_shorthand(intext)}}, "result_text VARCHAR(2000000)")\n'
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
# Rewriting scenarios
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cast_simple_identifier(cast_harness):
    """A simple identifier cast is rewritten to CAST(expr AS type)."""
    result = _harness_call(cast_harness, "SELECT col::integer FROM t")
    assert result == "SELECT CAST(col AS integer) FROM t"


@pytest.mark.integration
def test_cast_schema_qualified_identifier(cast_harness):
    """A schema-qualified identifier cast is rewritten correctly."""
    result = _harness_call(cast_harness, "SELECT s.t.col::varchar(20) FROM s.t")
    assert result == "SELECT CAST(s.t.col AS varchar(20)) FROM s.t"


@pytest.mark.integration
def test_cast_parenthesised_expression(cast_harness):
    """A parenthesised expression cast is rewritten correctly."""
    result = _harness_call(cast_harness, "SELECT (a + b)::decimal(10,2) FROM t")
    assert result == "SELECT CAST((a + b) AS decimal(10,2)) FROM t"


@pytest.mark.integration
def test_cast_function_call_operand(cast_harness):
    """A function-call operand is rewritten correctly."""
    result = _harness_call(cast_harness, "SELECT trim(col)::varchar(50) FROM t")
    assert result == "SELECT CAST(trim(col) AS varchar(50)) FROM t"


@pytest.mark.integration
def test_cast_schema_qualified_function_call_operand(cast_harness):
    """A schema-qualified function-call operand keeps its qualifier in the cast."""
    result = _harness_call(cast_harness, "SELECT s.fn(col)::int FROM t")
    assert result == "SELECT CAST(s.fn(col) AS int) FROM t"


@pytest.mark.integration
def test_cast_chained(cast_harness):
    """A chained cast is rewritten inside-out in a single left-to-right pass."""
    result = _harness_call(cast_harness, "SELECT a::int::text FROM t")
    assert result == "SELECT CAST(CAST(a AS int) AS text) FROM t"


@pytest.mark.integration
def test_cast_parameterised_type(cast_harness):
    """A parameterised type is captured including its argument list."""
    result = _harness_call(cast_harness, "SELECT x::decimal(10,2) FROM t")
    assert result == "SELECT CAST(x AS decimal(10,2)) FROM t"


# ---------------------------------------------------------------------------
# Passthrough (byte-for-byte unchanged) scenarios
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cast_passthrough_no_colons(cast_harness):
    """A statement with no '::' tokens is returned byte-for-byte unchanged."""
    input_text = "SELECT col FROM t"
    result = _harness_call(cast_harness, input_text)
    assert result == input_text


@pytest.mark.integration
def test_cast_inside_single_quoted_string(cast_harness):
    """A '::' inside a single-quoted string literal is NOT rewritten."""
    input_text = "SELECT '::not_a_cast' AS x FROM dual"
    result = _harness_call(cast_harness, input_text)
    assert result == input_text


@pytest.mark.integration
def test_cast_inside_double_quoted_identifier(cast_harness):
    """A '::' inside a double-quoted identifier is NOT rewritten."""
    input_text = 'SELECT "col::name" FROM t'
    result = _harness_call(cast_harness, input_text)
    assert result == input_text


@pytest.mark.integration
def test_cast_inside_line_comment(cast_harness):
    """A '::' inside a line comment is NOT rewritten."""
    input_text = "SELECT col FROM t -- col::integer is just a comment"
    result = _harness_call(cast_harness, input_text)
    assert result == input_text


@pytest.mark.integration
def test_cast_inside_block_comment(cast_harness):
    """A '::' inside a block comment is NOT rewritten."""
    input_text = "SELECT /* a::int placeholder */ col FROM t"
    result = _harness_call(cast_harness, input_text)
    assert result == input_text


@pytest.mark.integration
def test_cast_escaped_string_mixed(cast_harness):
    """A string with '' escape sequences is scanned correctly; only the real cast is rewritten."""
    input_text = "SELECT 'it''s::fine' AS x, col::integer FROM t"
    result = _harness_call(cast_harness, input_text)
    assert result == "SELECT 'it''s::fine' AS x, CAST(col AS integer) FROM t"


# ---------------------------------------------------------------------------
# Fail-closed scenario
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cast_unrecognised_operand_fail_closed(cast_harness):
    """An unrecognised left operand causes fail-closed: original text returned unchanged."""
    input_text = "SELECT arr[1]::int FROM t"
    result = _harness_call(cast_harness, input_text)
    assert result == input_text


# ---------------------------------------------------------------------------
# Static conformance assertion (no DB fixture needed)
# ---------------------------------------------------------------------------


def test_cast_shorthand_manifest_and_artifact_conform():
    """module.toml parses, and the artifact's script name and sha256 match it."""
    manifest = load_manifest(_MANIFEST_PATH)
    artifact_bytes = _ARTIFACT.read_bytes()
    verify_artifact_inventory(manifest, artifact_bytes.decode("utf-8"))
    verify_artifact_sha256(manifest, artifact_bytes)
