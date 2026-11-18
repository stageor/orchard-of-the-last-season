import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import validate_repository as vr


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def meta(guid: str, folder=False) -> str:
    if folder:
        return f"fileFormatVersion: 2\nguid: {guid}\nfolderAsset: yes\nDefaultImporter:\n  externalObjects: {{}}\n"
    return f"fileFormatVersion: 2\nguid: {guid}\nDefaultImporter:\n  externalObjects: {{}}\n"


class AssetTests(unittest.TestCase):
    def test_missing_meta_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/A.cs", "class A {}")
            report = vr.Report()
            vr.check_assets(report, root)
        self.assertFalse(report.ok)
        self.assertTrue(any("Missing .meta" in e for e in report.errors))

    def test_double_guid_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/A.cs", "class A {}")
            write(root, "Assets/Orchard/Scripts/A.cs.meta", meta("a" * 32))
            write(root, "Assets/Orchard/Scripts/B.cs", "class B {}")
            write(root, "Assets/Orchard/Scripts/B.cs.meta", meta("a" * 32))
            report = vr.Report()
            vr.check_assets(report, root)
        self.assertTrue(any("Duplicate GUID" in e for e in report.errors))

    def test_orphan_meta_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Gone.cs.meta", meta("b" * 32))
            report = vr.Report()
            vr.check_assets(report, root)
        self.assertTrue(any("Orphaned" in e for e in report.errors))

    def test_clean_asset_tree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets.meta", meta("a" * 32, folder=True))
            write(root, "Assets/Orchard.meta", meta("b" * 32, folder=True))
            write(root, "Assets/Orchard/Scripts.meta", meta("d" * 32, folder=True))
            write(root, "Assets/Orchard/Scripts/A.cs", "class A {}")
            write(root, "Assets/Orchard/Scripts/A.cs.meta", meta("c" * 32))
            report = vr.Report()
            vr.check_assets(report, root)
        self.assertTrue(report.ok, report.errors)


class SceneTests(unittest.TestCase):
    def make(self, root, guid="d" * 32, scene="%YAML 1.1\n", enabled="enabled: 1"):
        write(root, "Assets/Orchard/Scenes/Bootstrap.unity", scene)
        write(root, "Assets/Orchard/Scenes/Bootstrap.unity.meta", meta(guid))
        write(root, "ProjectSettings/EditorBuildSettings.asset",
              f"EditorBuildSettings:\n  m_Scenes:\n  - {enabled}\n    path: Assets/Orchard/Scenes/Bootstrap.unity\n    guid: {guid}\n")

    def test_valid_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make(root)
            report = vr.Report()
            vr.check_scene(report, root)
        self.assertTrue(report.ok, report.errors)

    def test_scene_with_gameobject_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make(root, scene="GameObject:\n  m_Name: Bad\n")
            report = vr.Report()
            vr.check_scene(report, root)
        self.assertTrue(any("empty scene" in e for e in report.errors))

    def test_guid_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make(root, guid="d" * 32)
            settings = root / "ProjectSettings/EditorBuildSettings.asset"
            settings.write_text(settings.read_text().replace("d" * 32, "e" * 32), encoding="utf-8")
            report = vr.Report()
            vr.check_scene(report, root)
        self.assertTrue(any("GUID" in e for e in report.errors))


class PackageTests(unittest.TestCase):
    def test_valid_manifest_and_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Packages/manifest.json", json.dumps({"dependencies": {"com.unity.test-framework": "1.4.6"}}))
            write(root, "Packages/packages-lock.json", json.dumps({"dependencies": {
                "com.unity.test-framework": {"version": "1.4.6", "source": "registry"},
                "com.unity.ext.nunit": {"version": "2.0.3", "source": "registry"},
            }}))
            report = vr.Report()
            vr.check_packages(report, root)
        self.assertTrue(report.ok, report.errors)

    def test_missing_test_framework_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Packages/manifest.json", json.dumps({"dependencies": {}}))
            write(root, "Packages/packages-lock.json", json.dumps({"dependencies": {}}))
            report = vr.Report()
            vr.check_packages(report, root)
        self.assertTrue(any("test-framework" in e for e in report.errors))


