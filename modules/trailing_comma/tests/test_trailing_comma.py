"""Tests for trailing_comma: opt-in trailing_comma removal.

Harness approach
----------------
Two generations of the module coexist on disk: ``trailing_comma_v1.sql`` (the
originally published behaviour, restored byte-for-byte to what was released)
and ``trailing_comma_v2.sql`` (a fix: ``CREATE ... SCRIPT`` bodies are left
verbatim, and ``(`` is no longer treated as a keyword boundary, so a call like
``set(...)`` or ``into(...)`` no longer loses its preceding comma). Each
generation is deployed from its own canonical artifact and exercised through
its own thin DB-side Lua harness that calls the module function and returns
the rewritten text as a single-row, single-column table — the only way to
assert byte-for-byte exact output, since probing through MASTER cannot
distinguish the rewritten text from what the engine received.

Each harness (and the module it imports) is deployed and torn down inside its
own module-scoped fixture so neither can pollute any other test in the
session, and so v1's and v2's live objects never collide.

Fail-closed note
-----------------
trailing_comma has no internal error path that can produce corrupted output:
the scanner only skips or appends characters, and ``is_trailing`` returns a
boolean that selects between two branches that both produce valid results.
The fail-closed test therefore asserts graceful handling of a
pathological-but-valid input (an unclosed string literal) — confirming the
harness returns SOME string and does not raise.
"""

import hashlib
from pathlib import Path

import pytest

from preproc.module.manifest import (
    load_manifest,
    verify_artifact_inventory,
    verify_artifact_sha256,
)

_MODULE_DIR = Path(__file__).resolve().parents[1]
_ARTIFACT_V1 = _MODULE_DIR / "trailing_comma_v1.sql"
_ARTIFACT_V2 = _MODULE_DIR / "trailing_comma_v2.sql"
_ARTIFACT = _ARTIFACT_V2
_MANIFEST_PATH = _MODULE_DIR / "module.toml"
_MODULE_SCRIPT_V1 = "PREPROC_RT.ERGONOMICS_TRAILING_COMMA_V1"
_MODULE_SCRIPT_V2 = "PREPROC_RT.ERGONOMICS_TRAILING_COMMA_V2"
_HARNESS_SCRIPT_V1 = "PREPROC_RT.TRAILING_COMMA_TEST_HARNESS_V1"
_HARNESS_SCRIPT_V2 = "PREPROC_RT.TRAILING_COMMA_TEST_HARNESS_V2"

# V1's restored sha256, cross-checked directly (module.toml no longer
# describes V1 -- it was promoted to V2 -- so there is no manifest object to
# verify V1's artifact against; the historical digest is asserted here instead).
_V1_SHA256 = "50358aa93f35f9cd95d443e0c13e8984f2686986de0a074d4b313d32a54be606"


def _create_statement(artifact: Path) -> str:
    """Return the artifact's CREATE OR REPLACE statement without the EXAplus delimiters."""
    text = artifact.read_text(encoding="utf-8")
    return text.removeprefix("--/\n").rstrip().removesuffix("/").rstrip()


def _sql_escape(text: str) -> str:
    """Escape a Python string for safe embedding in a SQL single-quoted literal."""
    return text.replace("'", "''")


def _harness_call(conn, harness_script: str, input_text: str) -> str:
    """Call a trailing_comma harness and return the single string result."""
    escaped = _sql_escape(input_text)
    rows = conn.execute(f"EXECUTE SCRIPT {harness_script}('{escaped}')").fetchall()
    return rows[0][0]


def _deploy_harness(conn, *, artifact: Path, module_script: str, harness_script: str):
    """Deploy one generation's artifact plus a thin harness that calls its entry function."""
    conn.execute(_create_statement(artifact))
    harness_body = (
        f"import('{module_script}', 'm')\n"
        'exit({{m.trailing_comma(intext)}}, "result_text VARCHAR(2000000)")\n'
    )
    conn.execute(
        f"CREATE OR REPLACE LUA SCRIPT {harness_script}(intext) RETURNS TABLE AS\n{harness_body}"
    )


@pytest.fixture(scope="module")
def tc_harness(installed):
    """Deploy the restored trailing_comma V1 artifact and a thin harness; tear down on exit."""
    conn = installed
    _deploy_harness(
        conn,
        artifact=_ARTIFACT_V1,
        module_script=_MODULE_SCRIPT_V1,
        harness_script=_HARNESS_SCRIPT_V1,
    )
    try:
        yield lambda input_text: _harness_call(conn, _HARNESS_SCRIPT_V1, input_text)
    finally:
        conn.execute(f"DROP SCRIPT IF EXISTS {_HARNESS_SCRIPT_V1}")
        conn.execute(f"DROP SCRIPT IF EXISTS {_MODULE_SCRIPT_V1}")


