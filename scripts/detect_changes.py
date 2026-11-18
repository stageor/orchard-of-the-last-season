#!/usr/bin/env python3
"""Classify a pull request as documentation-only or as a change that needs Unity validation.

This is deliberately an allow-list. Only Markdown, docs/ images and issue/PR templates may
skip Unity. Anything else -- including a new file with an unusual extension, ProjectSettings,
Packages, Assets, workflows or scripts -- forces the full Unity path. This prevents a path
filter from silently bypassing EditMode, PlayMode or build validation.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path

DOC_PATTERNS = (
    "*.md",
    "docs/**",
    "LICENSE",
    "LICENSE.*",
    "NOTICE",
    "NOTICE.*",
    ".github/ISSUE_TEMPLATE/**",
    ".github/pull_request_template.md",
)

PROTECTED_PATTERNS = (
    ".github/**",
    "scripts/**",
    "tests/ci/**",
    "Assets/Orchard/Editor/**",
    "Assets/Orchard/Tests/**",
    "ProjectSettings/**",
    "Packages/**",
)


def matches(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    for pattern in patterns:
        if fnmatch.fnmatch(normalized, pattern):
            return True
        # fnmatch's ** is not recursive; docs/** should match every depth.
        if pattern.endswith("/**") and normalized.startswith(pattern[:-2] + "/"):
            return True
    return False


def git_changed_files(base: str, head: str, repo: str | Path = ".") -> list[str]:
    # Include deletions: deleting a workflow or a test must not look like a docs-only change.
    cmd = ["git", "-C", str(repo), "diff", "--name-only", "--diff-filter=ACDMRTUXB", base, head]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git diff failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def classify(files: list[str]) -> dict:
    docs_only = bool(files) and all(matches(f, DOC_PATTERNS) for f in files)
    protected = sorted(f for f in files if matches(f, PROTECTED_PATTERNS))
    return {
        "files": files,
        "docs_only": docs_only,
        "unity": not docs_only,
        "build": not docs_only,
        "protected": bool(protected),
        "protected_files": protected,
    }


def write_outputs(result: dict, output_path: str | None = None) -> None:
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as fh:
        for key in ("docs_only", "unity", "build", "protected"):
            fh.write(f"{key}={'true' if result[key] else 'false'}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("GITHUB_BASE_SHA"))
    parser.add_argument("--head", default=os.environ.get("GITHUB_HEAD_SHA", "HEAD"))
    parser.add_argument("--repo", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    args = parser.parse_args(argv)

    if not args.base:
        print("error: --base or GITHUB_BASE_SHA is required", file=sys.stderr)
        return 2

    try:
        files = git_changed_files(args.base, args.head, args.repo)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = classify(files)
    write_outputs(result, args.github_output)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("docs_only=" + str(result["docs_only"]).lower())
        print("unity=" + str(result["unity"]).lower())
        print("protected=" + str(result["protected"]).lower())
        for f in files:
            print("changed: " + f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
