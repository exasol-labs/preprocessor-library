<div align="center">

# preprocessor-library

**Ready-to-use SQL preprocessors for Exasol.**

[![Release](https://img.shields.io/github/v/release/exasol-labs/preprocessor-library?sort=semver)](https://github.com/exasol-labs/preprocessor-library/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Exasol](https://img.shields.io/badge/Exasol-2025.x%20%7C%202026.1-1ba0e2.svg)](https://www.exasol.com/)
[![framework](https://img.shields.io/badge/preprocessor--framework-required-blue)](https://github.com/exasol-labs/preprocessor-framework)

</div>

https://github.com/user-attachments/assets/001fc2dd-3bc8-4d96-964c-0a33e7919077

> Don't see the video? [Watch the demo](https://github.com/exasol-labs/preprocessor-framework/blob/main/demo/Preprocessor_demo.mp4).


Pick one from the catalog below and install it in a single statement — then, if
you build something useful, [add it here](#contributing-a-module) so others can
do the same.

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
> You only need this repo when you want to **publish** it or use a community-written preprocessor.

## The catalog

| Module | Phase | What it does |
|---|---|---|
| **[cast_shorthand](modules/cast_shorthand/)** | TRANSLATE | PostgreSQL-style `expr::type` → `CAST(expr AS type)`. Eases a Postgres/Redshift port. |
| **[trailing_comma](modules/trailing_comma/)** | TRANSLATE | Removes trailing commas before `)` or a list-terminating keyword, so `SELECT a, b, FROM t` just works. |

```sql
PREPROC CATALOG MODULES;                                   -- browse the live catalog
PREPROC INSTALL MODULE cast_shorthand FOR ROLE ANALYSTS;   -- install one
```

## Installing a module

A DBA holding `PREPROC_ADMIN` installs a module with a single statement. The
database reads the module, verifies its `sha256`, installs every statement in
its artifact in file order, and registers its activation rule in one step.
There are two sources — pick by whether the database has outbound internet.

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
`v0.3.1`) instead. Supplying an `https:` source *is* the opt-in — there is no
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

1. **Get the tarball.** Download `preproc-lib-<ver>.tar.gz` from
   [Releases](https://github.com/exasol-labs/preprocessor-library/releases).

   Building it yourself is the same artifact, and is the only option on a fork
   or at a commit no release was cut from (stdlib-only, no framework needed):

   ```bash
   python3 scripts/build_release.py            # writes dist/preproc-lib-<VERSION>.tar.gz
   ```

   The archive holds `registry/index.json` plus each library-deployed artifact at
   its `modules/<name>/<name>_v<N>.sql` path — exactly the layout the resolver
   reads. The build re-verifies every artifact's sha256 against the index as it
   packs, and is byte-reproducible.

2. **Upload** `preproc-lib-<ver>.tar.gz` into your BucketFS bucket, using the Admin UI or curl:

   ```bash
   curl -k -X PUT --user w:<write-password> \
        -T preproc-lib-0.3.1.tar.gz \
        https://<host>:2581/<bucket>/preproc-lib-0.3.1.tar.gz
   ```

   BucketFS auto-extracts the archive on arrival; you still reference it by the
   name you uploaded.

3. If the bucket you uploaded to is protected by a read password, you must Create a CONNECTION naming that bucket and grant the admin role access. For example:

   ```sql
   CREATE CONNECTION PREPROC_BFS TO 'bucketfs:bfsdefault/<bucket>' IDENTIFIED BY '<read-password>';
   GRANT ACCESS ON CONNECTION PREPROC_BFS TO PREPROC_ADMIN;
   ```

4. **Install**, naming the archive exactly as uploaded:

   ```sql
   PREPROC CATALOG MODULES FROM 'bucketfs:bfsdefault/<bucket>/preproc-lib-<ver>.tar.gz';
   PREPROC INSTALL MODULE cast_shorthand FROM 'bucketfs:bfsdefault/<bucket>/preproc-lib-<ver>.tar.gz' FOR ROLE ANALYSTS;
   ```

See the framework's
[docs/operations.md § In-database module install](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/operations.md#in-database-module-install)
for the CONNECTION setup, result columns, and the admin boundary in full.

### After installing: verify, then turn it off again

Installing registers an activation rule; it does not change what a session that
already ran sees, and it reaches a user only if that user **holds** the scope
role. Verify from the *target* user's session, not the admin's:

```sql
SELECT * FROM PREPROC_RT.MY_PIPELINE;      -- the "does this affect me?" view
SELECT 1::INT FROM dual;                   -- the module's own effect
```

An empty `MY_PIPELINE` means no rule resolves to that user — the usual causes
are not holding the role, or the preprocessor not being activated for the
session. On the admin side, `PREPROC CATALOG MODULES` reports `installed` per
module and `PREPROC_RT.INSTALLED_MODULES` carries the provenance row.

Turning a module off is a rule operation — the activation rule is what makes a
deployed script reach anyone:

```sql
PREPROC LIST RULES;                        -- find the rule naming the module's script
PREPROC DISABLE RULE <rule_id>;            -- reversible; the rule stays listed
PREPROC DROP RULE <rule_id>;               -- removes the activation entirely
```

Both leave the `PREPROC_RT.<NAME>_V<N>` script deployed, on purpose — an
in-flight session is never stranded by a dropped rule. Retiring the provenance
row and physically reclaiming the script are separate later steps; see the
framework's
[docs/operations.md § Module lifecycle](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/operations.md#module-lifecycle)
and the [air-gap runbook § Rollback](https://github.com/exasol-labs/preprocessor-framework/blob/main/docs/air-gap-runbook.md)
for the full retire-then-reclaim discipline.

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
cp -r modules/_template modules/my_module            # 1. copy the template
# 2. rename my_module_v1.sql and tests/test_template.py, write your Lua,
#    fill in module.toml
python scripts/generate_index.py                     # 3. regenerate the index
preproc module validate my_module --registry .       # 4. check it locally
pytest                                               # 5. run the suite
# 6. open a PR
```

**Regenerate the index before you validate.** `validate` resolves your module
*through* `registry/index.json`, so on a freshly copied directory it fails with
`module 'my_module' not found in registry` until step 3 has run.

`validate` runs the same static gates CI does — manifest conformance, `sha256`,
and the declared-vs-parsed `[[objects]]` inventory in both directions — and, when
a database is configured, also compiles your artifact and smoke-tests your entry
function in a disposable schema. Both commands need the framework package on
your machine; see [CONTRIBUTING.md § Contributor tooling](CONTRIBUTING.md#contributor-tooling)
for the one-time setup.

Three things that trip up new contributors:

- **Every object carries your module's `_V<N>` suffix**, not just the entry
  script. This is what lets a v1 and a v2 coexist without collision.
- **A composite artifact must declare `[[objects]]`.** Optional for a
  single-statement artifact; mandatory the moment you add a second. CI rejects a
  disagreement in *either* direction.
- **Rename the copied test file too.** `modules/_template/tests/test_template.py`
  keeps its basename through a `cp -r`, and two identically-named test files are
  a collection hazard the moment anyone runs `pytest` without this repo's
  `pytest.ini`.

- **`preproc` and `scripts/generate_index.py` need the framework package.** One
  `pip install` from a checkout or a git URL — see
  [CONTRIBUTING.md § Contributor tooling](CONTRIBUTING.md#contributor-tooling).
  Static gates then run offline; database-backed tests skip cleanly when
  `EXASOL_DSN` / `EXASOL_USER` / `EXASOL_PASSWORD` are unset.

After merge, your module becomes installable via `PREPROC INSTALL MODULE` once a
release moves the `latest` tag — merging alone is not enough, since the default
install source resolves that tag. Cutting that release is
**[RELEASING.md](RELEASING.md)**.

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
