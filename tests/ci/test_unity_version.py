import tempfile
import unittest
from pathlib import Path

from scripts.unity_version import image_for, read_revision, read_version


class UnityVersionTests(unittest.TestCase):
    def make_project(self, text):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        settings = root / "ProjectSettings"
        settings.mkdir()
        (settings / "ProjectVersion.txt").write_text(text, encoding="utf-8")
        self.addCleanup(tmp.cleanup)
        return root

    def test_reads_editor_version(self):
        root = self.make_project("m_EditorVersion: 6000.3.25f1\n")
        self.assertEqual("6000.3.25f1", read_version(root))

    def test_reads_revision(self):
        root = self.make_project(
            "m_EditorVersion: 6000.3.25f1\n"
            "m_EditorVersionWithRevision: 6000.3.25f1 (e1dba0a9aba4)\n"
        )
        self.assertEqual("e1dba0a9aba4", read_revision(root))

    def test_rejects_missing_version(self):
        root = self.make_project("m_EditorVersionWithRevision: nothing\n")
        with self.assertRaises(ValueError):
            read_version(root)

    def test_rejects_malformed_version(self):
        root = self.make_project("m_EditorVersion: latest\n")
        with self.assertRaises(ValueError):
            read_version(root)

    def test_builds_exact_gameci_image(self):
        self.assertEqual(
            "unityci/editor:ubuntu-6000.3.25f1-base-3.2.2",
            image_for("6000.3.25f1"),
        )
        self.assertEqual(
            "unityci/editor:ubuntu-6000.3.25f1-webgl-3.2.2",
            image_for("6000.3.25f1", "webgl"),
        )

    def test_unknown_flavor_is_rejected(self):
        with self.assertRaises(ValueError):
            image_for("6000.3.25f1", "dos")


if __name__ == "__main__":
    unittest.main()
