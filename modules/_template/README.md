# \_template

A copy-this-directory starting point for a new module. It is a complete,
working (but trivial) TRANSLATE-phase module — `my_module(sqltext)`
returns its input unchanged — so the registry generator and CI can index and
test it exactly like a real module, while its body and comments describe
every place you need to fill in your own logic. Its `name` (`my_module`) and
`_V1` artifact (`my_module_v1.sql`) are placeholder values, deliberately
different from this directory's own name (`_template`, kept `_`-prefixed so
the registry generator skips indexing it) — rename both to match your own
module's directory when you copy this template.

## Using this template

1. Copy the whole `modules/_template/` directory to `modules/<your-module-name>/`.
2. Rename `my_module_v1.sql` to `<your-module-name>_v1.sql` and edit its
   `CREATE OR REPLACE LUA SCRIPT` name and Lua body.
3. Edit `module.toml`: set `name` to your directory name, `script_name` /
   `function` / `description` to match your script, and regenerate `sha256`
   (`sha256sum <your-module-name>_v1.sql`). If your module is the front door
   to a whole subsystem, its artifact MAY carry more than the one entry
   script — a Python UDF, a table, further Lua scripts — in the same `.sql`
   file, separated by the `--/` … `/` block-marker convention documented in
   this template's `module.toml` (see its `[[objects]]` comment block). Once
   the artifact carries more than one statement, `module.toml` MUST declare
   `[[objects]]` naming every object it creates, each carrying this module's
   `_V<N>` suffix.
4. Replace this `README.md` with what your module does and how to use it.
5. Replace `tests/` with your module's own tests — **rename
   `tests/test_template.py`** as you go. A `cp -r` carries that basename into
   your directory, and two test files with the same name in one tree are a
   collection hazard for anyone running `pytest` without this repo's
   `pytest.ini`.
6. Open a PR — CI regenerates `registry/index.json` from your `module.toml`
   and runs your `tests/` against a docker Exasol.

A module needs its `README.md` and its `tests/` to merge: both are checked by
`tests/test_scaffolding.py`, over every `modules/*/` directory.

## Testing it before you open a PR

You do not need a merged PR (or any network) to install and try your module — a
local checkout works as a registry source. Regenerate the index **first**: both
commands resolve your module through `registry/index.json`, and a freshly
copied directory is not in it yet.

```
python scripts/generate_index.py                        # your module joins the index
preproc module validate <your-module-name> --registry .
preproc module add <your-module-name> --registry .      # needs a database
```

`validate` runs the static conformance checks (manifest, `sha256`, and the
declared-vs-parsed `[[objects]]` inventory) and, when a database is configured,
also compiles your artifact's statements and smoke-tests the entry function in a
disposable schema. Run it before every commit — it catches the same things CI
will. Commit the regenerated index alongside your module.

Both commands need the framework package on your machine; see
`CONTRIBUTING.md` § Contributor tooling at the root of this repo.

The SQL-side `PREPROC INSTALL MODULE` path resolves modules from a *published*
index, so it only sees your module once your PR is merged and released; use the
CLI with `--registry .` while developing.

See `docs/module-authoring.md` in the `preprocessor-framework` repo for the
full contract (the function signature per phase, the `_V<N>` versioning
discipline, and the `module.toml` field reference), and `CONTRIBUTING.md` at
the root of this repo for the PR workflow.
