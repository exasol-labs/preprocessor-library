"""Tests for confd_control: the ConfD command surface as one composite module.

Two halves, split by what each needs.

``test_entry_rewrites_each_domain`` needs NEITHER a database NOR a ConfD
endpoint. The entry script is a pure text transform, so the artifact's own
entry-script body is loaded into an in-process Lua runtime and
``confd_control(sqltext)`` is called directly. That is the check that the bytes
THIS repo ships still rewrite all three command domains. It is deliberately a
smoke check, not a grammar suite: the grammars are verified upstream in
confd-via-sql over a corpus covering every command family, and duplicating that
corpus here would put the same assertions in two repos that release on
different cadences.

Every other test is an install-lifecycle test against a live Exasol instance
(the root ``conftest.py``'s ``installed`` fixture, which skips cleanly when no
instance is configured). None of them needs ConfD either: an install creates
scripts, one rule and one provenance row, and none of that contacts the ConfD
endpoint the deployed UDFs would use at call time. Where a test dispatches
through an activated MASTER it dispatches only statements a test-owned stand-in
answers, so no ConfD call is ever the observed rewrite.

Isolation, and the boundary this suite may not cross
    ``PREPROC.CONFIG``, ``PREPROC.RESOLUTION``, ``PREPROC.PROFILES`` and
    ``PREPROC.MODULES`` are global tables on a session-scoped connection shared
    with every other module's tests, so ``clean_install_state`` removes this
    module's rules, provenance rows and objects — and the test-owned stand-ins
    below — both before and after every test. It deletes the rules and refreshes
    BEFORE dropping any object, so a baked profile is orphaned into the MASTER
    stub while the script it bakes still exists.

    The boundary is exact and it is enforced by construction: ``_purge`` touches
    the module's OWN declared inventory and the scripts named in
    ``_TEST_OWNED_SCRIPTS``, and nothing else. Every one of those names is
    created either by the artifact under test or by this file. In particular this
    suite NEVER drops the pre-module hand-run install's own objects — the three
    unversioned-era grammar scripts ``PREPROC_RT.CONTROL_{DATABASE,BUCKETFS,
    STORAGE}_V1`` and the five unversioned admin scripts ``PREPROC.ADMIN_*`` — and
    never overwrites them. Nothing in either repo creates them, so nothing here
    may remove them: on an instance that carries a real hand-run install, doing
    so would silently perform the destructive half of the documented migration
    with none of the steps that precede it.

    ``PREPROC.PROFILES`` is deliberately the one shared table ``_purge`` does not
    DELETE from. A profile row is not free-standing state: it names a baked
    ``PREPROC_RT.P_<hash>`` script that live sessions may be pinned to, and
    ``REFRESH_CORE`` is the only thing that may retire one — it rewrites the
    script's body to the MASTER stub, stamps ``orphaned_at``, and drops the script
    only on a LATER refresh once no session old enough to be pinned to it remains.
    Deleting the row instead strands the script forever, untracked. So ``_purge``
    removes the RULES and refreshes, and lets ``REFRESH_CORE`` orphan and
    eventually reclaim the profiles that baked them. (This is why the framework's
    own suite, which owns its whole instance, can wipe PROFILES directly and this
    one cannot.)

The legacy stand-ins
    The two migration tests need a database carrying the pre-module hand-run
    install's SHAPE: three EXPAND rules over three grammar scripts, seeded at the
    same scope and with lower ``rule_id``s than the module's rule. What those
    tests assert is ``rule_id`` ordering, rule survival across the install, the
    cut-over point, and which script actually answers a statement — none of which
    depends on the old grammars' names or bodies. So the stand-ins are
    TEST-OWNED objects under this suite's own names, never the real grammar
    names. That is what makes the isolation boundary above provable rather than
    hopeful: a stand-in name has exactly one producer in the world, this file, so
    dropping it by name can only ever drop what this file created.

    Each stand-in name carries ``_ENTRY_SCRIPT`` as a STRICT PREFIX and shares its
    schema. That is deliberate: it makes the reclaim test's ownership claim
    load-bearing, because a drop set resolved from a name prefix or a schema
    sweep instead of from the recorded inventory would take them.

    Each stand-in also REWRITES, so shadowing is observable rather than inferred:
    it answers one domain's command with a tagged statement of its own, and tags
    the shared probe literal. The real bodies live in confd-via-sql, of which this
    repo deliberately keeps no copy.
"""

import hashlib
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from preproc.connection import connect_from_env
from preproc.module.artifact import split_statements
from preproc.module.deploy import (
    ArtifactDeployError,
    deploy_module,
    drop_objects,
    plan_artifact,
)
from preproc.module.manifest import (
    load_manifest,
    verify_artifact_inventory,
    verify_artifact_sha256,
)
from preproc.module.registry import decode_objects, read_registry

try:
    import lupa

    _HAVE_LUPA = True
except ImportError:  # pragma: no cover - exercised only where lupa is absent
    _HAVE_LUPA = False

