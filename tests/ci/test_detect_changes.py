import unittest

from scripts.detect_changes import classify, matches


class DetectChangesTests(unittest.TestCase):
    def test_markdown_only_is_docs_only(self):
        result = classify(["README.md", "docs/CI_CD.md", "docs/nested/image-notes.md"])
        self.assertTrue(result["docs_only"])
        self.assertFalse(result["unity"])
        self.assertFalse(result["build"])
        self.assertFalse(result["protected"])

    def test_code_forces_unity(self):
        result = classify(["README.md", "Assets/Orchard/Scripts/Core.cs"])
        self.assertFalse(result["docs_only"])
        self.assertTrue(result["unity"])
        self.assertTrue(result["build"])

    def test_mixed_protected_and_docs_still_requires_unity_and_ci_approval(self):
        result = classify(["README.md", ".github/workflows/ci.yml"])
        self.assertFalse(result["docs_only"])
        self.assertTrue(result["protected"])
        self.assertEqual([".github/workflows/ci.yml"], result["protected_files"])

    def test_workflow_change_is_protected(self):
        result = classify([".github/workflows/ci.yml"])
        self.assertTrue(result["protected"])
        self.assertFalse(result["docs_only"])

    def test_test_change_is_protected(self):
        result = classify(["Assets/Orchard/Tests/EditMode/AStarTests.cs"])
        self.assertTrue(result["protected"])
        self.assertTrue(result["unity"])

    def test_project_settings_change_is_protected(self):
        self.assertTrue(classify(["ProjectSettings/ProjectVersion.txt"])["protected"])
        self.assertTrue(classify(["Packages/manifest.json"])["protected"])

    def test_delete_only_change_is_not_docs_only(self):
        # The caller includes deleted paths; an empty list must never be treated as docs-only.
        result = classify([])
        self.assertFalse(result["docs_only"])
        self.assertTrue(result["unity"])

    def test_unknown_extension_forces_unity(self):
        result = classify(["README.md", "new-file.weird"])
        self.assertFalse(result["docs_only"])

    def test_path_leading_dot_slash_is_normalized(self):
        self.assertTrue(matches("./README.md", ("*.md",)))
        self.assertTrue(matches("./.github/workflows/ci.yml", (".github/**",)))

    def test_nested_docs_pattern_matches(self):
        self.assertTrue(matches("docs/team/approval.md", ("docs/**",)))

    def test_license_and_templates_are_docs(self):
        self.assertTrue(classify(["LICENSE"])["docs_only"])
        self.assertTrue(classify([".github/ISSUE_TEMPLATE/bug_report.yml"])["docs_only"])
        # A PR template is docs-only content but still a protected .github path.
        result = classify([".github/pull_request_template.md"])
        self.assertTrue(result["docs_only"])
        self.assertTrue(result["protected"])


if __name__ == "__main__":
    unittest.main()
