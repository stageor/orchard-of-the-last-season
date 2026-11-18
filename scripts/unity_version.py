#!/usr/bin/env python3
"""Read the Unity editor version from ProjectSettings/ProjectVersion.txt.

CI must never hard-code or silently upgrade the editor version. This module is the single
source of truth used by the workflows, the build verifier and the repository validator.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+[abcfpx]\d+$")
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IMAGE_SUFFIX = "3.2.2"

FLAVORS = ("base", "windows-mono", "windows-il2cpp", "webgl", "android", "ios", "mac-mono")


def read_version(project_root: str | Path = DEFAULT_PROJECT_ROOT) -> str:
    """Return m_EditorVersion from ProjectSettings/ProjectVersion.txt."""
    path = Path(project_root) / "ProjectSettings" / "ProjectVersion.txt"
    if not path.is_file():
        raise FileNotFoundError(f"missing Unity version file: {path}")
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^\s*m_EditorVersion:\s*(\S+)\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"{path} has no m_EditorVersion line")
    version = match.group(1)
    if not VERSION_RE.match(version):
        raise ValueError(f"unexpected Unity version {version!r} in {path}")
    return version


def read_revision(project_root: str | Path = DEFAULT_PROJECT_ROOT) -> str | None:
    path = Path(project_root) / "ProjectSettings" / "ProjectVersion.txt"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^\s*m_EditorVersionWithRevision:\s*\S+\s+\(([0-9a-fA-F]+)\)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def image_for(version: str, flavor: str = "base", suffix: str = DEFAULT_IMAGE_SUFFIX) -> str:
    if flavor not in FLAVORS:
        raise ValueError(f"unknown GameCI flavor {flavor!r}; expected one of {', '.join(FLAVORS)}")
    return f"unityci/editor:ubuntu-{version}-{flavor}-{suffix}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(DEFAULT_PROJECT_ROOT))
    parser.add_argument("--image", action="store_true", help="print the exact GameCI ubuntu image")
    parser.add_argument("--flavor", default="base", choices=FLAVORS)
    parser.add_argument("--tag-suffix", default=DEFAULT_IMAGE_SUFFIX)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        version = read_version(args.project_root)
        revision = read_revision(args.project_root)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"version": version, "revision": revision, "image": image_for(version, args.flavor, args.tag_suffix)}))
        return 0
    if args.image:
        print(image_for(version, args.flavor, args.tag_suffix))
        return 0
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
