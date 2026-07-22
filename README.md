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

## Installing in-database (no CLI, no toolchain)

`preprocessor-framework` **v0.5.0+** adds a SQL-only install path: a DBA holding
`PREPROC_ADMIN` installs a module with a single statement, no `preproc` CLI and
no Python/uv on the operator side. The database reads and integrity-verifies the
module (sha256 + a single `CREATE OR REPLACE LUA SCRIPT` matching the declared
`script_name`) and registers its activation rule in one step. There are two
sources — pick by whether the database has outbound internet.

Discover first (read-only), then install:

```sql
PREPROC CATALOG MODULES FROM '<source>';
PREPROC INSTALL MODULE <name> FROM '<source>' FOR ROLE <role>;   -- or FOR USER <user>
```

`<name>` and the scope value are bare words; the source is single-quoted. Scope
targets rule **activation** (who receives the transform), not install permission
— installing is always the `PREPROC_ADMIN` boundary.

### From the internet (HTTPS)

Point at this repo's `registry/index.json` served at a raw URL. Artifacts are
fetched relative to the index, so no separate build step is needed — the repo is
already laid out for it. The repo (or a fork) must be **public** so the cluster
can fetch it anonymously:

```sql
PREPROC CATALOG MODULES FROM 'https://raw.githubusercontent.com/<owner>/preprocessor-library/<ref>/registry/index.json';
PREPROC INSTALL MODULE cast-shorthand
  FROM 'https://raw.githubusercontent.com/<owner>/preprocessor-library/<ref>/registry/index.json'
  FOR ROLE ANALYSTS;
```

Pin `<ref>` to a tag (e.g. `v0.1.1`) rather than a moving branch. Supplying an
`https:` source *is* the opt-in — there is no toggle. On a no-egress cluster an
`https:` source fails with a network error and installs nothing (use BucketFS
below instead).

### Locally via BucketFS (air-gapped, no egress)

Build the release tarball, upload it into a bucket, and install off that bucket
— the database performs no network I/O.

1. **Build** the tarball (stdlib-only, no framework needed):

   ```
   python3 scripts/build_release.py            # writes dist/preproc-lib-<VERSION>.tar.gz
   ```

   The archive holds `registry/index.json` plus each library-deployed artifact
   at its `modules/<name>/<name>_v<N>.sql` path — exactly the layout the resolver
   reads. The build re-verifies every artifact's sha256 against the index as it
   packs, and is byte-reproducible.

2. **Upload** `dist/preproc-lib-<ver>.tar.gz` into your BucketFS bucket (any
   BucketFS client / `curl` PUT to the write service). BucketFS auto-extracts it.

3. **Create a CONNECTION** naming that bucket and grant the admin role access
   (the framework never creates it — the operator does; the name is arbitrary):

   ```sql
   CREATE CONNECTION PREPROC_BFS TO 'https://<bucketfs-host>:2581/<bucket>' USER '<user>' IDENTIFIED BY '<pw>';
   GRANT ACCESS ON CONNECTION PREPROC_BFS TO PREPROC_ADMIN;
   ```

4. **Install**, naming the archive exactly as uploaded:

   ```sql
   PREPROC CATALOG MODULES FROM 'bucketfs:PREPROC_BFS/preproc-lib-0.1.1.tar.gz';
   PREPROC INSTALL MODULE cast-shorthand FROM 'bucketfs:PREPROC_BFS/preproc-lib-0.1.1.tar.gz' FOR ROLE ANALYSTS;
   ```

See the framework's
[docs/operations.md § In-database module install](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/operations.md#module-management)
for the CONNECTION setup, result columns, and the admin boundary in full.

## Contributing a module

See [CONTRIBUTING.md](CONTRIBUTING.md) for both ways to add a module here: a
library-deployed PR under `modules/`, or a curated `registry/external/<name>.toml`
entry pointing at your own repo.
