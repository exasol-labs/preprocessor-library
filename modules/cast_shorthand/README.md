# cast_shorthand

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
  function call `f(...)` (optionally schema-qualified), a numeric literal, or a
  previously-rewritten `CAST(...)` result (for chaining).
* **Known limitation — a string-literal operand is not rewritten.** The scanner
  passes a single-quoted string through as a completed chunk before it reaches
  the following `::`, so `'42'::DECIMAL` is returned **unchanged** and reaches
  the engine as a normal syntax error. This fails closed (no half-rewritten
  SQL), but it does mean `'…'::type` is not supported in v1 — write
  `CAST('42' AS DECIMAL)` for a string literal, and use a column or numeric
  operand (`AMOUNT_TXT::DECIMAL(10,2)`) when demonstrating the module.
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
| `SELECT 123::varchar(10) FROM dual` | `SELECT CAST(123 AS varchar(10)) FROM dual` |
| `SELECT '::not_a_cast' AS x FROM dual` | unchanged (inside a string literal) |
| `SELECT '42'::DECIMAL FROM dual` | unchanged — string-literal operand, see limitation above |

## Install

Needs framework **0.3.0+**. From a SQL client, as a `PREPROC_ADMIN` holder:

```sql
PREPROC INSTALL MODULE cast_shorthand FOR ROLE ANALYSTS;
```

That is the whole install — no CLI, no Python toolchain. With no `FROM` clause
the source defaults to this library's newest release over HTTPS. On a cluster
with no outbound internet, stage a release tarball in BucketFS and install off
that instead:

```sql
PREPROC INSTALL MODULE cast_shorthand
  FROM 'bucketfs:bfsdefault/<bucket>/preproc-lib-0.3.1.tar.gz' FOR ROLE ANALYSTS;
```

The suggested default scope is `FOR ROLE PREPROC_ADMIN`; the operator may
deploy with a different scope, and a user must **hold** that role for the
transform to reach them. See the library
[README § Installing a module](../../README.md#installing-a-module) for both
paths in full (including BucketFS staging), `docs/operations.md` § Module
management in the `preprocessor-framework` repo for the CLI reference, and
`docs/module-authoring.md` there for the module contract.