@pytest.fixture(scope="module")
def tc_harness_v2(installed):
    """Deploy the fixed trailing_comma V2 artifact and a thin harness; tear down on exit."""
    conn = installed
    _deploy_harness(
        conn,
        artifact=_ARTIFACT_V2,
        module_script=_MODULE_SCRIPT_V2,
        harness_script=_HARNESS_SCRIPT_V2,
    )
    try:
        yield lambda input_text: _harness_call(conn, _HARNESS_SCRIPT_V2, input_text)
    finally:
        conn.execute(f"DROP SCRIPT IF EXISTS {_HARNESS_SCRIPT_V2}")
        conn.execute(f"DROP SCRIPT IF EXISTS {_MODULE_SCRIPT_V2}")


# ---------------------------------------------------------------------------
# Structural removal: trailing comma before ')'
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_trailing_comma_before_paren(tc_harness):
    """A trailing comma before ')' in a parenthesised list is removed."""
    result = tc_harness("SELECT * FROM t WHERE col IN (1, 2, 3,)")
    assert result == "SELECT * FROM t WHERE col IN (1, 2, 3)"


@pytest.mark.integration
def test_trailing_comma_values_list(tc_harness):
    """A trailing comma before ')' in a VALUES list is removed."""
    result = tc_harness("INSERT INTO t VALUES (1, 2,)")
    assert result == "INSERT INTO t VALUES (1, 2)"


@pytest.mark.integration
def test_trailing_comma_function_args(tc_harness):
    """A trailing comma before ')' in a function argument list is removed."""
    result = tc_harness("SELECT coalesce(a, b,) FROM t")
    assert result == "SELECT coalesce(a, b) FROM t"


@pytest.mark.integration
def test_trailing_comma_whitespace_before_paren(tc_harness):
    """A trailing comma before ')' with intervening whitespace is removed; whitespace preserved."""
    result = tc_harness("SELECT * FROM t WHERE col IN (1, 2, 3,  )")
    assert result == "SELECT * FROM t WHERE col IN (1, 2, 3  )"


@pytest.mark.integration
def test_trailing_comma_comment_before_paren(tc_harness):
    """A trailing comma before ')' with an intervening comment is removed."""
    result = tc_harness("SELECT * FROM t WHERE col IN (1, 2 /* last */ ,)")
    assert result == "SELECT * FROM t WHERE col IN (1, 2 /* last */ )"


# ---------------------------------------------------------------------------
# Keyword-terminated removal
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_trailing_comma_before_from(tc_harness):
    """A trailing comma before FROM in a SELECT list is removed."""
    result = tc_harness("SELECT a, b, FROM t")
    assert result == "SELECT a, b FROM t"


@pytest.mark.integration
def test_trailing_comma_before_group_by(tc_harness):
    """A trailing comma before GROUP BY is removed; trailing in GROUP BY list also removed."""
    result = tc_harness("SELECT a, b, FROM t GROUP BY a, b,")
    assert result == "SELECT a, b FROM t GROUP BY a, b"


# ---------------------------------------------------------------------------
# Passthrough (byte-for-byte unchanged) scenarios
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_trailing_comma_passthrough_no_trailing(tc_harness):
    """A statement with no trailing commas is returned byte-for-byte unchanged."""
    input_text = "SELECT a, b FROM t"
    result = tc_harness(input_text)
    assert result == input_text


@pytest.mark.integration
def test_trailing_comma_inside_single_quoted_string(tc_harness):
    """A comma inside a single-quoted string literal is NOT removed."""
    input_text = "SELECT 'a,b,c,' AS x FROM t"
    result = tc_harness(input_text)
    assert result == input_text


@pytest.mark.integration
def test_trailing_comma_inside_double_quoted_identifier(tc_harness):
    """A comma inside a double-quoted identifier is NOT removed."""
    input_text = 'SELECT "col,name" FROM t'
    result = tc_harness(input_text)
    assert result == input_text


@pytest.mark.integration
def test_trailing_comma_inside_line_comment(tc_harness):
    """A comma inside a line comment is NOT removed."""
    input_text = "SELECT a, b FROM t -- trailing comma not here,"
    result = tc_harness(input_text)
    assert result == input_text


@pytest.mark.integration
def test_trailing_comma_inside_block_comment(tc_harness):
    """A comma inside a block comment is NOT removed."""
    input_text = "SELECT a FROM t /* col, b, */ WHERE x = 1"
    result = tc_harness(input_text)
    assert result == input_text