_MODULE_DIR = Path(__file__).resolve().parents[1]
_LIBRARY_ROOT = _MODULE_DIR.parents[1]
_ARTIFACT = _MODULE_DIR / "confd_control_v1.sql"
_MANIFEST = _MODULE_DIR / "module.toml"

_MODULE_NAME = "confd_control"
_VERSION = 1
_ENTRY_SCRIPT = "PREPROC_RT.CONFD_CONTROL_V1"
_FUNCTION = "confd_control"
_PHASE = "EXPAND"
_SUGGESTED_SCOPE = ("ROLE", "DBA")
_OVERRIDE_SCOPE = ("ROLE", "PREPROC_ADMIN")
_OBJECT_COUNT = 15

# One recognised command per domain, with the exact text the entry must return.
# CONTROL DATABASE and CONTROL STORAGE reads take the inline UDF lane so they can
# be embedded in a larger statement; CONTROL BUCKETFS service inspection goes
# through the admin-script lane. Between them the three cover both rewrite
# shapes as well as all three domains. `"db_name":""` is the inference marker the
# UDF fills in at call time, not a value resolved during the rewrite, so the
# expected text is environment-independent.
_DOMAIN_REWRITES = (
    (
        "CONTROL DATABASE SHOW INFO",
        "SELECT PREPROC_RT.CONFD_QUERY_V1('CONFD_CONNECTION', 'db_info', "
        '\'{"db_name":""}\') FROM (SELECT 1)',
    ),
    (
        "CONTROL BUCKETFS SHOW SERVICES",
        "EXECUTE SCRIPT PREPROC.ADMIN_CONFD_JOB_V1('bucketfs_list', '{}')",
    ),
    (
        "CONTROL STORAGE SHOW VOLUMES",
        "SELECT PREPROC_RT.CONFD_QUERY_V1('CONFD_CONNECTION', 'st_volume_list', '{}') "
        "FROM (SELECT 1)",
    ),
)
_UNRECOGNISED_STATEMENT = "SELECT 1 FROM DUAL"

# --- the legacy stand-ins (see the module docstring) -------------------------
#
# Names are DERIVED from the entry script's name, so the strict-prefix property
# the reclaim test leans on is structural and cannot drift.
_LEGACY_FUNCTION = "expand"
_LEGACY_DOMAINS = ("DATABASE", "BUCKETFS", "STORAGE")
_LEGACY_STANDINS = tuple(f"{_ENTRY_SCRIPT}_TEST_LEGACY_{domain}" for domain in _LEGACY_DOMAINS)
_STANDIN_TAGS = tuple(f"LEGACY_{domain}" for domain in _LEGACY_DOMAINS)

# The statement MASTER is asked to dispatch when the question is "which script
# answered?". It is not a CONTROL command, so the entry script declines it and
# leaves it untouched — which is exactly how the cut-over becomes visible: while a
# stand-in rule is live the fetched value carries that stand-in's tag, and once the
# stand-in rules are gone it is the bare seed. A statement no rule rewrites is
# also always safe to execute.
_PROBE_SEED = "CONFD_CONTROL_LEGACY_PROBE"
_PROBE_STATEMENT = f"SELECT '{_PROBE_SEED}' AS PROBE"

# A stand-in answers its own domain's command with a tagged statement, and tags
# the probe literal. Returning nil for anything else is what lets MASTER's
# first-match-terminal EXPAND scan fall through to the next stand-in.
_STANDIN_BODY = (
    "CREATE OR REPLACE LUA SCRIPT {name}() AS\n"
    "    function {function}(sqltext)\n"
    "        if sqltext == '{command}' then\n"
    '            return "SELECT \'{tag}\' AS PROBE"\n'
    "        end\n"
    '        local tagged = string.gsub(sqltext, "({seed}[^\']*)\'", "%1|{tag}\'", 1)\n'
    "        if tagged ~= sqltext then\n"
    "            return tagged\n"
    "        end\n"
    "        return nil\n"
    "    end\n"
)
_LEGACY_STANDIN_SPECS = tuple(
    {"name": name, "command": command, "tag": tag}
    for name, (command, _rewrite), tag in zip(
        _LEGACY_STANDINS, _DOMAIN_REWRITES, _STANDIN_TAGS, strict=True
    )
)


def _standin_sql(spec: dict) -> str:
    """One stand-in's CREATE, with the constants the whole family shares filled in."""
    return _STANDIN_BODY.format(function=_LEGACY_FUNCTION, seed=_PROBE_SEED, **spec)

# Calls the DEPLOYED entry script, so the rewrite under observation is the bytes
# that survived CREATE rather than the bytes on disk.
_HARNESS_SCRIPT = "PREPROC_RT.CONFD_CONTROL_TEST_HARNESS"

# Every script this file creates. _purge drops exactly these plus the module's
# own declared inventory, and nothing else — see the module docstring.
_TEST_OWNED_SCRIPTS = (*_LEGACY_STANDINS, _HARNESS_SCRIPT)

