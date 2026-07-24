# Contributing

There are two ways to add a module to the federated registry this repo hosts.
Pick whichever fits: a library-deployed module lives its whole life here;
an externally-hosted module keeps living in its own repo and gets one curated
entry pointing at it.

## Path 1 — Add a library-deployed module (PR into `modules/`)

Use this when your module's whole artifact can live in this repo.

1. Copy `modules/_template/` to `modules/<your-module-name>/` (kebab-case,
   matching the directory name you choose).
2. Rename `_template_v1.sql` to `<your-module-name>_v1.sql` and replace its
   body with your module's `CREATE OR REPLACE LUA SCRIPT PREPROC_RT.<NAME>_V1
   AS <lua body>` — exactly one statement, nothing else in the file. See
   `docs/module-authoring.md` in the `preprocessor-framework` repo for the
   full function contract (the `fn(text) -> nil|string` signature per phase,
   the fail-open/fail-closed rules, the "no defensive `pcall`" rule) and the
   `_V<N>` versioning discipline.
3. Fill in `module.toml`: `name` (matches your directory), `description`,
   `phase` (`TRANSLATE` / `EXPAND` / `REWRITE`), `script_name`, `function`,
   `version` (must match the `_V<N>` suffix), `min_framework`,
   `suggested_scope`, `deploy_mode = "library-deployed"`, and `sha256` — the
   hex digest of your artifact file's bytes (`sha256sum <name>_v1.sql`).
4. Write `README.md` describing what your module does, its behaviour, and how
   to install it (see `modules/cast_shorthand/README.md` for the shape).
5. Write `tests/` — at minimum, a static test that your manifest parses and
   your artifact's script name and sha256 match it (see
   `src/preproc/module/manifest.py`'s `load_manifest` /
   `verify_artifact_script_name` / `verify_artifact_sha256` in the framework
   package), plus integration tests against a real Exasol instance for your
   module's actual behaviour, using the `installed` fixture from this repo's
   root `conftest.py`.
6. Regenerate the index and commit it alongside your module:

   ```
   python scripts/generate_index.py     # requires the preprocessor-framework package
   ```

   This stamps the index with the library's `library_version` (from `./VERSION`)
   and pins each entry's `source.ref` to the matching release tag `v<VERSION>`.
7. Open a PR. CI deploys your module against a docker Exasol, runs your
   `tests/`, and runs `python scripts/generate_index.py --check`, failing if the
   committed `registry/index.json` is out of sync.

Do **not** hand-edit `registry/index.json` for a library-deployed module; it is
generated from every `modules/*/module.toml` by `scripts/generate_index.py`.

## Path 2 — Register an external repo (PR into `registry/external/`)

Use this when your module's artifact lives in, and is deployed from, your own
repo (a `self-deployed` module — e.g. the front door to an existing
subsystem). This repo never fetches or hosts your code; it only carries a
curated pointer, and a human reviewing your PR is the trust gate.

1. Add one file, `registry/external/<your-module-name>.toml`, with the same
   fields as a `module.toml` (see `docs/module-authoring.md`), plus a
   `[source]` table naming your repo and the ref you pin releases to:

   ```toml
   name = "your-module-name"
   description = "..."
   phase = "EXPAND"
   script_name = "YOUR_SCHEMA.ENTRY_V3"
   function = "expand"
   version = 3
   min_framework = "0.3.0"
   deploy_mode = "self-deployed"

   [suggested_scope]
   type = "ROLE"
   value = "YOUR_ROLE"

   [source]
   repo = "your-org/your-repo"
   ref = "v3.0.0"
   ```

2. `self-deployed` entries do not carry a `sha256` — your own installer
   deploys the artifact; the framework CLI only registers the rule
   (`RULE_ENSURE`) and records provenance for it.
3. Open a PR. A maintainer reviews that the repo, ref, and metadata are
   legitimate before merging — that review is the entire trust boundary for
   external entries, since nothing here is auto-crawled. Once merged, CI's
   index regeneration picks up your entry automatically.

## What CI checks on every PR

* Every module's `tests/` run against a docker Exasol with the framework
  installed.
* `registry/index.json` is regenerated from `modules/*/module.toml` and
  `registry/external/*.toml` and compared to the committed file — a mismatch
  fails the build.
