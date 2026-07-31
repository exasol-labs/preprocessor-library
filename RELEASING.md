# Releasing

Merging a module does not make it installable. The default install source —
`PREPROC INSTALL MODULE <name>;` with no `FROM` clause — resolves
`exasol-labs/preprocessor-library@latest`, and the mutable `latest` tag only
moves when a `v*` tag is pushed. Cutting a release is what publishes a merged
module.

## The one invariant

Three things must name the same version, and each is derived from a different
place:

| Artifact | Version comes from |
|---|---|
| `preproc-lib-<ver>.tar.gz` and the GitHub Release | the **tag** |
| `registry/index.json`'s `library_version`, and every entry's `source.ref` | **`./VERSION`**, stamped by `scripts/generate_index.py` |

Nothing reconciles them at runtime, so the release workflow refuses a `v*` tag
that does not equal `v<VERSION>` before it builds anything. Bump `VERSION` and
regenerate the index **in the same commit you tag**.

## Cutting a release

```bash
# 1. Bump the version (semver; a new module is a MINOR bump, a fix to an
#    existing one a PATCH).
echo 0.4.0 > VERSION

# 2. Restamp the index: library_version = 0.4.0, every source.ref = v0.4.0.
python scripts/generate_index.py

# 3. Confirm the tree is clean and in sync.
pytest
python scripts/generate_index.py --check

# 4. Commit both files together — VERSION and registry/index.json.
git add VERSION registry/index.json
git commit -m "chore(release): bump version to 0.4.0"

# 5. Tag that exact commit and push both.
git tag v0.4.0
git push origin main
git push origin v0.4.0
```

Pushing the tag runs `.github/workflows/release.yml`, which:

1. checks `v0.4.0` equals `v<VERSION>` and fails the release if not;
2. builds `dist/preproc-lib-0.4.0.tar.gz` (stdlib-only — no framework, no
   token, no network);
3. creates the GitHub Release if the tag has none yet, and attaches the tarball;
4. force-moves the mutable `latest` tag onto the release commit.

Step 4 is what makes the new module installable from a plain
`PREPROC INSTALL MODULE <name>;`. Raw GitHub serving is CDN-cached (~5 min), so
allow a few minutes before the moved tag resolves everywhere.

## Why a merged-but-unreleased module looks odd

`generate_index.py` stamps `source.ref = v<VERSION>` from the **committed**
`VERSION`, not from a tag that exists. Between merging a module and cutting the
next release, the index therefore advertises that module at the *previous*
release's tag — a ref whose tree does not contain it. This is expected, and it
resolves itself at the next release, when the same generator restamps every
entry at the new tag. It is also why the `latest` tag, not `main`, is the
default install source: `latest` never points at that intermediate state.

## When the framework repo goes public

`exasol-labs/preprocessor-framework` is private today, and several places in
this repo work around that. When both repos are published, sweep all of them in
one pass — each is a workaround that becomes misleading the moment it is untrue:

- [ ] `.github/workflows/ci.yml` — delete the `FRAMEWORK_TOKEN` gating from both
      jobs and install the framework from the plain public git URL, so the
      static gates and module tests always run instead of skipping. **This is
      the important one:** with the secret absent, both jobs currently skip and
      the pipeline reports green with no gates run at all — on every fork PR.
- [ ] `requirements-test.txt` — the comment block explaining why the framework
      cannot be listed as a dependency. Once it is installable anonymously,
      decide whether to list it and shorten the comment either way.
- [ ] `CONTRIBUTING.md` § Contributor tooling — the git-URL install line can
      drop any token/checkout caveat.
- [ ] `README.md` — check the framework cross-links resolve, including the
      anchors: `#quick-start`, `#bring-your-own-preprocessor`,
      `#host-your-own-module-registry`, `docs/module-authoring.md`,
      `docs/operations.md#in-database-module-install`,
      `docs/operations.md#module-lifecycle`, `docs/air-gap-runbook.md`.
- [ ] `AGENTS.md` — the note that the module contract lives in a repo an agent
      may not be able to read.