# Every script name a rule assertion in this file may legitimately see. The
# framework's install seeds its own ROLE/PREPROC_ADMIN and ROLE/DBA EXPAND rules
# over PREPROC_RT.CONTROL_SUGAR_V1 (sql/install/70_control_sugar_seed.sql), and
# _purge must not delete them — they are not this module's and other suites on the
# shared instance rely on them. So rule assertions FILTER to the scripts under
# test rather than widening the purge or hard-coding the framework's seed, which
# would couple this module's tests to a framework install detail.
_RULE_SCRIPTS_UNDER_TEST = (*_LEGACY_STANDINS, _ENTRY_SCRIPT)

_ACTIVATE = "ALTER SESSION SET sql_preprocessor_script = PREPROC_RT.MASTER"
_PROBE_QUERY_TIMEOUT_SECONDS = 30

_RULE_COLUMNS = (
    "rule_id",
    "scope_type",
    "scope_value",
    "phase",
    "script_name",
    "function_name",
    "enabled",
)
_MODULE_COLUMNS = (
    "version",
    "sha256",
    "script_name",
    "function_name",
    "phase",
    "deploy_mode",
    "status",
    "retired_at",
    "objects",
)


# ---------------------------------------------------------------------------
# Artifact helpers (no database)
# ---------------------------------------------------------------------------


def _manifest():
    return load_manifest(_MANIFEST)


def _declared_objects():
    """The manifest's declared inventory, in file order."""
    objects = _manifest().objects
    assert objects is not None, "confd_control is composite and must declare [[objects]]"
    return objects


def _entry_body() -> str:
    """The entry script's Lua body, exactly as the installer sends it.

    Cut out of the artifact with the framework's own statement splitter rather
    than a private regex, so what the Lua runtime sees below is the text the
    database would compile.
    """
    header = f"CREATE OR REPLACE LUA SCRIPT {_ENTRY_SCRIPT}"
    statements = [
        statement
        for statement in split_statements(_ARTIFACT.read_text(encoding="utf-8"))
        if statement.startswith(header)
    ]
    assert len(statements) == 1, f"expected one {_ENTRY_SCRIPT} statement, found {len(statements)}"
    return statements[0].split("\n", 1)[1]


def _artifact_with_unloadable_last_statement() -> str:
    """The artifact with its LAST statement made un-parseable by the database.

    Only the statement's ``RETURNS`` clause is broken, so the statement still
    declares the same object: the artifact still splits into the same 15
    statements deriving the same 15-object inventory, and the install therefore
    fails where a statement is EXECUTED rather than where it is pre-flighted.
    """
    text = _ARTIFACT.read_text(encoding="utf-8")
    header = split_statements(text)[-1].split("\n", 1)[0]
    assert text.count(header) == 1, "the last statement's CREATE header is not unique"
    broken = header.replace("RETURNS TABLE", "RETURNS NO_SUCH_RESULT_KIND")
    assert broken != header, "the last statement no longer declares RETURNS TABLE"
    return text.replace(header, broken)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _script_exists(connection, qualified: str) -> bool:
    schema, _, name = qualified.partition(".")
    return (
        connection.execute(
            "SELECT COUNT(*) FROM EXA_ALL_SCRIPTS WHERE SCRIPT_SCHEMA = {s} AND SCRIPT_NAME = {n}",
            {"s": schema, "n": name},
        ).fetchval()
        > 0
    )


def _scripts_in_install_schemas(connection) -> set[str]:
    """Every script in the two schemas an install writes to, framework profiles aside.

    ``PREPROC_RT.P_<hash>`` is a baked profile: REFRESH_CORE creates and reclaims
    those on its own schedule and an install issues a refresh, so they are the
    framework's objects appearing as a side effect and never the module's.
    """
    rows = connection.execute(
        "SELECT SCRIPT_SCHEMA || '.' || SCRIPT_NAME FROM EXA_ALL_SCRIPTS "
        "WHERE SCRIPT_SCHEMA IN ('PREPROC', 'PREPROC_RT') AND SCRIPT_NAME NOT LIKE 'P\\_%' "
        "ESCAPE '\\'"
    ).fetchall()
    return {row[0] for row in rows}


def _rules_naming(connection, script_name: str) -> list[dict]:
    rows = connection.execute(
        "SELECT " + ", ".join(_RULE_COLUMNS) + " FROM PREPROC.CONFIG "
        "WHERE script_name = {sn} ORDER BY rule_id",
        {"sn": script_name},
    ).fetchall()
    return [dict(zip(_RULE_COLUMNS, row, strict=True)) for row in rows]


def _enabled_expand_rules(connection, scope_type: str, scope_value: str) -> list[dict]:
    """Enabled EXPAND rules at one scope, NARROWED to the scripts under test.

    The narrowing is the point: the framework's install seeds its own EXPAND
    rules at ROLE/DBA over PREPROC_RT.CONTROL_SUGAR_V1 and this suite may neither
    delete them nor assert them, so every rule-list assertion here is stated over
    ``_RULE_SCRIPTS_UNDER_TEST`` only.
    """
    binds = {f"s{index}": name for index, name in enumerate(_RULE_SCRIPTS_UNDER_TEST)}
    in_list = ", ".join("{" + key + "}" for key in binds)
    rows = connection.execute(
        "SELECT " + ", ".join(_RULE_COLUMNS) + " FROM PREPROC.CONFIG "
        "WHERE phase = {ph} AND enabled = TRUE AND scope_type = {st} AND scope_value = {sv} "
        f"AND script_name IN ({in_list}) ORDER BY rule_id",
        {"ph": _PHASE, "st": scope_type, "sv": scope_value, **binds},
    ).fetchall()
    return [dict(zip(_RULE_COLUMNS, row, strict=True)) for row in rows]


