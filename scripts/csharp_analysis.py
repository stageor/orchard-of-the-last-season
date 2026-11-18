#!/usr/bin/env python3
"""Repository-specific C# contract analysis for the Orchard Unity project.

This is deliberately not a general C# compiler. Unity compiles the project for
real inside the EditMode and PlayMode jobs. This job catches the rules that a
compiler cannot: the project namespace, editor-only boundaries, forbidden input
APIs, runtime asset loading, and the self-bootstrapping entry point.

Pre-existing gameplay deviations are recorded in ``.github/csharp-baseline.json``
with a reason. New violations fail CI; fixing one makes its baseline entry stale,
which is reported so the suppression can be removed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

DEFAULT_BASELINE = ".github/csharp-baseline.json"

ALLOWED_KEYS = {
    "W", "A", "S", "D",
    "UpArrow", "DownArrow", "LeftArrow", "RightArrow",
    "I", "J", "K", "L",
    "Space", "Z",
    "LeftShift", "RightShift", "X",
    "C", "V",
    "Return", "Tab", "Q", "E", "T", "P",
    "None",
}
ALLOWED_INPUT_MEMBERS = {"GetKey", "GetKeyDown", "GetKeyUp"}
FORBIDDEN_INPUT_MEMBERS = {
    "GetMouseButton", "GetMouseButtonDown", "GetMouseButtonUp", "mousePosition",
    "mouseScrollDelta", "GetAxis", "GetAxisRaw", "GetButton", "GetButtonDown",
    "GetButtonUp", "touchCount", "GetTouch", "acceleration", "gyro", "anyKey",
    "anyKeyDown", "inputString", "joystickNames",
}
KEY_RE = re.compile(r"\bKeyCode\.([A-Za-z0-9_]+)\b")
INPUT_RE = re.compile(r"\bInput\.([A-Za-z0-9_]+)\b")
NAMESPACE_RE = re.compile(r"\bnamespace\s+([A-Za-z_][A-Za-z0-9_.]*)")
MOUSE_RE = re.compile(r"\bEventType\.(MouseDown|MouseUp|MouseDrag|ScrollWheel)\b|\.mousePosition\b")


@dataclass
class Violation:
    rule: str
    severity: str
    file: str
    line: int
    message: str
    snippet: str

    def fingerprint(self) -> str:
        return f"{self.rule}|{self.file}|{self.snippet.strip()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "snippet": self.snippet,
        }


@dataclass
class Analysis:
    violations: list[Violation] = field(default_factory=list)
    suppressed: list[Violation] = field(default_factory=list)
    stale_baseline: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files: int = 0

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def warnings_list(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "files": self.files,
            "errors": [v.to_dict() for v in self.errors],
            "warnings": [v.to_dict() for v in self.warnings_list],
            "suppressed": [v.to_dict() for v in self.suppressed],
            "staleBaseline": self.stale_baseline,
            "notes": self.warnings,
        }

    def markdown(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        lines = [
            f"### C# contract analysis: {status}",
            "",
            f"Analyzed {self.files} C# file(s).",
            f"Errors: {len(self.errors)} · Warnings: {len(self.warnings_list)} · "
            f"Known suppressions used: {len(self.suppressed)}",
        ]
        if self.errors:
            lines.extend(["", "**New errors**", ""])
            for v in self.errors:
                lines.append(f"- `{v.file}:{v.line}` [{v.rule}] {v.message}")
        if self.warnings_list:
            lines.extend(["", "**Warnings**", ""])
            for v in self.warnings_list[:25]:
                lines.append(f"- `{v.file}:{v.line}` [{v.rule}] {v.message}")
            if len(self.warnings_list) > 25:
                lines.append(f"- ...and {len(self.warnings_list) - 25} more")
        if self.stale_baseline:
            lines.extend(["", "**Stale baseline entries (remove these suppressions)**", ""])
            for entry in self.stale_baseline[:25]:
                lines.append(f"- `{entry.get('file')}` [{entry.get('rule')}] {entry.get('note', '')}")
        if self.warnings:
            lines.extend(["", "**Notes**", ""])
            lines.extend(f"- {note}" for note in self.warnings)
        return "\n".join(lines)


def strip_comments_and_strings(text: str) -> list[str]:
    """Remove comments and literals while preserving line numbers.

    The result is intentionally not a parser; it is enough to stop policy checks
    matching text inside comments or user-facing strings.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    line = 0
    state = "code"
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                state = "line_comment"
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block_comment"
                i += 2
                continue
            if ch == '"':
                state = "string"
                out.append(" ")
                i += 1
                continue
            if ch == "'":
                state = "char"
                out.append(" ")
                i += 1
                continue
            out.append(ch)
            if ch == "\n":
                line += 1
            i += 1
            continue
        if state == "line_comment":
            if ch == "\n":
                state = "code"
                out.append("\n")
                line += 1
            i += 1
            continue
        if state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 2
                continue
            if ch == "\n":
                out.append("\n")
                line += 1
            i += 1
            continue
        if state == "string":
            if ch == "\\" and nxt:
                i += 2
                continue
            if ch == '"':
                state = "code"
            if ch == "\n":
                out.append("\n")
                line += 1
            i += 1
            continue
        if state == "char":
            if ch == "\\" and nxt:
                i += 2
                continue
            if ch == "'":
                state = "code"
            if ch == "\n":
                out.append("\n")
                line += 1
            i += 1
            continue
    return "".join(out).split("\n")


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def _namespace_for(rel: str) -> str:
    if rel.startswith("Assets/Orchard/Scripts/"):
        return "Orchard"
    if rel.startswith("Assets/Orchard/Editor/"):
        return "Orchard"
    if rel.startswith("Assets/Orchard/Tests/"):
        return "Orchard.Tests"
    return "Orchard"


