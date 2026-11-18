#!/usr/bin/env python3
"""Aggregate the mandatory CI jobs into one consistently named check.

The caller job is named ``Required checks``. This script fails closed when a
mandatory job failed, was cancelled, or was skipped for any reason other than an
intentional documentation-only PR. A documentation-only PR may skip the licensed
Unity test and build jobs, but never repository health or C# analysis.

Skipped Unity jobs on a non-docs fork PR are a failure with instructions: fork
PRs do not receive repository secrets, so a maintainer must copy the commits to a
same-repository branch for real validation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

REQUIRED_JOBS = (
    "changes",
    "repository-health",
    "csharp-analysis",
    "unity-editmode",
    "unity-playmode",
    "build-windows",
    "build-webgl",
)
UNITY_JOBS = {
    "unity-editmode",
    "unity-playmode",
    "build-windows",
    "build-webgl",
}
SUCCESS = "success"


@dataclass
class JobResult:
    job: str
    result: str
    allowed_skip: bool = False
    reason: str = ""


@dataclass
class Gate:
    docs_only: bool = False
    fork: bool = False
    jobs: dict[str, JobResult] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "docsOnly": self.docs_only,
            "fork": self.fork,
            "requiredJobs": list(REQUIRED_JOBS),
            "jobs": {
                job: {
                    "result": item.result,
                    "allowedSkip": item.allowed_skip,
                    "reason": item.reason,
                }
                for job, item in self.jobs.items()
            },
            "problems": self.problems,
            "warnings": self.warnings,
        }

    def markdown(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        lines = [
            f"### Required checks: {status}",
            "",
            f"Documentation-only PR: {'yes' if self.docs_only else 'no'}",
            f"Fork PR: {'yes' if self.fork else 'no'}",
            "",
            "| Required job | Result | Outcome |",
            "| --- | --- | --- |",
        ]
        for job in REQUIRED_JOBS:
            item = self.jobs.get(job)
            if item is None:
                lines.append(f"| `{job}` | missing | BLOCKED |")
            elif item.result == SUCCESS:
                lines.append(f"| `{job}` | success | PASS |")
            elif item.allowed_skip:
                lines.append(f"| `{job}` | skipped | ALLOWED (docs-only) |")
            else:
                lines.append(f"| `{job}` | {item.result or 'unknown'} | BLOCKED |")
        if self.problems:
            lines.extend(["", "**Blocking reasons**", ""])
            lines.extend(f"- {problem}" for problem in self.problems)
        if self.warnings:
            lines.extend(["", "**Warnings**", ""])
            lines.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(lines)


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_needs(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"needs JSON is not valid: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("needs JSON must be an object")
    return data


def evaluate(needs: dict[str, Any], docs_only: bool, fork: bool) -> Gate:
    gate = Gate(docs_only=docs_only, fork=fork)

    for job in REQUIRED_JOBS:
        item = needs.get(job)
        if not isinstance(item, dict):
            gate.problems.append(f"Required job `{job}` is missing from the dependency graph.")
            continue
        result = str(item.get("result") or "").lower()
        job_result = JobResult(job, result)
        if result == SUCCESS:
            job_result.reason = "passed"
        elif result == "skipped" and job in UNITY_JOBS and docs_only:
            job_result.allowed_skip = True
            job_result.reason = "documentation-only PR"
        elif result == "skipped" and job in UNITY_JOBS and fork:
            job_result.reason = "fork PR cannot receive Unity license secrets"
        elif result == "skipped":
            job_result.reason = "unexpected skip"
        else:
            job_result.reason = f"job {result or 'unknown'}"
        gate.jobs[job] = job_result

    for job in REQUIRED_JOBS:
        item = gate.jobs.get(job)
        if item is None:
            continue
        if item.result == SUCCESS or item.allowed_skip:
            continue
        if job in UNITY_JOBS and item.result == "skipped" and fork and not docs_only:
            gate.problems.append(
                f"`{job}` did not run because this is a fork PR and repository secrets are not available. "
                "A maintainer must copy the commits to a same-repository branch, open a validation PR, "
                "and keep the original PR open for the three approvals."
            )
            continue
        gate.problems.append(f"Required job `{job}` did not succeed (result: {item.result or 'unknown'}).")

    changes = needs.get("changes")
    if isinstance(changes, dict):
        outputs = changes.get("outputs") or {}
        output_docs = parse_bool(outputs.get("docs_only"), docs_only)
        output_fork = parse_bool(outputs.get("fork"), fork)
        if output_docs != docs_only:
            gate.warnings.append(
                f"Caller passed docs_only={docs_only}, but the changes job reported {output_docs}."
            )
        if output_fork != fork:
            gate.warnings.append(
                f"Caller passed fork={fork}, but the changes job reported {output_fork}."
            )

    if docs_only:
        gate.warnings.append(
            "Unity EditMode, PlayMode and build jobs were intentionally skipped because this PR only changes documentation."
        )
    if fork and not docs_only:
        gate.warnings.append(
            "Fork PRs require all three approvals and a same-repository validation branch before merging."
        )

    return gate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--needs-json", default=os.environ.get("NEEDS_JSON"))
    parser.add_argument("--needs-file")
    parser.add_argument("--docs-only", default="false")
    parser.add_argument("--fork", default="false")
    parser.add_argument("--out-json")
    parser.add_argument("--github-summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = parser.parse_args(argv)

    raw = args.needs_json
    if args.needs_file:
        try:
            raw = open(args.needs_file, encoding="utf-8").read()
        except OSError as exc:
            print(f"error: cannot read needs file: {exc}", file=sys.stderr)
            return 2
    if not raw:
        print("error: --needs-json, --needs-file or NEEDS_JSON is required", file=sys.stderr)
        return 2
    try:
        needs = parse_needs(raw)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    gate = evaluate(needs, parse_bool(args.docs_only), parse_bool(args.fork))
    payload = gate.to_dict()
    text = json.dumps(payload, indent=2)
    print(text)
    if args.out_json:
        path = args.out_json
        try:
            from pathlib import Path
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot write {path}: {exc}", file=sys.stderr)
            return 2
    markdown = gate.markdown()
    if args.github_summary:
        try:
            with open(args.github_summary, "a", encoding="utf-8") as handle:
                handle.write(markdown + "\n")
        except OSError as exc:
            print(f"warning: cannot append GitHub summary: {exc}", file=sys.stderr)
    if not gate.ok:
        for problem in gate.problems:
            print("error: " + problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