def _resolved_expand_scripts(connection) -> set[str]:
    """Every script an EXPAND rule resolves to, as the last refresh materialised it."""
    rows = connection.execute(
        "SELECT DISTINCT script_name FROM PREPROC.RESOLUTION WHERE phase = {ph}",
        {"ph": _PHASE},
    ).fetchall()
    return {row[0] for row in rows}


def _dispatch_order(connection) -> list[str]:
    """The EXPAND chain MASTER will scan for the current user, in dispatch order.

    MASTER reads PREPROC.RESOLUTION and walks each phase in ordinal-ascending
    order, so this — not PREPROC.CONFIG's ``rule_id`` order — is the sequence a
    statement is actually offered to. Narrowed to the scripts under test for the
    same reason ``_enabled_expand_rules`` is.
    """
    rows = connection.execute(
        "SELECT script_name FROM PREPROC.RESOLUTION "
        "WHERE phase = {ph} AND user_name = CURRENT_USER ORDER BY ordinal",
        {"ph": _PHASE},
    ).fetchall()
    return [row[0] for row in rows if row[0] in _RULE_SCRIPTS_UNDER_TEST]


def _module_row(connection, version: int = _VERSION) -> dict | None:
    rows = connection.execute(
        "SELECT " + ", ".join(_MODULE_COLUMNS) + " FROM PREPROC.MODULES "
        "WHERE name = {n} AND version = {v}",
        {"n": _MODULE_NAME, "v": version},
    ).fetchall()
    return dict(zip(_MODULE_COLUMNS, rows[0], strict=True)) if rows else None


def _module_row_count(connection) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM PREPROC.MODULES WHERE name = {n}", {"n": _MODULE_NAME}
    ).fetchval()


def _refresh(connection) -> None:
    connection.execute("EXECUTE SCRIPT PREPROC.REFRESH").fetchall()


def _preprocessed(statement: str):
    """Fetch ``statement`` through an ACTIVATED MASTER, on a throwaway connection.

    This is the only way to observe WHICH script answered a statement: MASTER
    rewrites text and returns nothing, so the answer has to be encoded in the
    rewrite's own result. A fresh session resolves the current committed pipeline
    (no stale profile pin) and MASTER dispatches the triggering statement before
    any convenience-mode profile swap, so the first statement is the transformed
    one. It is deliberately never the suite's shared connection: an activation
    must not outlive one probe.

    QUERY_TIMEOUT bounds the blast radius. Every statement passed here is one a
    stand-in answers, but EXPAND is fail-open — a stand-in that unexpectedly
    declined would fall through to the entry script, whose rewrite is a real
    ConfD call. The timeout turns that into a bounded failure rather than a hang.
    """
    probe = connect_from_env()
    try:
        probe.execute(f"ALTER SESSION SET QUERY_TIMEOUT = {_PROBE_QUERY_TIMEOUT_SECONDS}")
        probe.execute(_ACTIVATE)
        return probe.execute(statement).fetchval()
    finally:
        probe.close()


@contextmanager
def _entry_harness(connection):
    """Yield a callable returning the DEPLOYED entry script's rewrite, or None.

    ``is_match`` and not ``matched``: MATCHED is a reserved word inside an Exasol
    column-description string and the CREATE is rejected at parse time. A declined
    statement is returned as Lua ``''`` because ``exit`` needs the row to keep its
    declared arity, and is reported here as None.
    """
    connection.execute(
        f"CREATE OR REPLACE LUA SCRIPT {_HARNESS_SCRIPT}(intext) RETURNS TABLE AS\n"
        f"import('{_ENTRY_SCRIPT}', 'm')\n"
        f"local rewrite = m.{_FUNCTION}(intext)\n"
        "local is_match = 1\n"
        "if rewrite == nil then is_match = 0 rewrite = '' end\n"
        'exit({{is_match, rewrite}}, "is_match DECIMAL(1,0), rewrite_text VARCHAR(2000000)")\n'
    )

    def rewrite_of(statement: str) -> str | None:
        row = connection.execute(
            f"EXECUTE SCRIPT {_HARNESS_SCRIPT}({{s}})", {"s": statement}
        ).fetchall()[0]
        return row[1] if row[0] == 1 else None

    try:
        yield rewrite_of
    finally:
        connection.execute(f"DROP SCRIPT IF EXISTS {_HARNESS_SCRIPT}")


