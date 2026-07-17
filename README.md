# preprocessor-library

The community-facing module library for [`preprocessor-framework`](https://github.com/exasol-labs/preprocessor-framework),
the framework that owns Exasol's single `sql_preprocessor_script` slot and
multiplexes it to every registered syntax/policy provider via `PREPROC_RT.MASTER`.

Exasol exposes exactly **one** preprocessor slot per database (and one per
session). The framework claims that slot once and dispatches to as many
independent modules as are registered against it, so unrelated preprocessing
needs — cast shorthand, trailing-comma tolerance, a whole external subsystem's
front door — never have to fight over it. This repo is where those modules
live: a federated catalog of `fn(text) -> nil|string` Lua scripts, each with a
manifest describing what it does and how to deploy it.

## What's here

```
modules/<name>/              # one module per directory
  <name>_v<N>.sql             # the canonical artifact — one CREATE OR REPLACE statement
  module.toml                 # the contract manifest (phase, script name, sha256, ...)
  README.md                   # what it does, how to use it
  tests/                       # module-level tests

modules/_template/            # copy this to start a new module
registry/index.json           # generated: the federated index CI regenerates on every push
registry/external/            # curated entries for modules hosted in OTHER repos
```

Two modules ship today, both migrated from `preprocessor-framework`'s old
`examples/` directory as the proving case for this library:

* **[cast-shorthand](modules/cast-shorthand/)** — PostgreSQL-style
  `expr::type` → `CAST(expr AS type)`.
* **[trailing-comma](modules/trailing-comma/)** — removes trailing commas
  before `)` or a list-terminating keyword.

## Using a module

Modules here are installed with the `preproc module` CLI, which ships as part
of `preprocessor-framework` — not with `release.sql` (the framework's own
toolchain-free engine deploy). Using this CLI needs `uv` and a live DB
connection (`EXASOL_DSN`/`EXASOL_USER`/`EXASOL_PASSWORD`, see the framework's
[docs/operations.md](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/operations.md#environment-variables)):

```
uv run preproc module list --registry /path/to/preprocessor-library
uv run preproc module add cast-shorthand --registry /path/to/preprocessor-library
```

`--registry` also accepts a pinned `https://` URL to a hosted
`registry/index.json`, or is omitted entirely to use the framework's default
online registry pin. For an air-gapped database — one that must never reach
the network — run `uv run preproc module bundle <name> --output x.sql` on a
connected machine instead, then hand-carry `x.sql` and run it directly in a
SQL client, no CLI or DB connection needed on the air-gapped side. See the
framework's [docs/operations.md § Module management](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/operations.md#module-management)
for the full CLI reference and the air-gap flow, and
[docs/module-authoring.md](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/module-authoring.md)
for the module contract (writing your own).

## Contributing a module

See [CONTRIBUTING.md](CONTRIBUTING.md) for both ways to add a module here: a
library-deployed PR under `modules/`, or a curated `registry/external/<name>.toml`
entry pointing at your own repo.