@pytest.mark.integration
def test_trailing_comma_escaped_string_mixed(tc_harness):
    """A string with '' escapes is scanned correctly; only the real trailing comma is removed."""
    input_text = "SELECT 'it''s,ok' AS x, col FROM t WHERE col IN (1, 2,)"
    result = tc_harness(input_text)
    assert result == "SELECT 'it''s,ok' AS x, col FROM t WHERE col IN (1, 2)"


# ---------------------------------------------------------------------------
# Multi-occurrence and fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_trailing_comma_multiple_in_one_statement(tc_harness):
    """Multiple trailing commas in one statement are all removed in a single pass."""
    result = tc_harness(
        "SELECT a, b, FROM t WHERE col IN (1, 2,) AND y IN (3,)",
    )
    assert result == "SELECT a, b FROM t WHERE col IN (1, 2) AND y IN (3)"


@pytest.mark.integration
def test_trailing_comma_fail_closed(tc_harness):
    """Graceful handling: any input returns a string and does not raise."""
    input_text = "SELECT 'unclosed"
    result = tc_harness(input_text)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# CREATE ... SCRIPT bodies are code, not SQL: left byte-for-byte verbatim
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_create_script_body_left_verbatim(tc_harness_v2):
    """A CREATE ... SCRIPT body is a script language, not SQL. A comma before a
    keyword-named call (here `set(`) must NOT be removed -- doing so would turn
    valid code into a SyntaxError. The whole statement is returned unchanged.

    V2-only: V1 scanned SCRIPT bodies as SQL and mangled this exact case."""
    body = (
        "CREATE OR REPLACE PYTHON3 SCALAR SCRIPT S.RT(x VARCHAR(1)) "
        "RETURNS VARCHAR(10) AS\n"
        "def run(ctx):\n"
        '    labels = ["a", "b", "a"]\n'
        "    pairs = list(zip(labels, set(labels)))\n"
        "    return str(len(pairs))"
    )
    result = tc_harness_v2(body)
    assert result == body


@pytest.mark.integration
def test_create_script_body_keeps_python_trailing_comma(tc_harness_v2):
    """Even a genuine trailing comma inside a script body (valid Python) is left
    alone -- the body is never scanned at all. V2-only, see above."""
    body = (
        "CREATE OR REPLACE PYTHON3 SCALAR SCRIPT S.RT(x VARCHAR(1)) "
        "RETURNS VARCHAR(10) AS\n"
        "def run(ctx):\n"
        "    xs = list((1, 2,))\n"
        "    return str(len(xs))"
    )
    result = tc_harness_v2(body)
    assert result == body


# ---------------------------------------------------------------------------
# Keyword boundary: '(' after a keyword is a function call, not the SQL clause
# (V2-only: V1 treated '(' as a keyword boundary and dropped these commas)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_comma_before_keyword_named_call_is_kept(tc_harness_v2):
    """A comma before a call whose name matches a list-terminating keyword
    (e.g. `set(`, `into(`) is NOT trailing: '(' is not a keyword boundary."""
    result = tc_harness_v2("SELECT f(a, set(b)), g(c, into(d)) FROM t")
    assert result == "SELECT f(a, set(b)), g(c, into(d)) FROM t"


@pytest.mark.integration
def test_comma_before_real_keyword_still_removed(tc_harness_v2):
    """The keyword rule still fires when the keyword is followed by whitespace
    (the normal case): `SELECT a, b, FROM t` -> `SELECT a, b FROM t`."""
    result = tc_harness_v2("SELECT a, b, FROM t")
    assert result == "SELECT a, b FROM t"


# ---------------------------------------------------------------------------
# Static conformance assertion (no DB fixture needed)
# ---------------------------------------------------------------------------


def test_trailing_comma_manifest_and_artifact_conform():
    """module.toml (now describing V2) parses, and its artifact's inventory and
    sha256 match it."""
    manifest = load_manifest(_MANIFEST_PATH)
    artifact_bytes = _ARTIFACT.read_bytes()
    verify_artifact_inventory(manifest, artifact_bytes.decode("utf-8"))
    verify_artifact_sha256(manifest, artifact_bytes)


def test_trailing_comma_v1_artifact_restored_byte_for_byte():
    """trailing_comma_v1.sql matches its originally published sha256 exactly.

    V1 was promoted to V2 rather than mutated in place (never
    CREATE-OR-REPLACE-a-live-module), so an install that already pinned V1's
    sha256 must keep resolving to these exact bytes."""
    digest = hashlib.sha256(_ARTIFACT_V1.read_bytes()).hexdigest()
    assert digest == _V1_SHA256
