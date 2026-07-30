# Contributing

There are two ways to add a module to the federated registry this repo hosts.
Pick whichever fits: a library-deployed module lives its whole life here;
an externally-hosted module keeps living in its own repo and gets one curated
entry pointing at it.

## Path 1 — Add a library-deployed module (PR into `modules/`)

Use this when your module's whole artifact can live in this repo.

1. Copy `modules/_template/` to `modules/<your-module-name>/` (`snake_case`,
   an identifier — a letter followed by letters, digits, or underscores, no
   hyphens — matching the directory name you choose: `module.toml`'s `name`
   must equal it and must itself be a plain identifier so it works unquoted
   in `PREPROC INSTALL MODULE <name>`).
2. Rename `my_module_v1.sql` to `<your-module-name>_v1.sql` and replace its
   body with your module's `CREATE OR REPLACE LUA SCRIPT PREPROC_RT.<NAME>_V1
   AS <lua body>`. A ten-line transform stays a single statement — still the
   common case, and it needs no `[[objects]]` array (see step 3). A module
   that is the front door to a whole subsystem MAY ship further statements in
   the same artifact — a Python UDF, a table, further Lua scripts — instead
   of being pushed into `self-deployed` for the sole reason that it has more
   than one object to deliver; see "Contributing a composite module" below.
   See `docs/module-authoring.md` in the `preprocessor-framework` repo for the
   full function contract (the `fn(text) -> nil|string` signature per phase,
   the fail-open/fail-closed rules, the "no defensive `pcall`" rule) and the
   `_V<N>` versioning discipline.
3. Fill in `module.toml`: `name` (matches your directory), `description`,
   `phase` (`TRANSLATE` / `EXPAND` / `REWRITE`), `script_name`, `function`,
   `version` (must match the `_V<N>` suffix), `min_framework`,
   `suggested_scope`, `deploy_mode = "library-deployed"`, and `sha256` — the
   hex digest of your artifact file's bytes (`sha256sum <name>_v1.sql`). Add
   `[[objects]]` once your artifact carries more than one statement — see
   "Contributing a composite module" below; it is optional for a
   single-statement artifact.
4. Write `README.md` describing what your module does, its behaviour, and how
   to install it (see `modules/cast_shorthand/README.md` for the shape).
5. Write `tests/` — at minimum, a static test that your manifest parses and
   your artifact's inventory and sha256 match it (see
   `src/preproc/module/manifest.py`'s `load_manifest` /
   `verify_artifact_inventory` / `verify_artifact_sha256` in the framework
   package), plus integration tests against a real Exasol instance for your
   module's actual behaviour, using the `installed` fixture from this repo's
   root `conftest.py`.

   Test dependencies are declared in `requirements-test.txt` at the repo root.
   Add anything new there rather than to a CI step, or it lands in one job and
   is missing from the other. This matters more than it looks: a
   `skipif`-guarded test SKIPS SILENTLY when its package is absent, so a check
   guarded that way is only ever as reliable as the declaration.

   To run the suite locally you also need the framework package, which is
   private and unpublished: `pip install -e ../preprocessor-framework` from a
   local checkout, or export `PYTHONPATH=<checkout>/src`. The database-backed
   tests skip cleanly when `EXASOL_DSN` / `EXASOL_USER` / `EXASOL_PASSWORD` are
   unset, so plain `pytest` with no database configured runs every static gate
   and skips only the rest.
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

### Contributing a composite module

A module that is the front door to a whole subsystem — not just a syntax
transform — can ship its Python UDFs, tables, or further Lua scripts in the
same artifact as its entry script, instead of being forced into `self-deployed`
where this repo could only ever carry a pointer.

* **One artifact, one or more statements.** Separate statements with the
  EXAplus block-marker convention: wrap a statement whose body contains
  semicolons (a Lua or Python script body) between a line consisting solely of
  `--/` and a line consisting solely of `/`; terminate any other statement
  with `;`. This is what keeps the artifact directly runnable by hand in
  EXAplus for an air-gapped deployment — the actual reason the whole-file
  hand-carry story survives having more than one statement.
* **Declare every object in `[[objects]]`.** Once your artifact carries more
  than one statement, `module.toml` MUST declare a `[[objects]]` array naming
  every object it creates — `{ type = "...", name = "..." }` per object, e.g.
  `{ type = "PYTHON3 SCALAR SCRIPT", name = "PREPROC_RT.MY_MODULE_HELPER_V1" }`.
  It is optional only for a single-statement artifact, where the inventory is
  derived as the single entry named by `script_name`.
* **Every object carries the module's `_V<N>` suffix** — the entry script and
  every companion, not only the entry script — so a v1 and a v2 generation
  coexist without collisions, even when a companion's body is byte-identical
  between generations.
* **Objects may live in any writable schema**, not only `PREPROC_RT`/`PREPROC`
  — a subsystem module legitimately owns its own schema.
* **CI rejects drift.** Tooling independently parses your artifact and derives
  its own object inventory; the module is rejected if the declared and parsed
  inventories disagree in EITHER direction (an object your artifact creates
  but `module.toml` doesn't declare, or vice versa) — the same accept/reject
  discipline already applied to `sha256`.

See `docs/module-authoring.md`'s "The canonical artifact" and
"`module.toml` schema" sections in the `preprocessor-framework` repo for the
full grammar, the `[[objects]]` field reference, and a worked composite
(Lua entry + Python UDF) example, and `modules/_template/module.toml`'s
`[[objects]]` comment block for a copy-in starting point.

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

Every check that does not need a database runs in the `drift-check` job, which
runs the whole of `tests/`. Only the module suites, which do need one, wait for
the docker-Exasol job:

* `registry/index.json` is regenerated from `modules/*/module.toml` and
  `registry/external/*.toml` and compared to the committed file — a mismatch
  fails the build.
* Every module's declared `[[objects]]` inventory is compared against its
  artifact's independently parsed inventory — a disagreement in either
  direction fails the build, same as a `sha256` mismatch.
* Every module's `sha256`, directory layout and manifest conformance are
  checked.
* Every module's `tests/` run against a docker Exasol with the framework
  installed.