def _seed_legacy_install(connection) -> list[int]:
    """Recreate the pre-module install's shape with the test-owned stand-ins.

    Returns the allocated ``rule_id``s in seeding order. ``PREPROC.RULE_ADD``
    allocates ``MAX(rule_id) + 1`` over the sub-9000 operator band, which is
    exactly what the retired seed DML did. Its last argument is ``norefresh``, so
    the three inserts are committed without a rebuild each and one refresh at the
    end materialises all three.
    """
    rule_ids = []
    for spec in _LEGACY_STANDIN_SPECS:
        connection.execute(_standin_sql(spec))
    for spec in _LEGACY_STANDIN_SPECS:
        rule_ids.append(
            int(
                connection.execute(
                    "EXECUTE SCRIPT PREPROC.RULE_ADD({st}, {sv}, {ph}, {sn}, {fn}, TRUE)",
                    {
                        "st": _SUGGESTED_SCOPE[0],
                        "sv": _SUGGESTED_SCOPE[1],
                        "ph": _PHASE,
                        "sn": spec["name"],
                        "fn": _LEGACY_FUNCTION,
                    },
                ).fetchval()
            )
        )
    _refresh(connection)
    return rule_ids


def _purge(connection) -> None:
    """Remove every trace of confd_control and of this file's own objects.

    Rules go first and a refresh follows, so any profile baking a script is
    orphaned into the MASTER stub while that script still exists; only then are
    the objects dropped. Every statement is idempotent, so this is safe on an
    already-clean database and safe to repeat after a failed test.

    The drop set is the module's declared inventory plus ``_TEST_OWNED_SCRIPTS``.
    Nothing else is ever dropped — see the module docstring for why that boundary
    is not negotiable on a shared instance.

    Raises:
        RuntimeError: if an inventory object could not be dropped. ``drop_objects``
            is best-effort by contract and reports rather than raises, but a
            survivor here silently violates the next test's precondition, so it is
            escalated at once.
    """
    for script in (_ENTRY_SCRIPT, *_LEGACY_STANDINS):
        connection.execute("DELETE FROM PREPROC.CONFIG WHERE script_name = {sn}", {"sn": script})
    connection.execute("DELETE FROM PREPROC.MODULES WHERE name = {n}", {"n": _MODULE_NAME})
    connection.commit()
    _refresh(connection)

    failures = drop_objects(connection, _declared_objects())
    for script in _TEST_OWNED_SCRIPTS:
        connection.execute(f"DROP SCRIPT IF EXISTS {script}")
    connection.commit()
    if failures:
        unresolved = "; ".join(f"{obj.type} {obj.name} ({error})" for obj, error in failures)
        raise RuntimeError(f"clean_install_state could not drop {unresolved}")


@pytest.fixture(scope="module")
def registry_entry():
    """confd_control as the committed ``registry/index.json`` publishes it.

    Reading the entry back out of the index rather than out of ``module.toml``
    is deliberate: it is the index the operator's CLI resolves, so an install
    driven from it also proves the index carries a usable entry.
    """
    index = read_registry(str(_LIBRARY_ROOT))
    entries = [entry for entry in index.entries if entry.name == _MODULE_NAME]
    assert entries, (
        f"registry/index.json lists no {_MODULE_NAME} entry; run python3 scripts/generate_index.py"
    )
    return entries[-1]


@pytest.fixture
def clean_install_state(installed):
    """A database with no confd_control install and no legacy stand-in, both ways."""
    connection = installed
    _purge(connection)
    try:
        yield connection
    finally:
        _purge(connection)


# ---------------------------------------------------------------------------
# Static conformance (no database)
# ---------------------------------------------------------------------------


def test_confd_control_manifest_and_artifact_conform():
    """module.toml parses, and the artifact's inventory and sha256 match it."""
    manifest = _manifest()
    artifact_bytes = _ARTIFACT.read_bytes()
    derived = verify_artifact_inventory(manifest, artifact_bytes.decode("utf-8"))
    verify_artifact_sha256(manifest, artifact_bytes)
    assert len(derived) == _OBJECT_COUNT
    assert manifest.phase == _PHASE
    assert (manifest.suggested_scope.type, manifest.suggested_scope.value) == _SUGGESTED_SCOPE


# ---------------------------------------------------------------------------
# Rewrite behaviour: no database, no ConfD
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAVE_LUPA, reason="no in-process Lua runtime available (install `lupa`)")
def test_entry_rewrites_each_domain():
    """The shipped entry body rewrites all three domains and declines everything else.

    Runs entirely in-process: no database, no ConfD endpoint, no framework
    install. A recognised command from each domain must return its exact rewrite
    text as a single value, and an unrecognised statement must return no rewrite
    at all (a Lua ``nil``, never the input echoed back — an EXPAND module
    declines by returning nothing).
    """
    runtime = lupa.LuaRuntime(unpack_returned_tuples=True)
    runtime.execute(_entry_body())
    confd_control = runtime.globals().confd_control
    assert confd_control is not None, f"the entry body exported no global {_FUNCTION}()"

    for statement, expected in _DOMAIN_REWRITES:
        rewrite = confd_control(statement)
        assert not isinstance(rewrite, tuple), (
            f"{_FUNCTION}({statement!r}) returned {len(rewrite)} values; MASTER binds one"
        )
        assert rewrite == expected

    assert confd_control(_UNRECOGNISED_STATEMENT) is None, (
        "an unrecognised statement must produce no rewrite"
    )


