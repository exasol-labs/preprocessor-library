# preprocessor-library

The community-facing module library for [`preprocessor-framework`](https://github.com/exasol-labs/preprocessor-framework),
the framework that owns Exasol's single `sql_preprocessor_script` slot and
multiplexes it to every registered syntax/policy provider via `PREPROC_RT.MASTER`.

Exasol exposes exactly **one** preprocessor slot per database (and one per
session). The framework claims that slot once and dispatches to as many
independent modules as are registered against it, so unrelated preprocessing
needs — cast shorthand, trailing comma tolerance, a whole external subsystem's
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

* **[cast_shorthand](modules/cast_shorthand/)** — PostgreSQL-style
  `expr::type` → `CAST(expr AS type)`.
* **[trailing_comma](modules/trailing_comma/)** — removes trailing commas
  before `)` or a list-terminating keyword.

## Using a module

Modules here are installed with the `preproc module` CLI, which ships as part
of `preprocessor-framework` — not with `release.sql` (the framework's own
toolchain-free engine deploy). Using this CLI needs `uv` and a live DB
connection (`EXASOL_DSN`/`EXASOL_USER`/`EXASOL_PASSWORD`, see the framework's
[docs/operations.md](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/operations.md#environment-variables)):

```
uv run preproc module list --registry /path/to/preprocessor-library
uv run preproc module add cast_shorthand --registry /path/to/preprocessor-library
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

On **v0.6.0+** the `FROM '<source>'` clause is **optional**: omit it and the
source defaults to this library's index pinned to the mutable `latest` tag
(`exasol-labs/preprocessor-library@latest`), so the simplest install needs no
source at all —

```sql
PREPROC CATALOG MODULES;                                   -- newest release
PREPROC INSTALL MODULE cast_shorthand FOR ROLE ANALYSTS;   -- newest release
```

— and each install records the concrete release it resolved (`library_version`)
and the effective source URL in `PREPROC_RT.INSTALLED_MODULES`, so a `latest`
install stays auditable back to a fixed version (see [HTTPS](#from-the-internet-https)
below for the `latest`-vs-pin trade-off). Supply `FROM` to use a fork, a pinned
`vX.Y.Z`, or a BucketFS source instead.

The command follows **Exasol identifier rules**. Module names are
identifier-safe (letters, digits, underscores — no hyphens) and matched
case-insensitively, so write them unquoted in any case (`cast_shorthand`,
`CAST_SHORTHAND`, and `"cast_shorthand"` all resolve the same module). The `FOR
ROLE|USER` value is a role/user name and is always upper-cased (`dba`, `DBA`,
`"dba"` all mean `DBA`). The source is a single-quoted string. Scope targets rule
**activation** (who receives the transform), not install permission — installing
is always the `PREPROC_ADMIN` boundary.

### From the internet (HTTPS)

Point at this repo's `registry/index.json` served at a raw URL. Artifacts are
fetched relative to the index, so no separate build step is needed — the repo is
already laid out for it. The repo (or a fork) must be **public** so the cluster
can fetch it anonymously:

```sql
PREPROC CATALOG MODULES FROM 'https://raw.githubusercontent.com/<owner>/preprocessor-library/<ref>/registry/index.json';
PREPROC INSTALL MODULE cast_shorthand
  FROM 'https://raw.githubusercontent.com/<owner>/preprocessor-library/<ref>/registry/index.json'
  FOR ROLE ANALYSTS;
```

For `<ref>`, use `latest` to always resolve the newest release — the release
workflow moves a mutable `latest` tag to each `v*` release commit, so the URL
stays stable while tracking releases (not every push to a branch):

```sql
PREPROC CATALOG MODULES FROM 'https://raw.githubusercontent.com/exasol-labs/preprocessor-library/latest/registry/index.json';
```

`latest` is mutable, so the same statement can resolve to different content over
time, and raw serving is CDN-cached (~5 min) so a just-moved tag may lag briefly.
For reproducible or audited installs, pin `<ref>` to an immutable tag (e.g.
`v0.2.0`) instead. Supplying an `https:` source *is* the opt-in — there is no
toggle. On a no-egress cluster an `https:` source fails with a network error and
installs nothing (use BucketFS below instead).

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
   PREPROC CATALOG MODULES FROM 'bucketfs:PREPROC_BFS/preproc-lib-0.2.0.tar.gz';
   PREPROC INSTALL MODULE cast_shorthand FROM 'bucketfs:PREPROC_BFS/preproc-lib-0.2.0.tar.gz' FOR ROLE ANALYSTS;
   ```

See the framework's
[docs/operations.md § In-database module install](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/operations.md#module-management)
for the CONNECTION setup, result columns, and the admin boundary in full.

## Contributing a module

See [CONTRIBUTING.md](CONTRIBUTING.md) for both ways to add a module here: a
library-deployed PR under `modules/`, or a curated `registry/external/<name>.toml`
entry pointing at your own repo.
