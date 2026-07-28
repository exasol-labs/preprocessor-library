# trailing_comma

A TRANSLATE-phase preprocessor module that removes trailing commas from SQL
statements before the Exasol engine compiles them. Exasol rejects a trailing
comma in any list context as a syntax error, so the rewrite is purely
additive: a statement that is already valid Exasol SQL never contains a
trailing comma in a list context and is never altered.

Deployed script: `PREPROC_RT.ERGONOMICS_TRAILING_COMMA_V2`, function
`trailing_comma`, phase `TRANSLATE`.

V2 fixes a bug in V1: a `CREATE ... SCRIPT` body (Python/Lua/R/Java code, not
SQL) is now left byte-for-byte verbatim, and a comma before a call whose name
happens to match a list-terminating keyword (e.g. `set(...)`, `into(...)`) is
no longer treated as trailing. V1 remains published unchanged at its original
sha256 for any install already pinned to it.

## Behaviour

A trailing comma is one followed (ignoring whitespace and comments) by:

* a closing parenthesis `)` — structural, always safe to remove;
* one of the list-terminating keywords `FROM`, `WHERE`, `GROUP`, `ORDER`,
  `HAVING`, `LIMIT`, `UNION`, `INTERSECT`, `EXCEPT`, `INTO`, `SET`, `ON`,
  `RETURNING` (case-insensitive, word-boundary-guarded); or
* end of the statement.

Only the comma byte is deleted — surrounding whitespace and comments are
preserved verbatim. A statement with no trailing commas is returned
byte-for-byte unchanged. Single-quoted strings, double-quoted identifiers,
line comments, and block comments are scanned and passed through verbatim; a
comma inside any of them is never removed. The module adds no defensive
`pcall` — MASTER's dispatch-level `pcall` is the only error boundary.

## Examples

| Input | Output |
|---|---|
| `SELECT * FROM t WHERE col IN (1, 2, 3,)` | `SELECT * FROM t WHERE col IN (1, 2, 3)` |
| `INSERT INTO t VALUES (1, 2,)` | `INSERT INTO t VALUES (1, 2)` |
| `SELECT a, b, FROM t` | `SELECT a, b FROM t` |
| `SELECT a, b, FROM t GROUP BY a, b,` | `SELECT a, b FROM t GROUP BY a, b` |
| `SELECT 'a,b,c,' AS x FROM t` | unchanged (inside a string literal) |

## Install

```
uv run preproc module add trailing_comma --registry /path/to/preprocessor-library
```

or, for an air-gapped database, bundle it for hand-carry:

```
uv run preproc module bundle trailing_comma --output trailing_comma.sql --registry /path/to/preprocessor-library
```

The suggested default scope is `FOR ROLE PREPROC_ADMIN`; the operator may
deploy with a different scope. Installing needs the `preproc module` CLI
(`uv` + a DB connection) — see `docs/operations.md` § Module management in
the `preprocessor-framework` repo for the CLI reference (including the
`--registry` flag and the air-gap `bundle` flow), and
`docs/module-authoring.md` there for the module contract.
