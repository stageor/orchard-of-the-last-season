#!/usr/bin/env python3
"""Validate the Orchard repository's CI, Unity and documentation invariants.

Run locally with ``python3 scripts/validate_repository.py`` and in the
``repository-health`` CI job. Errors block; warnings are printed and included in
the job summary.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

try:
    import yaml
except ImportError:  # pragma: no cover - the CI job installs PyYAML
    yaml = None

try:
    from .approval_policy import TeamConfigError, load_team
    from .ci_gate import REQUIRED_JOBS
except ImportError:  # direct execution
    from approval_policy import TeamConfigError, load_team  # type: ignore
    from ci_gate import REQUIRED_JOBS  # type: ignore

PIN_RE = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
UNITY_VERSION_RE = re.compile(r"\b\d{4}\.\d+\.\d+[abcfpx]\d+\b")
GUID_RE = re.compile(r"^guid:\s*([0-9a-f]{32})\s*$", re.MULTILINE)
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")
BINARY_SUFFIXES = {
    ".dll", ".exe", ".wasm", ".data", ".zip", ".7z", ".tar", ".gz", ".br",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".psd", ".tga", ".fbx", ".obj",
    ".wav", ".mp3", ".ogg", ".mp4", ".mov", ".apk", ".aab", ".unitypackage",
    ".ulf", ".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".env",
}
FORBIDDEN_TRACKED_DIRS = (
    "Library/", "Temp/", "Logs/", "obj/", "UserSettings/", ".vs/",
    "Build/", "build/", "artifacts/", "TestResults/",
)
REQUIRED_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "docs/CI_CD.md",
    "docs/APPROVAL_POLICY.md",
    "docs/TESTING.md",
    "docs/BUILD_AND_RELEASE.md",
    "docs/GITHUB_SETUP.md",
    ".github/CODEOWNERS",
    ".github/team.json",
    ".github/dependabot.yml",
    ".github/csharp-baseline.json",
    ".github/workflows/ci.yml",
    ".github/workflows/unity-tests.yml",
    ".github/workflows/unity-build.yml",
    ".github/workflows/review-gate.yml",
    ".github/workflows/release.yml",
    ".github/workflows/nightly-regression.yml",
    ".github/workflows/security.yml",
    ".gitattributes",
    ".gitignore",
    "Assets/Orchard/Scenes/Bootstrap.unity",
    "ProjectSettings/ProjectVersion.txt",
    "Packages/manifest.json",
    "Packages/packages-lock.json",
)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: int = 0

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": self.checks, "errors": self.errors, "warnings": self.warnings}

    def markdown(self) -> str:
        status = "PASS" if self.ok else "FAIL"
        lines = [
            f"### Repository health: {status}",
            "",
            f"Checks run: {self.checks} · Errors: {len(self.errors)} · Warnings: {len(self.warnings)}",
        ]
        if self.errors:
            lines.extend(["", "**Errors**", ""])
            lines.extend(f"- {error}" for error in self.errors)
        if self.warnings:
            lines.extend(["", "**Warnings**", ""])
            lines.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(lines)


class UniqueKeyLoader(yaml.SafeLoader if yaml else object):
    """SafeLoader that rejects duplicate mapping keys."""

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise ValueError(f"duplicate YAML key {key!r}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def read_json(report: Report, path: Path) -> Any:
    report.checks += 1
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        report.error(f"Missing JSON file: {path}")
    except json.JSONDecodeError as exc:
        report.error(f"Invalid JSON in {path}: {exc}")
    except OSError as exc:
        report.error(f"Could not read {path}: {exc}")
    return None


def read_yaml(report: Report, path: Path) -> Any:
    report.checks += 1
    if yaml is None:
        report.error("PyYAML is not installed; install scripts/requirements-ci.txt")
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        report.error(f"Could not read {path}: {exc}")
        return None
    try:
        return yaml.load(text, Loader=UniqueKeyLoader)
    except Exception as exc:
        report.error(f"Invalid YAML in {path}: {exc}")
        return None


def triggers(workflow: dict[str, Any]) -> Any:
    if not isinstance(workflow, dict):
        return None
    if "on" in workflow:
        return workflow["on"]
    # PyYAML 1.1 turns the unquoted key `on` into True.
    return workflow.get(True)


def trigger_names(workflow: dict[str, Any]) -> set[str]:
    raw = triggers(workflow)
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {str(x) for x in raw}
    if isinstance(raw, dict):
        return {str(x) for x in raw.keys()}
    return set()


def iter_steps(workflow: dict[str, Any]):
    jobs = workflow.get("jobs") if isinstance(workflow, dict) else {}
    if not isinstance(jobs, dict):
        return
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict):
                yield str(job_name), job, step


def check_workflows(report: Report, root: Path) -> dict[str, dict[str, Any]]:
    workflows: dict[str, dict[str, Any]] = {}
    folder = root / ".github" / "workflows"
    if not folder.is_dir():
        report.error("Missing .github/workflows directory")
        return workflows
    for path in sorted(list(folder.glob("*.yml")) + list(folder.glob("*.yaml"))):
        data = read_yaml(report, path)
        if not isinstance(data, dict):
            report.error(f"{path} is not a YAML mapping")
            continue
        name = path.name
        workflows[name] = data

        for job_name, job, step in iter_steps(data):
            uses = step.get("uses")
            if isinstance(uses, str) and not uses.startswith("./") and not uses.startswith("docker://"):
                if not PIN_RE.match(uses):
                    report.error(f"{name}:{job_name} action is not pinned to a full commit SHA: {uses}")
            if step.get("continue-on-error") is True and job_name in set(REQUIRED_JOBS) | {"required-checks"}:
                report.error(f"{name}:{job_name} may not use continue-on-error on a required job")

        top_permissions = data.get("permissions")
        if top_permissions == "write-all":
            report.error(f"{name}: top-level permissions must not be write-all")
        jobs = data.get("jobs") or {}
        if not isinstance(jobs, dict) or not jobs:
            report.error(f"{name}: no jobs defined")
            continue
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                continue
            report.checks += 1
            # jobs.<job_id>.timeout-minutes is not a supported keyword when the
            # job calls a reusable workflow. The called workflow's own jobs must
            # declare their timeouts instead.
            if "uses" not in job and "timeout-minutes" not in job:
                report.error(f"{name}:{job_name} has no timeout-minutes")
            if top_permissions is None and "permissions" not in job:
                report.error(f"{name}:{job_name} has no permissions block")
            if job.get("permissions") == "write-all":
                report.error(f"{name}:{job_name} permissions must not be write-all")

        text = path.read_text(encoding="utf-8")
        for match in UNITY_VERSION_RE.findall(text):
            report.error(f"{name}: hard-coded Unity version {match}; read ProjectVersion.txt via scripts/unity_version.py")

    return workflows


def check_ci_workflow(report: Report, workflows: dict[str, dict[str, Any]]) -> None:
    ci = workflows.get("ci.yml")
    if not ci:
        report.error("ci.yml is missing")
        return
    raw_triggers = triggers(ci)
    if isinstance(raw_triggers, dict):
        for event in ("pull_request", "push"):
            config = raw_triggers.get(event)
            if isinstance(config, dict) and ("paths" in config or "paths-ignore" in config):
                report.error(f"ci.yml:{event} must not use paths/paths-ignore; documentation skipping is decided inside the workflow")
    jobs = ci.get("jobs") or {}
    required = set(REQUIRED_JOBS)
    missing = required - set(jobs)
    if missing:
        report.error("ci.yml is missing required jobs: " + ", ".join(sorted(missing)))
    gate = jobs.get("required-checks")
    if not isinstance(gate, dict):
        report.error("ci.yml has no required-checks job")
        return
    if "Required checks" not in str(gate.get("name") or ""):
        report.error("ci.yml required-checks job must be named 'Required checks'")
    if "always()" not in str(gate.get("if") or ""):
        report.error("ci.yml required-checks job must run with if: always()")
    needs = set(gate.get("needs") or [])
    expected_needs = required - {"changes"}
    if not expected_needs.issubset(needs):
        report.error("ci.yml required-checks needs is missing: " + ", ".join(sorted(expected_needs - needs)))
    if not ci.get("concurrency"):
        report.error("ci.yml must define concurrency so superseded runs are cancelled")


def check_review_gate(report: Report, workflows: dict[str, dict[str, Any]]) -> None:
    gate = workflows.get("review-gate.yml")
    if not gate:
        report.error("review-gate.yml is missing")
        return
    names = trigger_names(gate)
    for event in ("pull_request_target", "pull_request_review", "issue_comment"):
        if event not in names:
            report.error(f"review-gate.yml must listen to {event}")
    found_script = False
    for job_name, job, step in iter_steps(gate):
        run = str(step.get("run") or "")
        if "check_approvals.py" in run:
            found_script = True
        if str(step.get("uses") or "").startswith("actions/checkout"):
            with_values = step.get("with") or {}
            ref = str(with_values.get("ref") or "")
            if "pull_request.head" in ref or "head.sha" in ref or "head.ref" in ref:
                report.error(f"review-gate.yml:{job_name} must never check out the pull request head")
            if with_values.get("persist-credentials") is not False:
                report.error(f"review-gate.yml:{job_name} checkout must set persist-credentials: false")
    if not found_script:
        report.error("review-gate.yml does not invoke scripts/check_approvals.py")


def check_reusable_workflows(report: Report, workflows: dict[str, dict[str, Any]]) -> None:
    for name in ("unity-tests.yml", "unity-build.yml"):
        workflow = workflows.get(name)
        if not workflow:
            report.error(f"{name} is missing")
            continue
        if "workflow_call" not in trigger_names(workflow):
            report.error(f"{name} must be reusable via workflow_call")


def check_security_and_nightly(report: Report, workflows: dict[str, dict[str, Any]]) -> None:
    security = workflows.get("security.yml") or {}
    text = json.dumps(security)
    for needle in ("dependency-review-action", "codeql-action", "gitleaks"):
        if needle not in text:
            report.error(f"security.yml does not configure {needle}")
    nightly = workflows.get("nightly-regression.yml") or {}
    if "schedule" not in trigger_names(nightly):
        report.error("nightly-regression.yml must have a schedule trigger")
    release = workflows.get("release.yml") or {}
    raw = triggers(release)
    push = raw.get("push") if isinstance(raw, dict) else None
    tags = push.get("tags") if isinstance(push, dict) else None
    if not tags or not any("v" in str(tag) for tag in (tags if isinstance(tags, list) else [tags])):
        report.error("release.yml must trigger on v* tags")


def check_assets(report: Report, root: Path) -> None:
    assets = root / "Assets"
    if not assets.is_dir():
        report.error("Assets directory is missing")
        return
    guids: dict[str, str] = {}
    for path in sorted(assets.rglob("*")):
        if path.name == ".DS_Store":
            report.error(f"Tracked .DS_Store file: {path}")
        if path.name.endswith(".meta"):
            meta = path
            asset = Path(str(meta)[:-5])
            report.checks += 1
            if not asset.exists():
                report.error(f"Orphaned .meta file: {meta.relative_to(root)}")
            try:
                text = meta.read_text(encoding="utf-8")
            except OSError as exc:
                report.error(f"Could not read {meta}: {exc}")
                continue
            match = GUID_RE.search(text)
            if not match:
                report.error(f"Meta file has no 32-hex GUID: {meta.relative_to(root)}")
                continue
            guid = match.group(1)
            if guid in guids:
                report.error(f"Duplicate GUID {guid} in {meta.relative_to(root)} and {guids[guid]}")
            else:
                guids[guid] = str(meta.relative_to(root))
            continue
        if not path.is_dir() and not path.is_file():
            continue
        meta = Path(str(path) + ".meta")
        report.checks += 1
        if not meta.is_file():
            report.error(f"Missing .meta file for {path.relative_to(root)}")
    if (root / "Assets" / "Resources").exists():
        report.warn(
            "Assets/Resources exists (pre-existing runtime sprite bytes). "
            "This is a documented deviation from the zero-external-assets contract."
        )


def check_scene(report: Report, root: Path) -> None:
    scene = root / "Assets" / "Orchard" / "Scenes" / "Bootstrap.unity"
    meta = Path(str(scene) + ".meta")
    settings = root / "ProjectSettings" / "EditorBuildSettings.asset"
    if not scene.is_file():
        report.error("Bootstrap.unity is missing")
        return
    if not meta.is_file():
        report.error("Bootstrap.unity.meta is missing")
        return
    try:
        scene_text = scene.read_text(encoding="utf-8")
        meta_text = meta.read_text(encoding="utf-8")
        settings_text = settings.read_text(encoding="utf-8")
    except OSError as exc:
        report.error(f"Could not read scene/build settings: {exc}")
        return
    report.checks += 1
    if "GameObject:" in scene_text or "MonoBehaviour:" in scene_text:
        report.error("Bootstrap.unity must be an empty scene; OrchardBoot creates the game at runtime")
    match = GUID_RE.search(meta_text)
    if not match:
        report.error("Bootstrap.unity.meta has no GUID")
        return
    scene_guid = match.group(1)
    if "Assets/Orchard/Scenes/Bootstrap.unity" not in settings_text:
        report.error("EditorBuildSettings.asset does not reference Bootstrap.unity")
    if scene_guid not in settings_text:
        report.error("EditorBuildSettings.asset GUID does not match Bootstrap.unity.meta")
    if "enabled: 1" not in settings_text:
        report.error("Bootstrap.unity is not enabled in EditorBuildSettings.asset")


def check_packages(report: Report, root: Path) -> None:
    manifest = read_json(report, root / "Packages" / "manifest.json")
    lock = read_json(report, root / "Packages" / "packages-lock.json")
    if not isinstance(manifest, dict) or not isinstance(lock, dict):
        return
    deps = manifest.get("dependencies") or {}
    locked = lock.get("dependencies") or {}
    if deps.get("com.unity.test-framework") != "1.4.6":
        report.error("Packages/manifest.json must pin com.unity.test-framework 1.4.6")
    if "com.unity.test-framework" not in locked:
        report.error("packages-lock.json is missing com.unity.test-framework; let Unity resolve the lock file")
    else:
        entry = locked["com.unity.test-framework"]
        if entry.get("version") not in ("1.4.6", "1.6.0") or entry.get("source") not in ("registry", "builtin"):
            report.error("packages-lock.json has the wrong com.unity.test-framework entry")
    if "com.unity.ext.nunit" not in locked:
        report.error("packages-lock.json is missing com.unity.ext.nunit")
    else:
        entry = locked["com.unity.ext.nunit"]
        if entry.get("version") not in ("2.0.3", "2.0.5") or entry.get("source") not in ("registry", "builtin"):
            report.error("com.unity.ext.nunit must be 2.0.3 or 2.0.5")
    for name, version in deps.items():
        if isinstance(version, str) and (version.startswith("file:") or version.startswith("git:")):
            report.error(f"Unsupported non-registry dependency {name}: {version}")
    if list(deps.keys()) != sorted(deps.keys()):
        report.warn("Packages/manifest.json dependencies are not sorted alphabetically")


def check_project_settings(report: Report, root: Path) -> None:
    version_file = root / "ProjectSettings" / "ProjectVersion.txt"
    try:
        text = version_file.read_text(encoding="utf-8")
    except OSError as exc:
        report.error(f"Could not read ProjectVersion.txt: {exc}")
        return
    match = re.search(r"^m_EditorVersion:\s*(\S+)\s*$", text, re.MULTILINE)
    if not match or not re.match(r"^\d+\.\d+\.\d+[abcfpx]\d+$", match.group(1)):
        report.error("ProjectVersion.txt has no valid m_EditorVersion")
    revision = re.search(r"^m_EditorVersionWithRevision:\s*\S+\s+\(([0-9a-fA-F]+)\)", text, re.MULTILINE)
    if not revision:
        report.warn("ProjectVersion.txt has no editor revision")

    settings = root / "ProjectSettings" / "ProjectSettings.asset"
    try:
        settings_text = settings.read_text(encoding="utf-8")
    except OSError as exc:
        report.error(f"Could not read ProjectSettings.asset: {exc}")
        return
    if not re.search(r"^\s*webGLCompressionFormat:\s*2\s*$", settings_text, re.MULTILINE):
        report.error("webGLCompressionFormat must be 2 (Disabled) for static hosting without headers")
    fallback = re.search(r"^\s*webGLDecompressionFallback:\s*(\d+)\s*$", settings_text, re.MULTILINE)
    if fallback and fallback.group(1) != "0":
        report.error("webGLDecompressionFallback must be 0")


def check_team_and_codeowners(report: Report, root: Path) -> None:
    team = read_json(report, root / ".github" / "team.json")
    if isinstance(team, dict):
        try:
            config = load_team(team)
        except TeamConfigError as exc:
            report.error(f".github/team.json is invalid: {exc}")
            config = None
        if config is not None:
            if not config["configured"]:
                report.warn(
                    "team.json still contains REPLACE_ME_ logins. The Review gate fails closed until an "
                    "administrator replaces them with the three real GitHub usernames."
                )
            codeowners = root / ".github" / "CODEOWNERS"
            if codeowners.is_file():
                text = codeowners.read_text(encoding="utf-8")
                report.checks += 1
                if not any(line.strip().startswith("*") for line in text.splitlines()):
                    report.error("CODEOWNERS has no default '*' rule")
                if config["configured"]:
                    for login in config["logins"]:
                        if "@" + login not in text:
                            report.error(f"CODEOWNERS does not mention roster member @{login}")


def check_dependabot(report: Report, root: Path) -> None:
    data = read_yaml(report, root / ".github" / "dependabot.yml")
    if not isinstance(data, dict):
        return
    if data.get("version") != 2:
        report.error("dependabot.yml must use version: 2")
    ecosystems = {str(update.get("package-ecosystem")) for update in data.get("updates") or [] if isinstance(update, dict)}
    for needed in ("github-actions", "pip"):
        if needed not in ecosystems:
            report.error(f"dependabot.yml does not configure the {needed} ecosystem")


def check_gitignore_and_attributes(report: Report, root: Path) -> None:
    gitignore = root / ".gitignore"
    try:
        text = gitignore.read_text(encoding="utf-8")
    except OSError as exc:
        report.error(f"Could not read .gitignore: {exc}")
        return
    for needed in ("Library/", "Temp/", "Logs/", "obj/", "UserSettings/", ".vs/", "Build/", "artifacts/", "TestResults/", ".DS_Store", "*.csproj", "*.sln"):
        if needed not in text:
            report.error(f".gitignore is missing {needed}")
    attributes = root / ".gitattributes"
    try:
        attr_text = attributes.read_text(encoding="utf-8")
    except OSError as exc:
        report.error(f"Could not read .gitattributes: {exc}")
        return
    if "*.cs" not in attr_text or "text" not in attr_text:
        report.error(".gitattributes must normalise C# source line endings")


def check_markdown_links(report: Report, root: Path) -> None:
    for path in sorted(root.rglob("*.md")):
        if any(part in {".git", "Library", "Temp", "Build", "artifacts"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for target in MARKDOWN_LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#", "tel:")):
                continue
            clean = target.split("#", 1)[0]
            if not clean or clean.startswith("/"):
                candidate = root / clean.lstrip("/")
            else:
                candidate = path.parent / clean
            report.checks += 1
            if not candidate.exists():
                report.error(f"Broken link in {path.relative_to(root)}: {target}")


def check_tracked_files(report: Report, root: Path) -> None:
    try:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        report.warn("Not a git checkout; skipped tracked-file hygiene checks")
        return
    files = [f for f in proc.stdout.decode("utf-8", "replace").split("\0") if f]
    for rel in files:
        report.checks += 1
        if rel.endswith(".DS_Store"):
            report.error(f"Tracked .DS_Store: {rel}")
        if any(rel.startswith(prefix) for prefix in FORBIDDEN_TRACKED_DIRS):
            report.error(f"Generated/binary directory is tracked: {rel}")
        suffix = Path(rel).suffix.lower()
        if suffix in BINARY_SUFFIXES:
            report.error(f"Binary or secret-like file is tracked: {rel}")
        try:
            size = (root / rel).stat().st_size
        except OSError:
            continue
        if size > 2_000_000:
            report.warn(f"Large tracked file ({size} bytes): {rel}")


def check_required_files(report: Report, root: Path) -> None:
    for rel in REQUIRED_FILES:
        report.checks += 1
        path = root / rel
        if not path.is_file():
            report.error(f"Required file is missing: {rel}")
        elif path.stat().st_size == 0:
            report.error(f"Required file is empty: {rel}")


def validate(root: Path) -> Report:
    report = Report()
    check_required_files(report, root)
    workflows = check_workflows(report, root)
    check_ci_workflow(report, workflows)
    check_review_gate(report, workflows)
    check_reusable_workflows(report, workflows)
    check_security_and_nightly(report, workflows)
    check_assets(report, root)
    check_scene(report, root)
    check_packages(report, root)
    check_project_settings(report, root)
    check_team_and_codeowners(report, root)
    check_dependabot(report, root)
    check_gitignore_and_attributes(report, root)
    check_markdown_links(report, root)
    check_tracked_files(report, root)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors.")
    parser.add_argument("--out-json")
    parser.add_argument("--github-summary", default=None)
    args = parser.parse_args(argv)

    report = validate(Path(args.root).resolve())
    if args.strict:
        report.errors.extend(report.warnings)
        report.warnings = []
    payload = report.to_dict()
    text = json.dumps(payload, indent=2)
    print(text)
    if args.out_json:
        path = Path(args.out_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    markdown = report.markdown()
    if args.github_summary:
        with open(args.github_summary, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if not report.ok:
        for error in report.errors:
            print("error: " + error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
