import json
import tempfile
import unittest
from pathlib import Path

from scripts import verify_build as vb


def write(path: Path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())


def build_info(root: Path, target: str, **overrides):
    values = {
        "product": "OrchardOfTheLastSeason",
        "version": "1.0",
        "unityVersion": "6000.3.25f1",
        "target": target,
        "commit": "c" * 40,
        "totalErrors": "0",
        "totalWarnings": "0",
        "sizeBytes": "1000000",
    }
    if target == "WebGL":
        values["webglCompression"] = "Disabled"
    values.update(overrides)
    text = "".join(f"{k}={v}\n" for k, v in values.items())
    write(root / "BUILD_INFO.txt", text)


class VerifyBuildTests(unittest.TestCase):
    def project(self, tmp):
        write(Path(tmp) / "ProjectSettings" / "ProjectVersion.txt", "m_EditorVersion: 6000.3.25f1\n")
        return Path(tmp)

    def windows(self, tmp):
        root = Path(tmp) / "Build" / "Windows"
        write(root / "OrchardOfTheLastSeason.exe", b"MZ" + b"\0" * 100)
        write(root / "OrchardOfTheLastSeason_Data" / "globalgamemanagers", b"ggm")
        write(root / "OrchardOfTheLastSeason_Data" / "level0", b"level")
        write(root / "UnityPlayer.dll", b"MZ")
        build_info(root, "StandaloneWindows64")
        return root

    def webgl(self, tmp):
        root = Path(tmp) / "Build" / "WebGL"
        write(root / "index.html", "<script>createUnityInstance(document.querySelector('canvas'), {}, Build/);</script>")
        write(root / "Build" / "OrchardOfTheLastSeason.wasm", b"\x00asm" + b"\0" * 50)
        write(root / "Build" / "OrchardOfTheLastSeason.data", b"data")
        write(root / "Build" / "OrchardOfTheLastSeason.framework.js", b"js")
        build_info(root, "WebGL")
        return root

    def test_valid_windows_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.windows(tmp)
            check = vb.verify("windows", root, self.project(tmp), "c" * 40, 10)
        self.assertTrue(check.ok, check.problems)
        self.assertEqual("6000.3.25f1", check.info["unityVersion"])

    def test_windows_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.windows(tmp)
            (root / "UnityPlayer.dll").unlink()
            (root / "OrchardOfTheLastSeason_Data" / "globalgamemanagers").unlink()
            check = vb.verify("windows", root, self.project(tmp), "c" * 40, 10)
        self.assertFalse(check.ok)
        self.assertTrue(any("UnityPlayer.dll" in p for p in check.problems))
        self.assertTrue(any("globalgamemanagers" in p for p in check.problems))

    def test_windows_wrong_commit_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.windows(tmp)
            build_info(root, "StandaloneWindows64", commit="d" * 40, unityVersion="2022.3.1f1", totalErrors="2")
            check = vb.verify("windows", root, self.project(tmp), "c" * 40, 10)
        self.assertFalse(check.ok)
        self.assertTrue(any("commit" in p for p in check.problems))
        self.assertTrue(any("Unity" in p for p in check.problems))
        self.assertTrue(any("totalErrors" in p for p in check.problems))

    def test_valid_webgl_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.webgl(tmp)
            check = vb.verify("webgl", root, self.project(tmp), "c" * 40, 10)
        self.assertTrue(check.ok, check.problems)
        self.assertEqual("Disabled", check.info["webglCompression"])

    def test_webgl_rejects_compressed_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.webgl(tmp)
            write(root / "Build" / "OrchardOfTheLastSeason.data.gz", b"gz")
            check = vb.verify("webgl", root, self.project(tmp), "c" * 40, 10)
        self.assertFalse(check.ok)
        self.assertTrue(any("Compressed" in p for p in check.problems))

    def test_webgl_rejects_enabled_compression(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.webgl(tmp)
            build_info(root, "WebGL", webglCompression="Gzip")
            check = vb.verify("webgl", root, self.project(tmp), "c" * 40, 10)
        self.assertFalse(check.ok)
        self.assertTrue(any("Gzip" in p for p in check.problems))

    def test_webgl_rejects_bad_wasm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.webgl(tmp)
            write(root / "Build" / "OrchardOfTheLastSeason.wasm", b"not wasm")
            check = vb.verify("webgl", root, self.project(tmp), "c" * 40, 10)
        self.assertFalse(check.ok)
        self.assertTrue(any("WebAssembly" in p for p in check.problems))

    def test_webgl_missing_data_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.webgl(tmp)
            (root / "index.html").unlink()
            (root / "Build" / "OrchardOfTheLastSeason.data").unlink()
            check = vb.verify("webgl", root, self.project(tmp), "c" * 40, 10)
        self.assertFalse(check.ok)
        self.assertTrue(any("index.html" in p for p in check.problems))
        self.assertTrue(any(".data" in p for p in check.problems))

    def test_missing_build_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.windows(tmp)
            (root / "BUILD_INFO.txt").unlink()
            check = vb.verify("windows", root, self.project(tmp), "", 10)
        self.assertFalse(check.ok)
        self.assertTrue(any("BUILD_INFO" in p for p in check.problems))

    def test_size_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.windows(tmp)
            check = vb.verify("windows", root, self.project(tmp), "c" * 40, 10_000_000)
        self.assertFalse(check.ok)
        self.assertTrue(any("at least" in p for p in check.problems))

    def test_cli_outputs_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.windows(tmp)
            out = Path(tmp) / "report.json"
            code = vb.main([
                "--target", "windows",
                "--root", str(root),
                "--project-root", str(self.project(tmp)),
                "--expected-commit", "c" * 40,
                "--min-size", "10",
                "--out-json", str(out),
            ])
            self.assertEqual(0, code)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