def _braces_balanced(lines: Iterable[str]) -> tuple[bool, str]:
    pairs = {"{": "}", "(": ")", "[": "]"}
    closing = {v: k for k, v in pairs.items()}
    stack: list[tuple[str, int]] = []
    for number, line in enumerate(lines, start=1):
        for ch in line:
            if ch in pairs:
                stack.append((ch, number))
            elif ch in closing:
                if not stack or stack[-1][0] != closing[ch]:
                    return False, f"unmatched {ch!r} on line {number}"
                stack.pop()
    if stack:
        ch, number = stack[-1]
        return False, f"unclosed {ch!r} from line {number}"
    return True, ""


def analyze_file(path: Path, root: Path) -> list[Violation]:
    rel = _rel(path, root)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return [Violation("file.read", "error", rel, 0, f"could not read file: {exc}", "")]
    stripped_lines = strip_comments_and_strings(text)
    original_lines = text.splitlines()
    violations: list[Violation] = []

    for number, line in enumerate(stripped_lines, start=1):
        snippet = line.strip()
        if not snippet:
            continue
        # Whitespace and length checks belong to the real source line. The stripped
        # line deliberately leaves spaces where a literal or comment was removed,
        # so using it would report a false trailing-whitespace warning on every
        # line that ends with a string or a comment.
        original = original_lines[number - 1] if number <= len(original_lines) else line
        if "\t" in line:
            violations.append(Violation("style.tab", "warning", rel, number, "tab indentation", original.strip()))
        if original.rstrip() != original:
            violations.append(Violation("style.trailing_whitespace", "warning", rel, number, "trailing whitespace", original.strip()))
        if len(original) > 240:
            violations.append(Violation("style.long_line", "warning", rel, number, "line longer than 240 characters", original.strip()))

        for match in KEY_RE.finditer(line):
            key = match.group(1)
            if key not in ALLOWED_KEYS:
                violations.append(Violation(
                    "input.key", "error", rel, number,
                    f"keyboard key KeyCode.{key} is not in the allowed keyboard-only set",
                    snippet,
                ))
        for match in INPUT_RE.finditer(line):
            member = match.group(1)
            if member in FORBIDDEN_INPUT_MEMBERS:
                violations.append(Violation(
                    "input.forbidden", "error", rel, number,
                    f"Input.{member} is forbidden by the keyboard-only contract",
                    snippet,
                ))
            elif member not in ALLOWED_INPUT_MEMBERS:
                violations.append(Violation(
                    "input.unknown", "error", rel, number,
                    f"Input.{member} is not in the reviewed input allow-list",
                    snippet,
                ))
        if MOUSE_RE.search(line):
            violations.append(Violation(
                "input.mouse_event", "error", rel, number,
                "mouse GUI input is forbidden by the keyboard-only contract",
                snippet,
            ))
        if "Resources.Load" in line:
            violations.append(Violation(
                "external_asset.resources_load", "error", rel, number,
                "Resources.Load bypasses the runtime-generated-visual contract",
                snippet,
            ))
        if re.search(r"\bDllImport\b", line):
            violations.append(Violation(
                "platform.dllimport", "error", rel, number,
                "native imports are not portable to WebGL and are not allowed",
                snippet,
            ))
        if re.search(r"\b(AssetDatabase|UnityEditor)\b", line) and not rel.startswith("Assets/Orchard/Editor/"):
            violations.append(Violation(
                "editor.leak", "error", rel, number,
                "UnityEditor API used outside Assets/Orchard/Editor",
                snippet,
            ))
        if re.search(r"\b(System\.Threading|Task<|\basync\s+|\bawait\s+)", line):
            violations.append(Violation(
                "runtime.threading", "warning", rel, number,
                "threading/async may not be safe in the Unity player loop",
                snippet,
            ))

    code = "\n".join(stripped_lines)
    names = NAMESPACE_RE.findall(code)
    expected = _namespace_for(rel)
    if not names:
        violations.append(Violation("namespace.missing", "error", rel, 0, "no namespace declaration", ""))
    elif rel.startswith("Assets/Orchard/Scripts/") and not all(n == "Orchard" for n in names):
        violations.append(Violation(
            "namespace.contract", "error", rel, 0,
            f"runtime namespace must be Orchard, found {', '.join(names)}",
            "",
        ))
    elif rel.startswith("Assets/Orchard/Editor/") and not all(
        n in {"Orchard", "Orchard.CI", "Orchard.Editor"} for n in names
    ):
        violations.append(Violation(
            "namespace.contract", "error", rel, 0,
            f"editor namespace must be Orchard, Orchard.CI or Orchard.Editor, found {', '.join(names)}",
            "",
        ))
    elif expected == "Orchard.Tests" and not all(n == "Orchard.Tests" or n.startswith("Orchard.Tests.") for n in names):
        violations.append(Violation(
            "namespace.contract", "error", rel, 0,
            f"test namespace must start with Orchard.Tests, found {', '.join(names)}",
            "",
        ))

    if rel.startswith("Assets/Orchard/Editor/"):
        if "#if UNITY_EDITOR" not in text or "#endif" not in text:
            violations.append(Violation(
                "editor.guard", "error", rel, 0,
                "editor scripts must be wrapped in #if UNITY_EDITOR / #endif",
                "",
            ))
        if "using UnityEditor" not in text:
            violations.append(Violation(
                "editor.import", "warning", rel, 0,
                "editor script does not import UnityEditor",
                "",
            ))

    balanced, problem = _braces_balanced(stripped_lines)
    if not balanced:
        violations.append(Violation("syntax.brackets", "error", rel, 0, f"bracket balance: {problem}", ""))

    return violations


