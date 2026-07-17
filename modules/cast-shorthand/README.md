# cast-shorthand

A TRANSLATE-phase preprocessor module that rewrites PostgreSQL-style
`expr::type` cast shorthand to `CAST(expr AS type)` before the Exasol engine
compiles a statement. Exasol does not recognise `::` as a cast operator, so
any statement containing an unquoted `::` is a hard syntax error today — the
rewrite is purely additive: a statement that is already valid Exasol SQL never
contains an unquoted `::` and is never altered.

Deployed script: `PREPROC_RT.CAST_SHORTHAND_V1`, function `cast_shorthand`,
phase `TRANSLATE`.

## Behaviour

* A statement with no `::` tokens (or where every `::` is inside a string
  literal, quoted identifier, or comment) is returned byte-for-byte unchanged.
* Single-quoted strings (`'...'`, with `''` escapes), double-quoted
  identifiers (`"..."`), line comments (`-- … EOL`), and block comments
  (`/* … */`) are scanned and passed through verbatim — a `::` inside any of
  them is never rewritten.
* The left operand of `::` may be an unqualified or schema-qualified
  identifier (`a`, `schema.table.col`), a parenthesised expression `(...)`, a
  function call `f(...)` (optionally schema-qualified), a string or numeric
  literal, or a previously-rewritten `CAST(...)` result (for chaining).
* Chained casts are rewritten inside-out in a single left-to-right pass:
  `a::int::text` → `CAST(CAST(a AS int) AS text)`.
* The type name is the token immediately following `::`, plus an optional
  balanced `(...)` parameter list — so `x::decimal(10,2)` →
  `CAST(x AS decimal(10,2))`.
* **Fail-closed**: if the left operand cannot be identified as one of the
  supported kinds, the module returns the original text unchanged rather than
  emit partially-rewritten SQL. It adds no defensive `pcall` — MASTER's
  dispatch-level `pcall` is the only error boundary.

## Examples

| Input | Output |
|---|---|
| `SELECT col::integer FROM t` | `SELECT CAST(col AS integer) FROM t` |
| `SELECT s.t.col::varchar(20) FROM s.t` | `SELECT CAST(s.t.col AS varchar(20)) FROM s.t` |
| `SELECT (a + b)::decimal(10,2) FROM t` | `SELECT CAST((a + b) AS decimal(10,2)) FROM t` |
| `SELECT a::int::text FROM t` | `SELECT CAST(CAST(a AS int) AS text) FROM t` |
| `SELECT '::not_a_cast' AS x FROM dual` | unchanged (inside a string literal) |

## Install

```
uv run preproc module add cast-shorthand --registry /path/to/preprocessor-library
```

or, for an air-gapped database, bundle it for hand-carry:

```
uv run preproc module bundle cast-shorthand --output cast_shorthand.sql --registry /path/to/preprocessor-library
```

The suggested default scope is `FOR ROLE PREPROC_ADMIN`; the operator may
deploy with a different scope. Installing needs the `preproc module` CLI
(`uv` + a DB connection) — see `docs/operations.md` § Module management in
the `preprocessor-framework` repo for the CLI reference (including the
`--registry` flag and the air-gap `bundle` flow), and
`docs/module-authoring.md` there for the module contract.
