import json
import tempfile
import unittest
from pathlib import Path

from scripts import test_summary as ts

PASS_XML = """<?xml version="1.0" encoding="utf-8"?>
<test-run id="2" testcasecount="2" result="Passed" total="2" passed="2" failed="0" skipped="0">
  <test-suite type="Assembly" name="Orchard.Tests.EditMode.dll">
    <test-case id="1" name="A" fullname="Orchard.Tests.A" result="Passed" duration="0.1" />
    <test-case id="2" name="B" fullname="Orchard.Tests.B" result="Passed" duration="0.2" />
  </test-suite>
</test-run>
"""

FAIL_XML = """<?xml version="1.0" encoding="utf-8"?>
<test-run id="2">
  <test-suite type="Assembly" name="Orchard.Tests.EditMode.dll">
    <test-case id="3" name="C" fullname="Orchard.Tests.C" result="Failed" duration="0.3">
      <failure><message>expected 1 but was 2</message><stack-trace>at X()</stack-trace></failure>
    </test-case>
    <test-case id="4" name="D" fullname="Orchard.Tests.D" result="Skipped">
      <reason><message>not today</message></reason>
    </test-case>
  </test-suite>
</test-run>
"""


class SummaryTests(unittest.TestCase):
    def write(self, directory, name, text):
        path = Path(directory) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_all_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "results.xml", PASS_XML)
            summary = ts.collect(Path(tmp), "EditMode", min_tests=2, require_namespace="Orchard.Tests")
        self.assertTrue(summary.ok, summary.problems())
        self.assertEqual(2, summary.total)
        self.assertEqual(2, len(summary.passed))
        self.assertAlmostEqual(0.3, summary.duration)

    def test_failure_and_skip_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "results.xml", FAIL_XML)
            summary = ts.collect(Path(tmp), "EditMode", min_tests=1, require_namespace="Orchard.Tests")
        self.assertFalse(summary.ok)
        self.assertEqual(1, len(summary.failed))
        self.assertEqual(1, len(summary.skipped))
        self.assertIn("expected 1 but was 2", summary.failed[0].message)

    def test_allow_skipped_does_not_allow_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "results.xml", FAIL_XML)
            summary = ts.collect(Path(tmp), "EditMode", min_tests=1, allow_skipped=True)
        self.assertFalse(summary.ok)
        self.assertEqual(1, len(summary.failed))

    def test_empty_results_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = ts.collect(Path(tmp), "EditMode", min_tests=1)
        self.assertFalse(summary.ok)
        self.assertTrue(summary.parse_errors)

    def test_min_tests_fails_on_too_few(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "results.xml", PASS_XML)
            summary = ts.collect(Path(tmp), "EditMode", min_tests=50)
        self.assertFalse(summary.ok)
        self.assertIn("at least 50", summary.problems()[0])

    def test_namespace_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "results.xml", PASS_XML)
            summary = ts.collect(Path(tmp), "EditMode", min_tests=1, require_namespace="Other.Namespace")
        self.assertFalse(summary.ok)
        self.assertFalse(summary.namespace_ok)

    def test_deduplicates_same_case_across_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "a/results.xml", PASS_XML)
            self.write(tmp, "b/results.xml", PASS_XML)
            summary = ts.collect(Path(tmp), "EditMode", min_tests=2)
        self.assertEqual(2, summary.total)

    def test_malformed_xml_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "bad.xml", "<not xml")
            summary = ts.collect(Path(tmp), "EditMode", min_tests=1)
        self.assertFalse(summary.ok)
        self.assertTrue(summary.parse_errors)

    def test_to_dict_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "results.xml", FAIL_XML)
            summary = ts.collect(Path(tmp), "EditMode", min_tests=1)
        payload = summary.to_dict()
        self.assertEqual(1, payload["failed"])
        self.assertEqual(1, payload["skipped"])
        self.assertIn("Failed tests", summary.markdown())
        json.dumps(payload)

    def test_cli_writes_reports_and_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "results.xml", FAIL_XML)
            out_json = Path(tmp) / "out" / "summary.json"
            out_md = Path(tmp) / "out" / "summary.md"
            summary_file = Path(tmp) / "summary.md"
            code = ts.main([
                "--results-dir", tmp,
                "--label", "EditMode",
                "--out-json", str(out_json),
                "--out-markdown", str(out_md),
                "--github-summary", str(summary_file),
            ])
            self.assertEqual(1, code)
            self.assertTrue(out_json.is_file())
            self.assertIn("EditMode tests: FAIL", out_md.read_text(encoding="utf-8"))
            self.assertIn("EditMode tests: FAIL", summary_file.read_text(encoding="utf-8"))

    def test_cli_passes_when_real_tests_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write(tmp, "results.xml", PASS_XML)
            code = ts.main(["--results-dir", tmp, "--label", "PlayMode", "--min-tests", "2"])
        self.assertEqual(0, code)


if __name__ == "__main__":
    unittest.main()
