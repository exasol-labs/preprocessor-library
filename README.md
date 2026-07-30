# preprocessor-library

**Ready-to-use SQL preprocessors for Exasol.** Pick one from the catalog below
and install it in a single statement — then, if you build something useful,
[add it here](#contributing-a-module) so others can do the same.

This is the module catalog for
[`preprocessor-framework`](https://github.com/exasol-labs/preprocessor-framework),
which owns Exasol's single `sql_preprocessor_script` slot and multiplexes it, so
any number of independent preprocessors can coexist. The framework is the engine
and the SDK; **this repo is the shelf of things already built.**

> **You need the framework first.** One SQL file, no toolchain:
> [preprocessor-framework § Quick Start](https://github.com/exasol-labs/preprocessor-framework#quick-start).
> Then come back and run
> `PREPROC INSTALL MODULE cast_shorthand FOR ROLE <role>;`.
>
> Writing your *own* preprocessor, rather than using one from here? That is the
> framework's job — start at
> [§ Bring your own preprocessor](https://github.com/exasol-labs/preprocessor-framework#bring-your-own-preprocessor).
> You only need this repo when you want to **publish** it.

## The catalog

| Module | Phase | Needs | What it does |
|---|---|---|---|
| **[cast_shorthand](modules/cast_shorthand/)** | TRANSLATE | fw 0.3.0+ | PostgreSQL-style `expr::type` → `CAST(expr AS type)`. Eases a Postgres/Redshift port. |
| **[trailing_comma](modules/trailing_comma/)** | TRANSLATE | fw 0.3.0+ | Removes trailing commas before `)` or a list-terminating keyword, so `SELECT a, b, FROM t` just works. |

```sql
PREPROC CATALOG MODULES;                                   -- browse the live catalog
PREPROC INSTALL MODULE cast_shorthand FOR ROLE ANALYSTS;   -- install one
```

Notes worth knowing before you pick one:

- **`trailing_comma` is at v2** and keeps its original
  `PREPROC_RT.ERGONOMICS_TRAILING_COMMA_V2` script name from its migration out of
  the framework's `examples/`, so its deployed script name deliberately does not
  match its module name.
- **`min_framework` is advisory** — nothing enforces it. Verified on 2026.1: a
  module requiring a newer framework than you run installs and reports
  `installed`, then fails at use. Check your framework version yourself.

## What's here

```
modules/<name>/              # one module per directory
  <name>_v<N>.sql             # the canonical artifact — one or more CREATE statements
  module.toml                 # the contract manifest (phase, script name, sha256, objects, ...)
  README.md                   # what it does, how to use it
  tests/                       # module-level tests

modules/_template/            # copy this to start a new module
registry/index.json           # generated: the federated index CI regenerates on every push
registry/external/            # curated entries for modules hosted in OTHER repos
```

## Installing a module

Two independent paths reach the same end state — a `PREPROC_RT.<NAME>_V<N>`
script, an activation rule, and a provenance row. Pick by what you have
available, not by capability:

| | [From SQL](#from-sql-no-cli-no-toolchain) | [With the CLI](#with-the-preproc-module-cli) |
|---|---|---|
| Needs | a SQL client + `PREPROC_ADMIN` | `uv` + a live DB connection from your machine |
| Best for | a DBA who works only in SQL | scripted/declarative fleet management |
| Extra verbs | catalog, install | `list` / `search` / `update` / `remove` / `sync` / `bundle` / `validate` |

If you just want a module installed, use the SQL path.

## From SQL (no CLI, no toolchain)

A DBA holding `PREPROC_ADMIN` installs a module with a single statement — no
`preproc` CLI and no Python/uv on the operator side. The database reads the
module, verifies its `sha256`, installs every statement in its artifact in file
order, and registers its activation rule in one step. There are two sources —
pick by whether the database has outbound internet.

Discover first (read-only), then install:

```sql
PREPROC CATALOG MODULES FROM '<source>';
PREPROC INSTALL MODULE <name> FROM '<source>' FOR ROLE <role>;   -- or FOR USER <user>
```

The `FROM '<source>'` clause is **optional**: omit it and the source defaults to
this library's index pinned to the mutable `latest` tag
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

> **No trailing `--` comment on a `PREPROC …` line.** Most SQL clients send the
> comment as part of the statement text, and the command module strips only
> *leading* comment lines — so `PREPROC STATUS;` works but
> `PREPROC STATUS; -- check` is declined with a puzzling `syntax error`. Put
> comments on the line above. (Ordinary SQL is unaffected; this applies only to
> the `PREPROC` sugar.)

### Review what an install will create

An install is DDL executed under `PREPROC_ADMIN`, and a module's artifact may
carry **more than one statement** — a composite module installs every object in
its inventory, and an artifact may create objects in any schema the
installing admin can write. So the object inventory is declared up front rather
than discovered afterwards: `PREPROC CATALOG MODULES` returns each module's
`objects` inventory, and the install is refused outright if the artifact's
actual statements disagree with that declared inventory in either direction —
the same accept/reject discipline applied to `sha256`.

Review before installing, and audit after:

```sql
PREPROC CATALOG MODULES;                                    -- name, version, phase, objects, installed?
SELECT name, version, library_version, source_url, sha256, objects
FROM PREPROC_RT.INSTALLED_MODULES WHERE status = 'deployed';
```

`min_framework` in the registry states the lowest framework release a module
supports, but **nothing enforces it** — it is advisory metadata. Installing a
module onto an older framework than it declares will not be refused at
install time; it fails later, at use. Check your framework version first.

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
`v0.3.0`) instead. Supplying an `https:` source *is* the opt-in — there is no
toggle. On a no-egress cluster an `https:` source fails with a network error and
installs nothing (use BucketFS below instead).

### Locally via BucketFS (air-gapped, no egress)

> **Want this as one ordered procedure instead?** The framework ships a verified
> **[air-gap runbook](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/air-gap-runbook.md)**
> covering the whole path — collect artifacts → transfer → deploy the framework →
> stage in BucketFS → install → verify → roll back — with the real output and error
> messages at every step. Start there if you are doing this for the first time, or
> need something to hand a change board. The summary below is the module-install
> half only.

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

2. **Upload** `dist/preproc-lib-<ver>.tar.gz` into your BucketFS bucket, using the
   BucketFS **write** service and its write password:

   ```bash
   curl -k -X PUT --user w:<write-password> \
        -T dist/preproc-lib-0.3.0.tar.gz \
        https://<host>:2581/<bucket>/preproc-lib-0.3.0.tar.gz
   ```

   BucketFS auto-extracts the archive on arrival; you still reference it by the
   name you uploaded.

3. **Create a CONNECTION** naming that bucket and grant the admin role access
   (the framework never creates it — the operator does; the name is arbitrary):

   ```sql
   CREATE CONNECTION PREPROC_BFS TO 'bucketfs:bfsdefault/<bucket>' IDENTIFIED BY '<read-password>';
   GRANT ACCESS ON CONNECTION PREPROC_BFS TO PREPROC_ADMIN;
   ```

   > **Use the native BucketFS address — not the `https://…:2581/…` upload URL.**
   > The database reads BucketFS off its cluster-local mount
   > (`/buckets/<service>/<bucket>/…`), so the address takes the form
   > `bucketfs:<service>/<bucket>` with no host and no port — `<service>` is the
   > BucketFS service name, usually `bfsdefault`. The resolver **rejects** an
   > `https://` address here (`unsupported BucketFS connection address …`), and
   > the native form is what makes this path egress-free. The
   > `https://<host>:2581/…` URL in step 2 is the *upload* endpoint and is not
   > interchangeable with it. Give the bucket's **read** password — a different
   > credential from the write password in step 2 — and note that what gates
   > *who* may install from this bucket is the `GRANT ACCESS ON CONNECTION`
   > above, since the resolver reads the mount through the filesystem the UDF
   > already runs on.

4. **Install**, naming the archive exactly as uploaded:

   ```sql
   PREPROC CATALOG MODULES FROM 'bucketfs:PREPROC_BFS/preproc-lib-0.3.0.tar.gz';
   PREPROC INSTALL MODULE cast_shorthand FROM 'bucketfs:PREPROC_BFS/preproc-lib-0.3.0.tar.gz' FOR ROLE ANALYSTS;
   ```

   Note the two different meanings of `bucketfs:` — in the CONNECTION it names
   the *bucket* (`bucketfs:<service>/<bucket>`); in the source string it names
   the *CONNECTION object* plus a path inside that bucket
   (`bucketfs:<CONNECTION>/<path>`).

See the framework's
[docs/operations.md § In-database module install](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/operations.md#in-database-module-install)
for the CONNECTION setup, result columns, and the admin boundary in full.

## With the `preproc module` CLI

The CLI ships as part of `preprocessor-framework` — not with `release.sql` (the
framework's own toolchain-free engine deploy). It needs `uv` and a live DB
connection (`EXASOL_DSN`/`EXASOL_USER`/`EXASOL_PASSWORD`, see the framework's
[docs/operations.md](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/operations.md#environment-variables)):

```
uv run preproc module list --registry /path/to/preprocessor-library
uv run preproc module add cast_shorthand --registry /path/to/preprocessor-library
```

`--registry` also accepts a pinned `https://` URL to a hosted
`registry/index.json`, or is omitted entirely to use the framework's default
online registry pin. Beyond `add`, the CLI carries the verbs the SQL surface
does not: `search`, `update`, `remove`, `validate`, and a declarative `sync`
that converges a database to a desired-state TOML file in one pass.

For an air-gapped database, the CLI offers a second option beyond the BucketFS
path above: run `uv run preproc module bundle <name> --output x.sql` on a
connected machine, then hand-carry `x.sql` and run it directly in a SQL client —
no CLI or DB connection needed on the air-gapped side. Choose `bundle` for a
one-off hand-carry, BucketFS staging when the cluster should keep installing
modules on its own.

See the framework's [docs/operations.md § Module management](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/operations.md#module-management)
for the full CLI reference, and
[docs/module-authoring.md](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/module-authoring.md)
for the module contract (writing your own).

## Seeing it work end to end

The framework repo ships a runnable, narrated
[`demo/`](https://github.com/exasol-labs/preprocessor-framework/tree/main/demo)
suite verified against Exasol 2026.1 — including
[`02_module_from_github.sql`](https://github.com/exasol-labs/preprocessor-framework/blob/main/demo/02_module_from_github.sql)
(install a module from this library over HTTPS) and
[`03_module_from_bucketfs.sql`](https://github.com/exasol-labs/preprocessor-framework/blob/main/demo/03_module_from_bucketfs.sql)
(the same from a BucketFS-staged release). Start there if you would rather run
something than read.

## Contributing a module

This catalog only stays useful if people add to it. If you have written a
preprocessor that others would want, there are **two ways** to publish it — you
do not have to hand over your code to do it:

| | **Path 1 — library-deployed** | **Path 2 — external entry** |
|---|---|---|
| Your artifact lives | here, under `modules/<name>/` | in **your own repo** |
| This repo carries | the whole module | a curated pointer only |
| `deploy_mode` | `library-deployed` | `self-deployed` |
| Installed by | `PREPROC INSTALL MODULE <name>` — the framework deploys it | your own installer; the framework registers the rule + provenance |
| You add | a directory + `module.toml` + tests | one `registry/external/<name>.toml` |
| Best for | a self-contained transform | the front door to a product or subsystem you already ship |

**The shortest path to a PR:**

```bash
cp -r modules/_template modules/my_module     # 1. copy the template
# 2. rename my_module_v1.sql, write your Lua, fill in module.toml
uv run preproc module validate my_module --registry .    # 3. check it locally
python scripts/generate_index.py                          # 4. regenerate the index
# 5. open a PR
```

`validate` runs the same static gates CI does — manifest conformance, `sha256`,
and the declared-vs-parsed `[[objects]]` inventory in both directions — and, when
a database is configured, also compiles your artifact and smoke-tests your entry
function in a disposable schema.

Three things that trip up new contributors:

- **Every object carries your module's `_V<N>` suffix**, not just the entry
  script. This is what lets a v1 and a v2 coexist without collision.
- **A composite artifact must declare `[[objects]]`.** Optional for a
  single-statement artifact; mandatory the moment you add a second. CI rejects a
  disagreement in *either* direction.
- **`uv run preproc …` needs the framework package**, which is currently private
  and unpublished. From a local checkout:
  `pip install -e ../preprocessor-framework`, or export
  `PYTHONPATH=<checkout>/src`. Static gates then run offline; database-backed
  tests skip cleanly when `EXASOL_DSN` / `EXASOL_USER` / `EXASOL_PASSWORD` are
  unset.

After merge, your module becomes installable via `PREPROC INSTALL MODULE` once a
release moves the `latest` tag — merging alone is not enough, since the default
install source resolves that tag.

Full walkthrough, including composite modules and the external-entry format:
**[CONTRIBUTING.md](CONTRIBUTING.md)**. The module contract itself lives in the
framework's
[docs/module-authoring.md](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/module-authoring.md).

### Keeping it private instead

Publishing here is optional. A registry is just a `registry/index.json` plus the
artifacts it points at, so you can host your own internal catalog and install
from it with the same one-statement flow — see
[preprocessor-framework § Host your own module registry](https://github.com/exasol-labs/preprocessor-framework#host-your-own-module-registry).
Use this repo when you want *reach*, not because the mechanism requires it.
