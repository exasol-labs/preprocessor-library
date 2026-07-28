"""Shared helper: the registry stamping values ``scripts/generate_index.py`` uses.

``scripts/generate_index.py`` stamps the committed ``registry/index.json``
with ``library_version`` (read from ``./VERSION``) and ``ref = "v" + version``
(the matching release tag). Any test that regenerates the index and compares
it against the committed file — a "drift" check — MUST derive the same two
values the same way, or the freshly generated index reads as drift against
the committed file for no reason other than the test itself going stale at
the next release. This is the one place that derivation lives, so
``test_scaffolding.py`` and ``test_library_modules.py`` cannot go out of step
with each other or with the generator.
"""

from pathlib import Path


def stamping_args(repo_root: Path) -> dict[str, str]:
    """The (``ref``, ``library_version``) ``scripts/generate_index.py`` stamps the index with.

    Mirrors that script's own ``_version``/``_ref`` exactly, so a
    byte-identical regeneration check built from this can never diverge from
    what CI's drift-check runs.
    """
    version = (repo_root / "VERSION").read_text(encoding="utf-8").strip().lstrip("v")
    return {"ref": f"v{version}", "library_version": version}
