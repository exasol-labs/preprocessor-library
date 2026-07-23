# trailing_comma

A TRANSLATE-phase preprocessor module that removes trailing commas from SQL
statements before the Exasol engine compiles them. Exasol rejects a trailing
comma in any list context as a syntax error, so the rewrite is purely
additive: a statement that is already valid Exasol SQL never contains a
trailing comma in a list context and is never altered.

Deployed script: `PREPROC_RT.ERGONOMICS_TRAILING_COMMA_V1`, function
`trailing_comma`, phase `TRANSLATE`.

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
