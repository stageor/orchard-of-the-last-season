#!/usr/bin/env python3
"""Verify that a Unity player build is real, complete and matches the repository.

This runs immediately after GameCI builds and before artifacts are uploaded or a
release is published. It checks file signatures, the generated BUILD_INFO.txt,
the exact Unity version, the commit and the project-wide WebGL rule that
compression must be Disabled.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .unity_version import read_version
except ImportError:  # direct execution
    from unity_version import read_version  # type: ignore

WASM_MAGIC = b"\x00asm"
EXE_MAGIC = b"MZ"
COMPRESSED_SUFFIXES = (".gz", ".br", ".unityweb", ".zip")


@dataclass
class BuildCheck:
    target: str
    root: str
    info: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    total_size: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "root": self.root,
            "ok": self.ok,
            "unityVersion": self.info.get("unityVersion", ""),
            "buildTarget": self.info.get("target", ""),
            "commit": self.info.get("commit", ""),
            "compression": self.info.get("webglCompression", ""),
            "totalSize": self.total_size,
            "files": self.files,
            "problems": self.problems,
            "warnings": self.warnings,
        }

    def markdown(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        lines = [
            f"### {self.target} build: {status}",
            "",
            "| Field | Value |",
            "| --- | --- |",
            f"| Unity | `{self.info.get('unityVersion', 'unknown')}` |",
            f"| Build target | `{self.info.get('target', 'unknown')}` |",
            f"| Commit | `{self.info.get('commit', 'unknown')}` |",
            f"| Size | {self.total_size / (1024 * 1024):.1f} MiB |",
        ]
        if self.target == "webgl":
            lines.append(f"| Compression | `{self.info.get('webglCompression', 'unknown')}` |")
        if self.problems:
            lines.extend(["", "**Problems**", ""])
            lines.extend(f"- {problem}" for problem in self.problems)
        if self.warnings:
            lines.extend(["", "**Warnings**", ""])
            lines.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(lines)


def parse_build_info(path: Path) -> tuple[dict[str, str], list[str]]:
    info: dict[str, str] = {}
    problems: list[str] = []
    if not path.is_file():
        return info, [f"Missing {path}"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return info, [f"Could not read {path}: {exc}"]
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            problems.append(f"Malformed BUILD_INFO line: {line!r}")
            continue
        key, value = line.split("=", 1)
        info[key.strip()] = value.strip()
    return info, problems


def _first_bytes(path: Path, count: int) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(count)
    except OSError:
        return b""


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _total_size(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += _size(path)
    return total


def _collect_files(root: Path, check: BuildCheck) -> None:
    if not root.is_dir():
        check.problems.append(f"Build directory does not exist: {root}")
        return
    for path in sorted(root.rglob("*")):
        if path.is_file():
            check.files.append(str(path.relative_to(root)))
    check.total_size = _total_size(root)


def _check_common(check: BuildCheck, root: Path, project_root: Path, expected_commit: str) -> None:
    info, info_problems = parse_build_info(root / "BUILD_INFO.txt")
    check.info = info
    check.problems.extend(info_problems)
    if not info:
        return

    for key in ("product", "version", "unityVersion", "target", "commit", "totalErrors", "sizeBytes"):
        if key not in info:
            check.problems.append(f"BUILD_INFO.txt is missing {key}")

    try:
        project_version = read_version(project_root)
    except (OSError, ValueError) as exc:
        check.problems.append(f"Could not read the project Unity version: {exc}")
        project_version = ""

    if project_version and info.get("unityVersion") != project_version:
        check.problems.append(
            f"Build used Unity {info.get('unityVersion')!r}, but ProjectVersion.txt says {project_version!r}."
        )
    if info.get("totalErrors") not in (None, "0"):
        check.problems.append(f"BUILD_INFO reports totalErrors={info.get('totalErrors')}.")
    try:
        reported_size = int(info.get("sizeBytes") or 0)
    except ValueError:
        reported_size = 0
        check.problems.append("BUILD_INFO sizeBytes is not an integer.")
    if reported_size <= 0:
        check.problems.append("BUILD_INFO sizeBytes must be positive.")
    if expected_commit and info.get("commit") != expected_commit:
        check.problems.append(
            f"Build commit {info.get('commit')!r} does not match the expected commit {expected_commit!r}."
        )
    if info.get("commit") in (None, "", "local"):
        check.warnings.append("Build does not record a CI commit.")


def check_windows(root: Path, project_root: Path, expected_commit: str, min_size: int) -> BuildCheck:
    check = BuildCheck("windows", str(root))
    _collect_files(root, check)
    if not root.is_dir():
        return check
    _check_common(check, root, project_root, expected_commit)

    exe = root / "OrchardOfTheLastSeason.exe"
    if not exe.is_file():
        check.problems.append("Missing OrchardOfTheLastSeason.exe")
    else:
        if _first_bytes(exe, 2) != EXE_MAGIC:
            check.problems.append("OrchardOfTheLastSeason.exe is not a PE executable (missing MZ header).")
        if _size(exe) == 0:
            check.problems.append("OrchardOfTheLastSeason.exe is empty.")

    data_dir = root / "OrchardOfTheLastSeason_Data"
    if not data_dir.is_dir():
        check.problems.append("Missing OrchardOfTheLastSeason_Data directory.")
    else:
        if not (data_dir / "globalgamemanagers").is_file():
            check.problems.append("Missing OrchardOfTheLastSeason_Data/globalgamemanagers.")
        if not any((data_dir / name).is_file() for name in ("level0", "data.unity3d")):
            check.problems.append("Missing the first Unity scene data (level0 or data.unity3d).")

    if not (root / "UnityPlayer.dll").is_file():
        check.problems.append("Missing UnityPlayer.dll.")

    if check.info:
        target = check.info.get("target", "")
        if "StandaloneWindows64" not in target:
            check.problems.append(f"BUILD_INFO target is {target!r}, expected StandaloneWindows64.")
    if check.total_size < min_size:
        check.problems.append(f"Build is only {check.total_size} bytes; expected at least {min_size}.")
    return check


def check_webgl(root: Path, project_root: Path, expected_commit: str, min_size: int) -> BuildCheck:
    check = BuildCheck("webgl", str(root))
    _collect_files(root, check)
    if not root.is_dir():
        return check
    _check_common(check, root, project_root, expected_commit)

    index = root / "index.html"
    if not index.is_file():
        check.problems.append("Missing index.html.")
    else:
        text = index.read_text(encoding="utf-8", errors="replace")
        if "createUnityInstance" not in text and "unityInstance" not in text:
            check.problems.append("index.html does not look like a Unity WebGL loader.")
        if "Build/" not in text:
            check.problems.append("index.html does not reference the Build/ loader directory.")

    build_dir = root / "Build"
    if not build_dir.is_dir():
        check.problems.append("Missing Build/ directory.")
    else:
        wasm = sorted(build_dir.glob("*.wasm"))
        data = sorted(build_dir.glob("*.data"))
        if not wasm:
            check.problems.append("Missing WebGL .wasm payload.")
        for path in wasm:
            if _first_bytes(path, 4) != WASM_MAGIC:
                check.problems.append(f"{path.name} is not a WebAssembly binary.")
        if not data:
            check.problems.append("Missing WebGL .data payload.")
        if not any(build_dir.glob("*.framework.js")):
            check.warnings.append("No .framework.js loader was found; check the Unity version's output layout.")

    compressed = [p for p in root.rglob("*") if p.is_file() and p.name.lower().endswith(COMPRESSED_SUFFIXES)]
    if compressed:
        names = ", ".join(str(p.relative_to(root)) for p in compressed[:10])
        check.problems.append(f"Compressed or packaged WebGL artifacts are not allowed: {names}")

    compression = check.info.get("webglCompression", "")
    if compression and compression != "Disabled":
        check.problems.append(f"BUILD_INFO webglCompression is {compression!r}, expected Disabled.")
    if not compression and check.info:
        check.problems.append("BUILD_INFO is missing webglCompression.")

    if check.info:
        target = check.info.get("target", "")
        if "WebGL" not in target:
            check.problems.append(f"BUILD_INFO target is {target!r}, expected WebGL.")
    if check.total_size < min_size:
        check.problems.append(f"Build is only {check.total_size} bytes; expected at least {min_size}.")
    return check


def verify(target: str, root: Path, project_root: Path, expected_commit: str = "", min_size: int | None = None) -> BuildCheck:
    if target == "windows":
        return check_windows(root, project_root, expected_commit, min_size if min_size is not None else 1_000_000)
    if target == "webgl":
        return check_webgl(root, project_root, expected_commit, min_size if min_size is not None else 1_000_000)
    raise ValueError(f"unknown build target: {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=("windows", "webgl"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--expected-commit", default="")
    parser.add_argument("--min-size", type=int)
    parser.add_argument("--out-json")
    parser.add_argument("--github-summary", default=None)
    args = parser.parse_args(argv)

    check = verify(args.target, Path(args.root), Path(args.project_root), args.expected_commit, args.min_size)
    payload = check.to_dict()
    text = json.dumps(payload, indent=2)
    print(text)
    if args.out_json:
        path = Path(args.out_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    markdown = check.markdown()
    if args.github_summary:
        with open(args.github_summary, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if not check.ok:
        for problem in check.problems:
            print("error: " + problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
