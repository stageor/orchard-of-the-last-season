import json
import tempfile
import unittest
from pathlib import Path

from scripts import ci_gate


def needs(**overrides):
    data = {job: {"result": "success", "outputs": {}} for job in ci_gate.REQUIRED_JOBS}
    data["changes"]["outputs"] = {"docs_only": "false", "fork": "false"}
    for job, value in overrides.items():
        if isinstance(value, str):
            data[job] = {"result": value, "outputs": {}}
        else:
            data[job] = value
    return data


class GateTests(unittest.TestCase):
    def test_all_success_passes(self):
        gate = ci_gate.evaluate(needs(), False, False)
        self.assertTrue(gate.ok, gate.problems)

    def test_docs_only_allows_unity_skips(self):
        data = needs(**{job: "skipped" for job in ci_gate.UNITY_JOBS})
        data["changes"]["outputs"] = {"docs_only": "true", "fork": "false"}
        gate = ci_gate.evaluate(data, True, False)
        self.assertTrue(gate.ok, gate.problems)
        self.assertTrue(gate.jobs["unity-editmode"].allowed_skip)

    def test_docs_only_still_requires_health_and_analysis(self):
        data = needs(**{job: "skipped" for job in ci_gate.UNITY_JOBS})
        data["repository-health"] = {"result": "skipped", "outputs": {}}
        data["changes"]["outputs"] = {"docs_only": "true", "fork": "false"}
        gate = ci_gate.evaluate(data, True, False)
        self.assertFalse(gate.ok)
        self.assertTrue(any("repository-health" in p for p in gate.problems))

    def test_unexpected_unity_skip_blocks(self):
        data = needs(**{job: "skipped" for job in ci_gate.UNITY_JOBS})
        gate = ci_gate.evaluate(data, False, False)
        self.assertFalse(gate.ok)
        self.assertTrue(any("unity-editmode" in p for p in gate.problems))

    def test_cancelled_job_blocks(self):
        gate = ci_gate.evaluate(needs(**{"unity-playmode": "cancelled"}), False, False)
        self.assertFalse(gate.ok)
        self.assertIn("cancelled", gate.jobs["unity-playmode"].result)

    def test_failed_job_blocks(self):
        gate = ci_gate.evaluate(needs(**{"build-webgl": "failure"}), False, False)
        self.assertFalse(gate.ok)

    def test_missing_required_job_blocks(self):
        data = needs()
        del data["build-windows"]
        gate = ci_gate.evaluate(data, False, False)
        self.assertFalse(gate.ok)
        self.assertTrue(any("build-windows" in p for p in gate.problems))

    def test_fork_non_docs_skips_fail_with_instructions(self):
        data = needs(**{job: "skipped" for job in ci_gate.UNITY_JOBS})
        data["changes"]["outputs"] = {"docs_only": "false", "fork": "true"}
        gate = ci_gate.evaluate(data, False, True)
        self.assertFalse(gate.ok)
        self.assertTrue(any("same-repository branch" in p for p in gate.problems))

    def test_fork_docs_only_is_allowed(self):
        data = needs(**{job: "skipped" for job in ci_gate.UNITY_JOBS})
        data["changes"]["outputs"] = {"docs_only": "true", "fork": "true"}
        gate = ci_gate.evaluate(data, True, True)
        self.assertTrue(gate.ok, gate.problems)

    def test_changes_job_failure_blocks(self):
        data = needs(**{"changes": "failure"})
        gate = ci_gate.evaluate(data, False, False)
        self.assertFalse(gate.ok)

    def test_output_mismatch_is_a_warning_not_a_bypass(self):
        data = needs()
        data["changes"]["outputs"] = {"docs_only": "false", "fork": "false"}
        gate = ci_gate.evaluate(data, True, False)
        self.assertTrue(gate.ok)
        self.assertTrue(gate.warnings)

    def test_markdown_lists_every_required_job(self):
        gate = ci_gate.evaluate(needs(), False, False)
        text = gate.markdown()
        for job in ci_gate.REQUIRED_JOBS:
            self.assertIn(job, text)

    def test_json_parse_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            ci_gate.parse_needs("{bad")
        with self.assertRaises(ValueError):
            ci_gate.parse_needs("[]")

    def test_parse_bool(self):
        self.assertTrue(ci_gate.parse_bool("true"))
        self.assertTrue(ci_gate.parse_bool(True))
        self.assertFalse(ci_gate.parse_bool("false"))
        self.assertFalse(ci_gate.parse_bool(None))
        self.assertTrue(ci_gate.parse_bool(None, True))

    def test_cli_writes_summary_and_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "gate.json"
            summary = Path(tmp) / "summary.md"
            code = ci_gate.main([
                "--needs-json", json.dumps(needs(**{"unity-editmode": "failure"})),
                "--out-json", str(out),
                "--github-summary", str(summary),
            ])
            self.assertEqual(1, code)
            self.assertFalse(json.loads(out.read_text(encoding="utf-8"))["ok"])
            self.assertIn("Required checks: FAIL", summary.read_text(encoding="utf-8"))

    def test_cli_passes(self):
        code = ci_gate.main(["--needs-json", json.dumps(needs())])
        self.assertEqual(0, code)

    def test_cli_requires_needs(self):
        code = ci_gate.main([])
        self.assertEqual(2, code)


if __name__ == "__main__":
    unittest.main()