# ---------------------------------------------------------------------------
# Registry install
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_module_add_creates_objects_rule_and_provenance(clean_install_state, registry_entry):
    """Install creates the 15 objects in file order, one DBA rule, and provenance."""
    connection = clean_install_state

    result = deploy_module(connection, registry_entry, str(_LIBRARY_ROOT))

    assert result.artifact_deployed is True
    assert [(obj.type, obj.name) for obj in result.objects] == [
        (obj.type, obj.name) for obj in _declared_objects()
    ], "the deployed inventory must be the manifest's, in file order"
    for obj in result.objects:
        assert _script_exists(connection, obj.name), f"{obj.name} was not created"

    rules = _rules_naming(connection, _ENTRY_SCRIPT)
    assert len(rules) == 1, "exactly one rule must bind the entry script"
    rule = rules[0]
    assert (rule["scope_type"], rule["scope_value"]) == _SUGGESTED_SCOPE
    assert rule["phase"] == _PHASE
    assert rule["function_name"] == _FUNCTION
    assert rule["enabled"] is True
    assert result.rule_created is True

    row = _module_row(connection)
    assert row is not None, "no PREPROC.MODULES provenance row was written"
    assert row["sha256"] == registry_entry.sha256
    assert row["script_name"] == _ENTRY_SCRIPT
    assert row["function_name"] == _FUNCTION
    assert row["phase"] == _PHASE
    assert row["deploy_mode"] == "library-deployed"
    assert row["status"] == "deployed"
    recorded = decode_objects(row["objects"])
    assert [(obj["type"], obj["name"]) for obj in recorded] == [
        (obj.type, obj.name) for obj in result.objects
    ], "the recorded inventory must be the full 15-object inventory, in file order"

    # The install's single refresh is what materialises the new rule; a resolved
    # EXPAND row naming the entry script is that refresh's observable effect.
    assert _ENTRY_SCRIPT in _resolved_expand_scripts(connection)


@pytest.mark.integration
def test_module_add_is_idempotent(clean_install_state, registry_entry):
    """A second install returns the same rule unchanged and updates one provenance row."""
    connection = clean_install_state

    first = deploy_module(connection, registry_entry, str(_LIBRARY_ROOT))
    second = deploy_module(connection, registry_entry, str(_LIBRARY_ROOT))

    assert first.rule_created is True
    assert second.rule_created is False, "the second install must not create a second rule"
    assert second.rule_id == first.rule_id, "the existing rule's identity must be returned"
    assert len(_rules_naming(connection, _ENTRY_SCRIPT)) == 1

    assert first.provenance_created is True
    assert second.provenance_created is False, "provenance must be updated, not duplicated"
    assert _module_row_count(connection) == 1


@pytest.mark.integration
def test_scope_override_is_honoured(clean_install_state, registry_entry):
    """An explicit scope override registers the rule at that scope; the suggestion stands."""
    connection = clean_install_state

    result = deploy_module(connection, registry_entry, str(_LIBRARY_ROOT), scope=_OVERRIDE_SCOPE)

    assert (result.scope_type, result.scope_value) == _OVERRIDE_SCOPE
    rules = _rules_naming(connection, _ENTRY_SCRIPT)
    assert len(rules) == 1, "the override must replace the suggested scope, not add to it"
    assert (rules[0]["scope_type"], rules[0]["scope_value"]) == _OVERRIDE_SCOPE

    manifest_scope = _manifest().suggested_scope
    assert (manifest_scope.type, manifest_scope.value) == _SUGGESTED_SCOPE, (
        "the manifest's suggested_scope must stay the default for anyone who does not override"
    )
    entry_scope = registry_entry.suggested_scope
    assert (entry_scope["type"], entry_scope["value"]) == _SUGGESTED_SCOPE


@pytest.mark.integration
def test_failed_statement_compensates_and_registers_no_rule(
    clean_install_state, registry_entry, tmp_path
):
    """A mid-artifact failure drops what it created, registers nothing, and re-converges.

    The install runs against a scratch registry holding an artifact whose LAST
    statement the database refuses. Its digest is recomputed, so the pre-flight
    passes and the failure lands where a statement executes: the 14 objects the
    preceding statements created are dropped in reverse, and the rule — which is
    registered only after the whole artifact — was never reached, so the module
    cannot activate half-installed.
    """
    connection = clean_install_state
    tampered_text = _artifact_with_unloadable_last_statement()

    plan = plan_artifact(_manifest(), tampered_text)
    assert len(plan.statements) == _OBJECT_COUNT
    assert plan.objects == _declared_objects(), (
        "the tampered artifact must pre-flight identically, or this tests the wrong gate"
    )

    artifact_path = tmp_path / "modules" / _MODULE_NAME / _ARTIFACT.name
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(tampered_text, encoding="utf-8")
    tampered_entry = replace(
        registry_entry, sha256=hashlib.sha256(tampered_text.encode("utf-8")).hexdigest()
    )

    with pytest.raises(ArtifactDeployError) as failure:
        deploy_module(connection, tampered_entry, str(tmp_path))

    assert failure.value.index == _OBJECT_COUNT
    assert failure.value.total == _OBJECT_COUNT
    assert failure.value.cleanup_failures == ()
    for obj in _declared_objects():
        assert not _script_exists(connection, obj.name), f"{obj.name} survived compensating cleanup"
    assert _rules_naming(connection, _ENTRY_SCRIPT) == [], "a failed install registered a rule"
    assert _module_row(connection) is None, "a failed install wrote a provenance row"

    converged = deploy_module(connection, registry_entry, str(_LIBRARY_ROOT))
    assert converged.rule_created is True
    assert len(converged.objects) == _OBJECT_COUNT


