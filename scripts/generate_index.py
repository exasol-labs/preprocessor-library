#!/usr/bin/env python3
"""Regenerate ``registry/index.json`` from every ``modules/*/module.toml``.

This is the supported way to (re)write the committed federated index — do NOT
hand-edit ``registry/index.json`` (CI's drift-check regenerates it and fails on
any mismatch). The index is stamped with the library's release identity so an
install resolved through the mutable ``latest`` tag is auditable back to a
concrete release:

* top-level ``library_version`` — the contents of ``./VERSION`` (e.g. ``0.2.0``);
* each library-deployed entry's ``source.ref`` — the matching release tag
  ``v<VERSION>`` (e.g. ``v0.2.0``), an immutable pin rather than a moving branch.

The generation, the stamped values, and the tag formula MUST match CI's
drift-check (``.github/workflows/ci.yml``) exactly, or the freshly generated
index reads as drift against the committed file. Both read ``./VERSION`` and
derive ``ref = "v" + version`` — keep them in lock-step.

Requires the ``preprocessor-framework`` package (``preproc.module.registry``);
it is the same generator CI uses, so this is not an independent reimplementation.

Usage:
    python3 scripts/generate_index.py            # regenerate + write in place
    python3 scripts/generate_index.py --check     # exit 1 if the file is stale
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from preproc.module.registry import generate_index, index_drift, render_index

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INDEX_PATH = _REPO_ROOT / "registry" / "index.json"


def _version() -> str:
    version_file = _REPO_ROOT / "VERSION"
    if not version_file.is_file():
        sys.exit("./VERSION is missing")
    return version_file.read_text(encoding="utf-8").strip().lstrip("v")


def _ref(version: str) -> str:
    """The immutable release tag the index pins its source to."""
    return f"v{version}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if registry/index.json is out of sync.",
    )
    args = parser.parse_args()

    version = _version()
    ref = _ref(version)

    if args.check:
        drift = index_drift(_REPO_ROOT, ref=ref, library_version=version)
        if drift:
            for line in drift:
                print(line, file=sys.stderr)
            sys.exit(1)
        print("registry/index.json is in sync.")
        return

    index = generate_index(_REPO_ROOT, ref=ref, library_version=version)
    _INDEX_PATH.write_text(render_index(index), encoding="utf-8")
    print(f"Wrote {_INDEX_PATH.relative_to(_REPO_ROOT)}")
    print(f"  library_version : {version}")
    print(f"  source.ref      : {ref}")
    print(f"  modules         : {len(index.entries)}")


if __name__ == "__main__":
    main()
