# \_template

A copy-this-directory starting point for a new module. It is a complete,
working (but trivial) TRANSLATE-phase module — `template_module(sqltext)`
returns its input unchanged — so the registry generator and CI can index and
test it exactly like a real module, while its body and comments describe
every place you need to fill in your own logic.

## Using this template

1. Copy the whole `modules/_template/` directory to `modules/<your-module-name>/`.
2. Rename `_template_v1.sql` to `<your-module-name>_v1.sql` and edit its
   `CREATE OR REPLACE LUA SCRIPT` name and Lua body.
3. Edit `module.toml`: set `name` to your directory name, `script_name` /
   `function` / `description` to match your script, and regenerate `sha256`
   (`sha256sum <your-module-name>_v1.sql`).
4. Replace this `README.md` with what your module does and how to use it.
5. Replace `tests/` with your module's own tests.
6. Open a PR — CI regenerates `registry/index.json` from your `module.toml`
   and runs your `tests/` against a docker Exasol.

See `docs/module-authoring.md` in the `preprocessor-framework` repo for the
full contract (the function signature per phase, the `_V<N>` versioning
discipline, and the `module.toml` field reference), and `CONTRIBUTING.md` at
the root of this repo for the PR workflow.