# ---------------------------------------------------------------------------
# Migration off the hand-run install
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_install_over_legacy_rules_keeps_old_path_serving(clean_install_state, registry_entry):
    """Installing over the old install leaves it serving; the new entry is live but shadowed.

    Shadowing is OBSERVED here, not inferred. After the install, each of the three
    domain commands dispatched through an activated MASTER still comes back with
    its stand-in's tag, while the DEPLOYED entry script — asked directly through
    the harness at the same moment — rewrites those very same three commands into
    its own ConfD calls. Two different answers to one input is precisely what
    "live but shadowed" means, and it is the behaviour the zero-downtime
    migration order rests on.

    The mechanism behind it: RULE_ENSURE allocates above the seeded three, refresh
    materialises RESOLUTION in ``rule_id`` order, and MASTER's EXPAND scan is
    first-match-terminal in that order. Nothing of the old install is dropped,
    renamed or disabled.
    """
    connection = clean_install_state
    legacy_rule_ids = _seed_legacy_install(connection)

    result = deploy_module(connection, registry_entry, str(_LIBRARY_ROOT))

    assert result.rule_id > max(legacy_rule_ids), (
        "the module's rule must sort after the seeded rules, or the cut-over is not shadowed"
    )
    dba_rules = _enabled_expand_rules(connection, *_SUGGESTED_SCOPE)
    assert [rule["script_name"] for rule in dba_rules] == [
        *_LEGACY_STANDINS,
        _ENTRY_SCRIPT,
    ], "the old rules must still be enabled, and still match ahead of the new one"
    assert _dispatch_order(connection) == [*_LEGACY_STANDINS, _ENTRY_SCRIPT], (
        "MASTER scans RESOLUTION's ordinal order, so that is where the shadowing has to hold"
    )

    assert _preprocessed(_PROBE_STATEMENT) == f"{_PROBE_SEED}|{_STANDIN_TAGS[0]}", (
        "the lowest-rule_id stand-in must win the first-match-terminal scan"
    )
    with _entry_harness(connection) as entry_rewrite:
        for spec, (command, expected_rewrite) in zip(
            _LEGACY_STANDIN_SPECS, _DOMAIN_REWRITES, strict=True
        ):
            assert _preprocessed(command) == spec["tag"], (
                f"{command!r} must still be served by the old path after the install"
            )
            assert entry_rewrite(command) == expected_rewrite, (
                f"the deployed entry must itself rewrite {command!r}, or it is not shadowed "
                "but simply not working"
            )

    for script in _LEGACY_STANDINS:
        assert _script_exists(connection, script), f"the install dropped {script}"
        assert len(_rules_naming(connection, script)) == 1, f"the install disturbed {script}'s rule"
    assert _script_exists(connection, _ENTRY_SCRIPT), "the new entry script must be present"


@pytest.mark.integration
def test_dropping_legacy_rules_cuts_over_to_entry_script(clean_install_state, registry_entry):
    """Dropping the three old rules is the single cut-over point, and drops no object.

    The old path is observed serving before the drop and observed to have stopped
    after it: the shared probe comes back tagged while a stand-in rule is live and
    bare once the three are gone. What serves instead is settled without calling
    ConfD — after the cut-over the entry script is the only script the EXPAND
    chain offers a statement to, and it rewrites all three domains.
    """
    connection = clean_install_state
    legacy_rule_ids = _seed_legacy_install(connection)
    deploy_module(connection, registry_entry, str(_LIBRARY_ROOT))
    assert _preprocessed(_PROBE_STATEMENT) == f"{_PROBE_SEED}|{_STANDIN_TAGS[0]}", (
        "the old path must be serving before the cut-over, or there is nothing to cut over"
    )

    for rule_id in legacy_rule_ids:
        connection.execute(
            "EXECUTE SCRIPT PREPROC.RULE_DROP({rid}, TRUE)", {"rid": rule_id}
        ).fetchall()
    _refresh(connection)

    dba_rules = _enabled_expand_rules(connection, *_SUGGESTED_SCOPE)
    assert [rule["script_name"] for rule in dba_rules] == [_ENTRY_SCRIPT], (
        "after the cut-over the module's rule must be the only matching EXPAND rule"
    )
    assert _dispatch_order(connection) == [_ENTRY_SCRIPT]
    resolved = _resolved_expand_scripts(connection)
    assert _ENTRY_SCRIPT in resolved, "every domain must now resolve to the entry script"
    assert resolved.isdisjoint(_LEGACY_STANDINS), "an old grammar still resolves after the cut-over"

    assert _preprocessed(_PROBE_STATEMENT) == _PROBE_SEED, (
        "the old path must have stopped serving; a tag means a stand-in still answered"
    )
    with _entry_harness(connection) as entry_rewrite:
        for command, expected_rewrite in _DOMAIN_REWRITES:
            assert entry_rewrite(command) == expected_rewrite

    for script in _LEGACY_STANDINS:
        assert _script_exists(connection, script), (
            "the cut-over must drop no object, so it stays reversible until decommission"
        )


