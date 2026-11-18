#!/usr/bin/env python3
"""Summarise Unity NUnit XML and fail when tests did not actually pass.

Unity Test Runner writes NUnit 3 XML. This script is used after the GameCI test
step so a green container does not hide:
  * failed or errored test cases
  * skipped/inconclusive tests in a mandatory suite
  * empty test discovery (for example a broken asmdef)
  * results from the wrong test assembly
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

PASSED = {"passed", "success"}
FAILED = {"failed", "error", "cancelled"}
SKIPPED = {"skipped", "inconclusive", "ignored", "notrunnable"}


@dataclass
class Case:
    name: str
    fullname: str
    result: str
    duration: float = 0.0
    message: str = ""
    stack_trace: str = ""
    source: str = ""
    case_id: str = ""


@dataclass
class Summary:
    label: str
    results_dir: str
    files: list[str] = field(default_factory=list)
    cases: list[Case] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    min_tests: int = 1
    require_namespace: str = ""
    allow_skipped: bool = False

    @property
    def passed(self) -> list[Case]:
        return [c for c in self.cases if c.result in PASSED]

    @property
    def failed(self) -> list[Case]:
        return [c for c in self.cases if c.result in FAILED]

    @property
    def skipped(self) -> list[Case]:
        return [c for c in self.cases if c.result in SKIPPED]

    @property
    def other(self) -> list[Case]:
        return [c for c in self.cases if c.result not in PASSED | FAILED | SKIPPED]

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def duration(self) -> float:
        return sum(c.duration for c in self.cases)

    @property
    def namespace_ok(self) -> bool:
        if not self.require_namespace:
            return True
        return any(c.fullname.startswith(self.require_namespace + ".") or c.fullname == self.require_namespace
                   for c in self.cases)

    @property
    def ok(self) -> bool:
        return (
            not self.parse_errors
            and self.total >= self.min_tests
            and not self.failed
            and not self.other
            and self.namespace_ok
            and (self.allow_skipped or not self.skipped)
        )

    def problems(self) -> list[str]:
        problems: list[str] = []
        if self.parse_errors:
            problems.append("Could not parse all result files: " + "; ".join(self.parse_errors))
        if self.total < self.min_tests:
            problems.append(f"Only {self.total} test(s) discovered; at least {self.min_tests} are required.")
        if self.failed:
            problems.append(f"{len(self.failed)} test(s) failed.")
        if self.other:
            problems.append(f"{len(self.other)} test(s) had an unknown result.")
        if self.skipped and not self.allow_skipped:
            problems.append(f"{len(self.skipped)} test(s) were skipped or inconclusive; mandatory suites may not skip.")
        if not self.namespace_ok:
            problems.append(f"No test from namespace {self.require_namespace!r} was discovered.")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "resultsDir": self.results_dir,
            "files": self.files,
            "total": self.total,
            "passed": len(self.passed),
            "failed": len(self.failed),
            "skipped": len(self.skipped),
            "other": len(self.other),
            "durationSeconds": round(self.duration, 3),
            "ok": self.ok,
            "problems": self.problems(),
            "minTests": self.min_tests,
            "requireNamespace": self.require_namespace,
            "allowSkipped": self.allow_skipped,
            "parseErrors": self.parse_errors,
            "failures": [
                {
                    "fullname": c.fullname,
                    "name": c.name,
                    "result": c.result,
                    "message": c.message,
                    "stackTrace": c.stack_trace,
                    "source": c.source,
                }
                for c in self.failed
            ],
            "skippedTests": [
                {"fullname": c.fullname, "name": c.name, "result": c.result, "message": c.message, "source": c.source}
                for c in self.skipped
            ],
            "otherTests": [
                {"fullname": c.fullname, "name": c.name, "result": c.result, "source": c.source}
                for c in self.other
            ],
        }

    def markdown(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        lines = [
            f"### {self.label} tests: {status}",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Discovered | {self.total} |",
            f"| Passed | {len(self.passed)} |",
            f"| Failed | {len(self.failed)} |",
            f"| Skipped/inconclusive | {len(self.skipped)} |",
            f"| Duration | {self.duration:.2f} s |",
            f"| Minimum required | {self.min_tests} |",
        ]
        if self.require_namespace:
            lines.append(f"| Required namespace | `{self.require_namespace}` |")
        if self.parse_errors:
            lines.extend(["", "**Result files that could not be parsed**", ""])
            lines.extend(f"- {error}" for error in self.parse_errors)
        if self.failed:
            lines.extend(["", "**Failed tests**", ""])
            for case in self.failed:
                message = (case.message or "").strip().splitlines()
                first = message[0] if message else "no message"
                lines.append(f"- `{case.fullname}` — {first}")
        if self.skipped:
            lines.extend(["", "**Skipped or inconclusive tests**", ""])
            for case in self.skipped:
                lines.append(f"- `{case.fullname}` ({case.result})")
        if self.other:
            lines.extend(["", "**Unknown results**", ""])
            for case in self.other:
                lines.append(f"- `{case.fullname}` ({case.result})")
        problems = self.problems()
        if problems:
            lines.extend(["", "**Why this failed**", ""])
            lines.extend(f"- {problem}" for problem in problems)
        return "\n".join(lines)


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _duration(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def parse_file(path: Path) -> tuple[list[Case], str | None]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [], f"{path}: {exc}"
    except OSError as exc:
        return [], f"{path}: {exc}"
    cases: list[Case] = []
    for element in root.iter("test-case"):
        result = str(element.get("result") or "").strip().lower()
        failure = element.find("failure")
        reason = element.find("reason")
        cases.append(Case(
            name=str(element.get("name") or ""),
            fullname=str(element.get("fullname") or element.get("name") or ""),
            result=result,
            duration=_duration(element.get("duration")),
            message=_text(failure.find("message")) if failure is not None else _text(reason.find("message") if reason is not None else None),
            stack_trace=_text(failure.find("stack-trace")) if failure is not None else "",
            source=str(path),
            case_id=str(element.get("id") or ""),
        ))
    return cases, None


def find_xml(results_dir: Path) -> list[Path]:
    if not results_dir.exists():
        return []
    return sorted(p for p in results_dir.rglob("*.xml") if p.is_file())


def collect(results_dir: Path, label: str, min_tests: int = 1, require_namespace: str = "",
            allow_skipped: bool = False) -> Summary:
    summary = Summary(label=label, results_dir=str(results_dir), min_tests=min_tests,
                      require_namespace=require_namespace, allow_skipped=allow_skipped)
    files = find_xml(results_dir)
    if not files:
        summary.parse_errors.append(f"No XML result files found under {results_dir}")
        return summary
    seen: set[str] = set()
    for path in files:
        summary.files.append(str(path))
        cases, error = parse_file(path)
        if error:
            summary.parse_errors.append(error)
            continue
        for case in cases:
            key = case.case_id or (case.fullname + "|" + case.name)
            if key in seen:
                continue
            seen.add(key)
            summary.cases.append(case)
    return summary


def write_text(path: str | None, text: str) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--label", default="Unity")
    parser.add_argument("--min-tests", type=int, default=1)
    parser.add_argument("--require-namespace", default="")
    parser.add_argument("--allow-skipped", action="store_true")
    parser.add_argument("--out-json")
    parser.add_argument("--out-markdown")
    parser.add_argument("--github-summary", default=None)
    args = parser.parse_args(argv)

    summary = collect(Path(args.results_dir), args.label, args.min_tests, args.require_namespace, args.allow_skipped)
    payload = summary.to_dict()
    text = json.dumps(payload, indent=2)
    print(text)
    write_text(args.out_json, text)
    markdown = summary.markdown()
    write_text(args.out_markdown, markdown)

    summary_path = args.github_summary
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")

    if not summary.ok:
        for problem in summary.problems():
            print("error: " + problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