class SettingsTests(unittest.TestCase):
    def test_compression_must_be_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 6000.3.25f1\n")
            write(root, "ProjectSettings/ProjectSettings.asset", "  webGLCompressionFormat: 1\n")
            report = vr.Report()
            vr.check_project_settings(report, root)
        self.assertTrue(any("webGLCompressionFormat" in e for e in report.errors))

    def test_compression_disabled_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 6000.3.25f1\n")
            write(root, "ProjectSettings/ProjectSettings.asset", "  webGLCompressionFormat: 2\n")
            report = vr.Report()
            vr.check_project_settings(report, root)
        self.assertTrue(report.ok, report.errors)


class WorkflowTests(unittest.TestCase):
    def workflow(self, extra="", job_extra=""):
        return f"""name: CI
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - run: echo ok
{job_extra}
{extra}
"""

    def test_pinned_workflow_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ".github/workflows/ci.yml", self.workflow())
            report = vr.Report()
            workflows = vr.check_workflows(report, root)
        self.assertTrue(report.ok, report.errors)
        self.assertIn("ci.yml", workflows)

    def test_unpinned_action_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = self.workflow().replace(
                "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                "actions/checkout@v4",
            )
            write(root, ".github/workflows/ci.yml", text)
            report = vr.Report()
            vr.check_workflows(report, root)
        self.assertTrue(any("not pinned" in e for e in report.errors))

    def test_missing_timeout_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ".github/workflows/ci.yml", self.workflow().replace("    timeout-minutes: 5\n", ""))
            report = vr.Report()
            vr.check_workflows(report, root)
        self.assertTrue(any("timeout-minutes" in e for e in report.errors))

    def test_missing_permissions_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ".github/workflows/ci.yml", self.workflow().replace("permissions:\n  contents: read\n", ""))
            report = vr.Report()
            vr.check_workflows(report, root)
        self.assertTrue(any("permissions" in e for e in report.errors))

    def test_reusable_workflow_call_job_does_not_need_timeout(self):
        # GitHub rejects timeout-minutes on a job that calls a reusable workflow.
        # The called workflow's jobs carry the timeouts instead.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ".github/workflows/ci.yml", """name: CI
on:
  pull_request:
permissions:
  contents: read
jobs:
  call:
    uses: ./.github/workflows/reusable.yml
""")
            write(root, ".github/workflows/reusable.yml", """name: Reusable
on:
  workflow_call:
permissions:
  contents: read
jobs:
  work:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - run: echo ok
""")
            report = vr.Report()
            vr.check_workflows(report, root)
        self.assertTrue(report.ok, report.errors)

    def test_duplicate_yaml_key_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = self.workflow().replace("jobs:\n", "jobs:\n  duplicate: {}\n  duplicate: {}\n")
            write(root, ".github/workflows/ci.yml", text)
            report = vr.Report()
            vr.check_workflows(report, root)
        self.assertTrue(any("duplicate YAML key" in e for e in report.errors))

    def test_hardcoded_unity_version_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ".github/workflows/ci.yml", self.workflow(extra="    # 6000.3.25f1\n"))
            report = vr.Report()
            vr.check_workflows(report, root)
        self.assertTrue(any("hard-coded Unity version" in e for e in report.errors))

    def test_ci_gate_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs = "\n".join(
                f"  {job}:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n    steps:\n      - run: echo ok"
                for job in vr.REQUIRED_JOBS
            )
            gate = """  required-checks:
    name: Required checks
    if: always()
    needs: [changes, repository-health, csharp-analysis, unity-editmode, unity-playmode, build-windows, build-webgl]
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - run: echo ok
"""
            text = "name: CI\non:\n  pull_request:\npermissions:\n  contents: read\nconcurrency:\n  group: ci\n  cancel-in-progress: true\njobs:\n" + jobs + "\n" + gate
            write(root, ".github/workflows/ci.yml", text)
            report = vr.Report()
            workflows = vr.check_workflows(report, root)
            vr.check_ci_workflow(report, workflows)
        self.assertTrue(report.ok, report.errors)

    def test_review_gate_requires_safe_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = """name: Review