@pytest.mark.integration
def test_fresh_install_needs_no_decommission(clean_install_state, registry_entry):
    """On a database that never carried the old install, nothing needs decommissioning.

    "Needs no decommission" is the claim that the install leaves nothing behind
    that the framework cannot itself reclaim, so it is tested as inventory
    closure: the set of scripts the install adds to PREPROC and PREPROC_RT must be
    exactly the recorded inventory. An artifact statement creating an undeclared
    object would land here — and only here — as a leftover that retire/reclaim
    would never remove.

    The second half exercises the command surface through the DEPLOYED entry
    script, so it is the in-database counterpart of
    ``test_entry_rewrites_each_domain``: it proves the bytes that survived
    ``CREATE`` still rewrite. No ConfD endpoint is contacted — the rewrite is
    text, and its UDF is never called.
    """
    connection = clean_install_state
    before = _scripts_in_install_schemas(connection)

    deploy_module(connection, registry_entry, str(_LIBRARY_ROOT))

    added = _scripts_in_install_schemas(connection) - before
    assert added == {obj.name for obj in _declared_objects()}, (
        "a fresh install must create exactly its recorded inventory, so retire-then-reclaim "
        "removes all of it and no decommission step is left for the operator"
    )
    assert [
        rule["script_name"] for rule in _enabled_expand_rules(connection, *_SUGGESTED_SCOPE)
    ] == [_ENTRY_SCRIPT], "a fresh install must leave exactly one EXPAND rule"

    with _entry_harness(connection) as entry_rewrite:
        for command, expected_rewrite in _DOMAIN_REWRITES:
            assert entry_rewrite(command) == expected_rewrite, (
                f"the deployed entry declined or mis-rewrote {command!r}"
            )


@pytest.mark.integration
def test_retire_then_reclaim_drops_only_recorded_inventory(clean_install_state, registry_entry):
    """Reclaim refuses while the rule is enabled, then drops exactly the 15 objects.

    A leftover object from the old install stands outside the recorded
    inventory, so it must survive: the inventory, never a schema or a name
    pattern, is the ownership boundary. Each stand-in name here carries the entry
    script's fully-qualified name as a strict prefix and shares its schema, so a
    drop set resolved from a prefix or a schema sweep would take them and this
    test would catch it.
    """
    connection = clean_install_state
    for spec in _LEGACY_STANDIN_SPECS:
        connection.execute(_standin_sql(spec))
    result = deploy_module(connection, registry_entry, str(_LIBRARY_ROOT))

    retired = connection.execute(
        "EXECUTE SCRIPT PREPROC.MODULE_RETIRE({n}, {v})",
        {"n": _MODULE_NAME, "v": _VERSION},
    ).fetchall()
    assert retired[0][2] == "retired"

    blocked = connection.execute(
        "EXECUTE SCRIPT PREPROC.MODULE_RECLAIM({n}, {v})",
        {"n": _MODULE_NAME, "v": _VERSION},
    ).fetchall()
    assert blocked[0][4] == "blocked_by_rule", "reclaim must refuse while an enabled rule names it"
    assert blocked[0][3] is False
    assert _script_exists(connection, _ENTRY_SCRIPT)

    # norefresh=FALSE is load-bearing, not incidental. Dropping the rule clears
    # reclaim's guard 1, but the profile baking the entry script still satisfies
    # guard 2 until a refresh rewrites it to the MASTER stub and stamps
    # orphaned_at. RULE_DROP's own rebuild is that refresh. Batching the refreshes
    # instead — norefresh=TRUE here and one refresh later — leaves the profile live
    # and the reclaim below returns 'blocked_by_profile'.
    connection.execute(
        "EXECUTE SCRIPT PREPROC.RULE_DROP({rid}, FALSE)", {"rid": result.rule_id}
    ).fetchall()
    reclaimed = connection.execute(
        "EXECUTE SCRIPT PREPROC.MODULE_RECLAIM({n}, {v})",
        {"n": _MODULE_NAME, "v": _VERSION},
    ).fetchall()
    assert reclaimed[0][4] == "reclaimed"
    assert reclaimed[0][2] is True
    assert reclaimed[0][3] is True

    for obj in _declared_objects():
        assert not _script_exists(connection, obj.name), f"reclaim left {obj.name} behind"
    assert _module_row(connection) is None
    for script in _LEGACY_STANDINS:
        assert _script_exists(connection, script), (
            f"reclaim dropped {script}, which no inventory records"
        )
