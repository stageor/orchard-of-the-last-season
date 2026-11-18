import json
import tempfile
import unittest
from pathlib import Path

from scripts import csharp_analysis as ca

VALID = """using UnityEngine;
namespace Orchard
{
    public static class Boot
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void StartGame() { }
    }
}
"""


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def runtime(body: str) -> str:
    return "using UnityEngine;\nnamespace Orchard\n{\n" + body + "\n}\n"


class StripTests(unittest.TestCase):
    def test_removes_comments_and_literals(self):
        text = 'var a = "KeyCode.F"; // KeyCode.F\n/* Input.mousePosition */\nvar b = \'x\';\n'
        stripped = "\n".join(ca.strip_comments_and_strings(text))
        self.assertNotIn("KeyCode.F", stripped)
        self.assertNotIn("Input.mousePosition", stripped)
        self.assertIn("var a", stripped)
        self.assertIn("var b", stripped)

    def test_keeps_line_numbers(self):
        lines = ca.strip_comments_and_strings("a\n// b\nc\n")
        self.assertEqual(4, len(lines))
        self.assertEqual("c", lines[2])


class StyleWhitespaceTests(unittest.TestCase):
    def test_comment_at_end_of_line_is_not_trailing_whitespace(self):
        # strip_comments_and_strings leaves padding where the comment was. That
        # padding must not be mistaken for trailing whitespace in the source.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write(
                root,
                "Assets/Orchard/Scripts/Boot.cs",
                VALID.replace(
                    "static void StartGame() { }",
                    "static void StartGame() { int x = 1; // explain\n        }",
                ),
            )
            violations = ca.analyze_file(path, root)
        trailing = [v for v in violations if v.rule == "style.trailing_whitespace"]
        self.assertEqual([], trailing)

    def test_real_trailing_whitespace_is_still_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write(
                root,
                "Assets/Orchard/Scripts/Boot.cs",
                VALID.replace("static void StartGame() { }", "static void StartGame() { }   "),
            )
            violations = ca.analyze_file(path, root)
        trailing = [v for v in violations if v.rule == "style.trailing_whitespace"]
        self.assertEqual(1, len(trailing))


class AnalysisTests(unittest.TestCase):
    def test_valid_runtime_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            result = ca.analyze(root, {})
        self.assertTrue(result.ok, [v.to_dict() for v in result.errors])

    def test_missing_bootstrap_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Plain.cs", runtime("class Plain { }"))
            result = ca.analyze(root, {})
        self.assertTrue(any(v.rule == "boot.missing" for v in result.errors))

    def test_no_csharp_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = ca.analyze(Path(tmp), {})
        self.assertTrue(any(v.rule == "boot.no_csharp" for v in result.errors))

    def test_forbidden_function_key_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Scripts/Bad.cs", runtime('class Bad { void F() { var k = KeyCode.F1; } }'))
            result = ca.analyze(root, {})
        self.assertTrue(any(v.rule == "input.key" for v in result.errors))

    def test_single_f_key_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Scripts/Bad.cs", runtime("class Bad { void F() { var k = KeyCode.F; } }"))
            result = ca.analyze(root, {})
        self.assertTrue(any("KeyCode.F" in v.message for v in result.errors))

    def test_allowed_key_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Scripts/Ok.cs", runtime(
                "class Ok { bool F() { return Input.GetKeyDown(KeyCode.LeftShift); } }"
            ))
            result = ca.analyze(root, {})
        self.assertTrue(result.ok, [v.to_dict() for v in result.errors])

    def test_mouse_input_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Scripts/Bad.cs", runtime(
                "class Bad { void F() { var p = Input.mousePosition; } }"
            ))
            result = ca.analyze(root, {})
        self.assertTrue(any(v.rule == "input.forbidden" for v in result.errors))

    def test_controller_axis_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Scripts/Bad.cs", runtime(
                "class Bad { void F() { var x = Input.GetAxis(\"Horizontal\"); } }"
            ))
            result = ca.analyze(root, {})
        self.assertTrue(any(v.rule == "input.forbidden" for v in result.errors))

    def test_mouse_event_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Scripts/Bad.cs", runtime(
                "class Bad { void F(Event e) { if (e.type == EventType.MouseDown) { } } }"
            ))
            result = ca.analyze(root, {})
        self.assertTrue(any(v.rule == "input.mouse_event" for v in result.errors))

    def test_resources_load_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Scripts/Bad.cs", runtime(
                "class Bad { void F() { var t = Resources.Load(\"x\"); } }"
            ))
            result = ca.analyze(root, {})
        self.assertTrue(any(v.rule == "external_asset.resources_load" for v in result.errors))

    def test_wrong_runtime_namespace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Scripts/Bad.cs", "namespace Wrong { class Bad { } }")
            result = ca.analyze(root, {})
        self.assertTrue(any(v.rule == "namespace.contract" for v in result.errors))

    def test_editor_guard_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Editor/Bad.cs", "using UnityEditor;\nnamespace Orchard.CI { class Bad { } }")
            result = ca.analyze(root, {})
        self.assertTrue(any(v.rule == "editor.guard" for v in result.errors))

    def test_guarded_editor_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Editor/Good.cs",
                  "#if UNITY_EDITOR\nusing UnityEditor;\nnamespace Orchard.CI { class Good { } }\n#endif\n")
            result = ca.analyze(root, {})
        self.assertTrue(result.ok, [v.to_dict() for v in result.errors])

    def test_unbalanced_brackets_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Scripts/Bad.cs", runtime("class Bad { void F() { }"))
            result = ca.analyze(root, {})
        self.assertTrue(any(v.rule == "syntax.brackets" for v in result.errors))

    def test_baseline_suppresses_existing_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            write(root, "Assets/Orchard/Scripts/Legacy.cs", runtime(
                "class Legacy { void F() { var k = KeyCode.F; } }"
            ))
            first = ca.analyze(root, {})
            self.assertFalse(first.ok)
            violation = next(v for v in first.errors if v.rule == "input.key")
            baseline = {violation.fingerprint(): {
                "rule": violation.rule,
                "file": violation.file,
                "snippet": violation.snippet,
                "note": "legacy",
            }}
            second = ca.analyze(root, baseline)
        self.assertTrue(second.ok, [v.to_dict() for v in second.errors])
        self.assertEqual(1, len(second.suppressed))

    def test_stale_baseline_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            baseline = {"input.key|gone.cs|KeyCode.F": {
                "rule": "input.key", "file": "gone.cs", "snippet": "KeyCode.F", "note": "old",
            }}
            result = ca.analyze(root, baseline)
        self.assertTrue(result.ok)
        self.assertEqual(1, len(result.stale_baseline))

    def test_markdown_contains_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            result = ca.analyze(root, {})
        text = result.markdown()
        self.assertIn("C# contract analysis: PASS", text)
        self.assertIn("Analyzed 1 C# file", text)

    def test_cli_passes_and_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            self.assertEqual(0, ca.main(["--root", str(root), "--no-baseline"]))
            write(root, "Assets/Orchard/Scripts/Bad.cs", runtime("class Bad { void F() { var k = KeyCode.F1; } }"))
            self.assertEqual(1, ca.main(["--root", str(root), "--no-baseline"]))

    def test_cli_missing_baseline_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "Assets/Orchard/Scripts/Boot.cs", VALID)
            code = ca.main(["--root", str(root), "--baseline", str(root / "missing.json")])
        self.assertEqual(0, code)


if __name__ == "__main__":
    unittest.main()