def load_baseline(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read baseline {path}: {exc}") from exc
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"baseline {path} must contain an entries list")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("baseline entries must be objects")
        for key in ("rule", "file", "snippet"):
            if not entry.get(key):
                raise ValueError(f"baseline entry is missing {key}")
        fingerprint = f"{entry['rule']}|{entry['file']}|{str(entry['snippet']).strip()}"
        result[fingerprint] = entry
    return result


def analyze(root: Path, baseline: dict[str, dict[str, Any]] | None = None) -> Analysis:
    result = Analysis()
    baseline = baseline or {}
    used: set[str] = set()
    code_root = root / "Assets"
    files = sorted(p for p in code_root.rglob("*.cs") if p.is_file()) if code_root.is_dir() else []
    result.files = len(files)
    boot_found = False
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8-sig")
        except OSError:
            raw = ""
        if "RuntimeInitializeOnLoadMethod" in raw and "RuntimeInitializeLoadType.AfterSceneLoad" in raw:
            boot_found = True
        for violation in analyze_file(path, root):
            fingerprint = violation.fingerprint()
            if violation.severity == "error" and fingerprint in baseline:
                result.suppressed.append(violation)
                used.add(fingerprint)
            else:
                result.violations.append(violation)
    if not files:
        result.violations.append(Violation(
            "boot.no_csharp", "error", "Assets", 0,
            "no C# source files were found under Assets/", "",
        ))
    elif not boot_found:
        result.violations.append(Violation(
            "boot.missing", "error", "Assets", 0,
            "no [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)] bootstrap was found", "",
        ))
    for fingerprint, entry in baseline.items():
        if fingerprint not in used:
            result.stale_baseline.append(entry)
    result.warnings.append(
        "The project namespace is 'Orchard'; AGENTS.md's 'OrchardOfTheLastSeason' wording is not enforced "
        "because renaming production code would be a behaviour-changing refactor."
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors.")
    parser.add_argument("--out-json")
    parser.add_argument("--github-summary", default=None)
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    baseline_path = Path(args.baseline) if args.baseline else root / DEFAULT_BASELINE
    try:
        baseline = {} if args.no_baseline else load_baseline(baseline_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = analyze(root, baseline)
    if args.strict:
        for warning in result.warnings_list:
            warning.severity = "error"
    payload = result.to_dict()
    text = json.dumps(payload, indent=2)
    print(text)
    if args.out_json:
        path = Path(args.out_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    markdown = result.markdown()
    if args.github_summary:
        with open(args.github_summary, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if not result.ok:
        for violation in result.errors:
            print(f"error: {violation.file}:{violation.line} [{violation.rule}] {violation.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
