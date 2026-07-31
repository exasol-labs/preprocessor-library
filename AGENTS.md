# AGENTS.md

Instructions for an AI agent working in this repository. Humans: this is a
condensed, ordered version of [CONTRIBUTING.md](CONTRIBUTING.md) and
[RELEASING.md](RELEASING.md) — those remain the prose sources.

## What this repo is

The **module catalog** for `preprocessor-framework`. This repo holds module
artifacts and a generated federated index; the framework holds the engine, the
CLI, and the module contract. A change to how modules *behave* belongs in the
framework repo, not here.

`registry/index.json` is **generated**. Never hand-edit it — CI regenerates it
and fails on any difference.

## Setup

```bash
pip install "preprocessor-framework @ git+https://github.com/exasol-labs/preprocessor-framework.git@main"
pip install -r requirements-test.txt
```

`preproc module validate` and `scripts/generate_index.py` both need that
package. `uv run preproc …` does **not** work here — this repo has no
`pyproject.toml`, so `uv run` builds an environment without the framework and
fails with `Failed to spawn: preproc`. Call `preproc` directly.

> While `exasol-labs/preprocessor-framework` is private, that install needs
> credentials and the framework's `docs/module-authoring.md` — the authoritative
> module contract — may not be readable. The essentials are restated under
> [Contract rules](#contract-rules) below; when the doc is reachable, it wins.

## Adding a library-deployed module

Run these in order. Steps 5 and 6 are order-dependent: `validate` resolves a
module *through* the index, so a module that is not in the index yet fails with
`module '<name>' not found in registry`.

```bash
# 1. Copy the template. <name> is snake_case and a plain Exasol identifier:
#    a letter, then letters/digits/underscores. No hyphens, no leading
#    underscore. The directory name and module.toml's `name` must be equal.
cp -r modules/_template modules/<name>

# 2. Rename the artifact and the test file (the test file matters: two
#    identically-named test files in the tree are a collection hazard).
mv modules/<name>/my_module_v1.sql modules/<name>/<name>_v1.sql
mv modules/<name>/tests/test_template.py modules/<name>/tests/test_<name>.py

# 3. Write the artifact and the manifest (see below), then the digest:
sha256sum modules/<name>/<name>_v1.sql        # paste into module.toml's sha256

# 4. Write modules/<name>/README.md and the tests. Both are REQUIRED to merge —
#    tests/test_scaffolding.py fails a module with an empty README or a tests/
#    directory holding no test_*.py.

# 5. Regenerate the index (do this before step 6).
python scripts/generate_index.py

# 6. Verify exactly what CI verifies.
preproc module validate <name> --registry .
pytest

# 7. Commit the module directory AND registry/index.json together.
```

Re-run steps 3, 5 and 6 after **every** edit to the artifact: changing one byte
invalidates the `sha256` in the manifest and the index built from it.

### The manifest

`module.toml` fields, all required unless noted: `name` (= directory name),
`description`, `phase` (`TRANSLATE` | `EXPAND` | `REWRITE`), `script_name`
(fully qualified, ending `_V<N>`), `function` (the exported Lua function),
`version` (an integer equal to `<N>`), `min_framework`, `sha256`,
`deploy_mode = "library-deployed"`, a `[suggested_scope]` table (`type` =
`ROLE` | `USER`, and `value`), and `[[objects]]` (required only for a composite
artifact — see below). `modules/_template/module.toml` is a working annotated
example.

### Contract rules

- The entry function takes the statement text and returns `nil` or a string.
  **`TRANSLATE` and `REWRITE` must return a string on every path** — return the
  input unchanged when not transforming. In `EXPAND`, `nil` means "not my
  command, keep scanning".
- **No defensive `pcall`.** The dispatcher's `pcall` is the only error boundary;
  wrapping your own body converts a visible fault into a silent wrong answer and
  is a contract violation.
- The entry function must be a **top-level global** — a `local` function is
  invisible to `import`.
- `string.gsub` returns **two** values; never forward its result directly.
- Every deployed object carries the module's `_V<N>` suffix, so two generations
  can coexist.

### Composite artifacts (more than one statement)

- Separate statements with the EXAplus block-marker convention: a statement
  whose body contains semicolons (any Lua or Python script body) goes between a
  line that is exactly `--/` and a line that is exactly `/`; any other statement
  ends with `;`. This keeps the artifact runnable by hand in EXAplus.
- `[[objects]]` becomes **mandatory** — one `{ type = "...", name = "..." }`
  entry per object the artifact creates, e.g.
  `{ type = "PYTHON3 SCALAR SCRIPT", name = "PREPROC_RT.MY_MODULE_HELPER_V1" }`.
  Every declared name carries the `_V<N>` suffix, companions included.
- Tooling parses the artifact independently and rejects the module if the
  declared and parsed inventories disagree in **either** direction. An object
  you create but do not declare fails exactly like an object you declare but do
  not create.
- Objects may live in any schema the installing admin can write, not only
  `PREPROC_RT`.

## Registering an externally-hosted module

For a module whose artifact lives in, and is deployed from, another repo: add
one file, `registry/external/<name>.toml`, with the same fields plus
`deploy_mode = "self-deployed"` and a `[source]` table (`repo`, `ref`), and no
`sha256`. Then regenerate the index and open a PR. See CONTRIBUTING.md § Path 2.

## Releasing

Merging does not publish. A module becomes installable only when a `v*` tag
moves the mutable `latest` tag. The full sequence — bump `VERSION`, regenerate
the index, commit both, tag `v<VERSION>`, push — is in
[RELEASING.md](RELEASING.md). Do not tag a commit whose `VERSION` disagrees with
the tag; the release workflow rejects it.

## Do not

- Hand-edit `registry/index.json`.
- Edit `modules/_template/` when adding a module — copy it.
- Rename or re-`CREATE OR REPLACE` a published `_V<N>` object. A behaviour
  change ships as `_V<N+1>` with a new artifact file and manifest `version`.
- Add test dependencies to a CI step instead of `requirements-test.txt`. A
  `skipif`-guarded test skips silently when its package is missing, so a check
  is only as reliable as its declaration.
- Change a module's `phase` or `script_name` casually — both are behaviour, and
  `tests/test_scaffolding.py` pins them for the modules already published.