on:
  pull_request_target:
  pull_request_review:
  issue_comment:
permissions:
  contents: read
jobs:
  gate:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          ref: ${{ github.event.pull_request.head.sha }}
      - run: python3 scripts/check_approvals.py
"""
            write(root, ".github/workflows/review-gate.yml", text)
            report = vr.Report()
            workflows = vr.check_workflows(report, root)
            vr.check_review_gate(report, workflows)
        self.assertTrue(any("never check out" in e for e in report.errors))


class LinkTests(unittest.TestCase):
    def test_broken_local_link_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "README.md", "[docs](docs/missing.md)\n")
            report = vr.Report()
            vr.check_markdown_links(report, root)
        self.assertTrue(any("Broken link" in e for e in report.errors))

    def test_existing_local_link_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "README.md", "[docs](docs/guide.md)\n")
            write(root, "docs/guide.md", "# Guide\n")
            report = vr.Report()
            vr.check_markdown_links(report, root)
        self.assertTrue(report.ok, report.errors)

    def test_external_and_anchor_links_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "README.md", "[web](https://example.com)\n[top](#top)\n")
            report = vr.Report()
            vr.check_markdown_links(report, root)
        self.assertTrue(report.ok, report.errors)


class TeamTests(unittest.TestCase):
    def test_placeholder_team_warns_but_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ".github/team.json", json.dumps({
                "members": [
                    {"name": "Stanley", "login": "REPLACE_ME_stanley"},
                    {"name": "Zian", "login": "REPLACE_ME_zian"},
                    {"name": "Manu", "login": "REPLACE_ME_manu"},
                ]
            }))
            write(root, ".github/CODEOWNERS", "* @REPLACE_ME_stanley @REPLACE_ME_zian @REPLACE_ME_manu\n")
            report = vr.Report()
            vr.check_team_and_codeowners(report, root)
        self.assertTrue(report.ok, report.errors)
        self.assertTrue(any("REPLACE_ME_" in w for w in report.warnings))

    def test_invalid_team_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ".github/team.json", json.dumps({"members": []}))
            report = vr.Report()
            vr.check_team_and_codeowners(report, root)
        self.assertTrue(any("team.json is invalid" in e for e in report.errors))


class GitignoreTests(unittest.TestCase):
    def test_complete_gitignore_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ".gitignore", "\n".join([
                "Library/", "Temp/", "Logs/", "obj/", "UserSettings/", ".vs/",
                "Build/", "artifacts/", "TestResults/", ".DS_Store", "*.csproj", "*.sln",
            ]))
            write(root, ".gitattributes", "*.cs text eol=lf\n")
            report = vr.Report()
            vr.check_gitignore_and_attributes(report, root)
        self.assertTrue(report.ok, report.errors)

    def test_missing_build_ignore_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ".gitignore", "Library/\n")
            write(root, ".gitattributes", "*.cs text eol=lf\n")
            report = vr.Report()
            vr.check_gitignore_and_attributes(report, root)
        self.assertTrue(any("Build/" in e for e in report.errors))


class TrackedFileTests(unittest.TestCase):
    def test_tracked_ds_store_and_binary_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            write(root, ".DS_Store", "x")
            write(root, "Assets/thing.png", "x")
            subprocess.run(["git", "add", ".DS_Store", "Assets/thing.png"], cwd=root, check=True)
            report = vr.Report()
            vr.check_tracked_files(report, root)
        self.assertTrue(any(".DS_Store" in e for e in report.errors))
        self.assertTrue(any("Binary" in e or "binary" in e for e in report.errors))


class DependabotTests(unittest.TestCase):
    def test_requires_actions_and_pip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, ".github/dependabot.yml", """version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
""")
            report = vr.Report()
            vr.check_dependabot(report, root)
        self.assertTrue(report.ok, report.errors)


if __name__ == "__main__":
    unittest.main()
