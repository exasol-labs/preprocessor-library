#!/usr/bin/env python3
"""Build the ``preproc-lib-<version>.tar.gz`` release tarball for BucketFS install.

The preprocessor framework's in-database installer
(``PREPROC.MODULE_RESOLVER_V1`` / ``PREPROC.MODULE_INSTALL``) reads a module
either over HTTPS from a ``registry/index.json`` URL, or NATIVELY off a
BucketFS-staged release tarball. The HTTPS path needs nothing beyond this repo
served at raw URLs; the BucketFS path needs a single ``.tar.gz`` archive laid
out exactly the way the resolver reads it:

    preproc-lib-<version>.tar.gz
    ├── registry/index.json                       (the federated index)
    └── modules/<name>/<name>_v<N>.sql            (each library-deployed artifact)

BucketFS AUTO-EXTRACTS an uploaded archive to a directory at the extension-less
path (``preproc-lib-<version>/``), and the resolver reads ``registry/index.json``
plus each entry's ``artifact_path`` relative to that root (a raw-tarball fallback
covers buckets that do not auto-extract). This script therefore packs those exact
members at those exact arcnames.

Trust boundary: as it packs, the script RE-VERIFIES every library-deployed
artifact's sha256 against the value the committed index declares — the same check
the resolver performs in the database — so a stale index or a tampered artifact
fails the build rather than shipping a bad tarball. (Index-vs-``module.toml``
drift is covered separately by the CI ``drift-check`` job, which needs the
framework package; this build is deliberately stdlib-only so it runs anywhere.)

Usage:
    python3 scripts/build_release.py                 # version from ./VERSION
    python3 scripts/build_release.py --version 0.2.0
    python3 scripts/build_release.py --output-dir dist
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INDEX_MEMBER = "registry/index.json"
# Fixed metadata so the same sources always produce a byte-identical tarball.
_EPOCH = 0


def _read_version(explicit: str | None) -> str:
    if explicit:
        return explicit.lstrip("v")
    version_file = _REPO_ROOT / "VERSION"
    if not version_file.is_file():
        sys.exit("no --version given and ./VERSION is missing")
    return version_file.read_text(encoding="utf-8").strip().lstrip("v")


def _load_index() -> dict:
    index_path = _REPO_ROOT / _INDEX_MEMBER
    if not index_path.is_file():
        sys.exit(f"{_INDEX_MEMBER} not found; is this the library repo root?")
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"{_INDEX_MEMBER} is not valid JSON: {exc}")


def _artifact_members(index: dict) -> list[tuple[str, bytes]]:
    """Return (arcname, bytes) for each library-deployed artifact, sha-verified.

    A self-deployed entry (null ``artifact_path``) carries no bundled artifact
    and is index-metadata only, so it contributes no tarball member.
    """
    members: list[tuple[str, bytes]] = []
    for entry in index.get("modules", []):
        artifact_path = entry.get("artifact_path")
        if not artifact_path:
            continue
        abspath = _REPO_ROOT / artifact_path
        if not abspath.is_file():
            sys.exit(f"{entry['name']}: declared artifact {artifact_path} is missing")
        data = abspath.read_bytes()
        declared = (entry.get("sha256") or "").lower()
        actual = hashlib.sha256(data).hexdigest()
        if not declared:
            sys.exit(f"{entry['name']}: index declares no sha256 for a library-deployed artifact")
        if actual != declared:
            sys.exit(
                f"{entry['name']}: sha256 mismatch — index declares {declared}, "
                f"{artifact_path} hashes to {actual}. Regenerate registry/index.json."
            )
        members.append((artifact_path, data))
    return members


def _add(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mtime = _EPOCH
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


def build(version: str, output_dir: Path) -> Path:
    index = _load_index()
    index_bytes = (_REPO_ROOT / _INDEX_MEMBER).read_bytes()
    artifacts = _artifact_members(index)

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"preproc-lib-{version}.tar.gz"

    # Sort members for a deterministic archive; gzip with mtime=0 (via GzipFile)
    # so repeated builds of the same sources are byte-identical.
    members: list[tuple[str, bytes]] = sorted(
        [(_INDEX_MEMBER, index_bytes), *artifacts], key=lambda m: m[0]
    )
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for arcname, data in members:
            _add(tar, arcname, data)
    import gzip

    with open(dest, "wb") as fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=_EPOCH) as gz:
            gz.write(raw.getvalue())

    tarball_sha = hashlib.sha256(dest.read_bytes()).hexdigest()
    print(f"Built {dest.relative_to(_REPO_ROOT)}")
    print(f"  version : {version}")
    print(f"  members : {len(members)} ({_INDEX_MEMBER} + {len(artifacts)} artifact(s))")
    for arcname, _ in members:
        print(f"            {arcname}")
    print(f"  sha256  : {tarball_sha}")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default=None, help="Release version (default: ./VERSION).")
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Directory to write the tarball into (default: dist/).",
    )
    args = parser.parse_args()
    build(_read_version(args.version), _REPO_ROOT / args.output_dir)


if __name__ == "__main__":
    main()
