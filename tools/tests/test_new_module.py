"""Tests for :mod:`ccfa.new_module`."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from ccfa import new_module

FIXTURE_FILES = {
    "tools/ccfa/__init__.py": "",
    "tools/ccfa/existing.py": (
        '"""existing."""\n'
        "\n"
        "\n"
        "def main(argv):\n"
        "    return 0\n"
    ),
    "tools/ccfa/dispatch.py": (
        '"""dispatch."""\n'
        "\n"
        "COMMANDS: dict[str, str] = {\n"
        '    "existing": "ccfa.existing",\n'
        "}\n"
    ),
    "tools/ccfa/test_impact.py": (
        '"""impact."""\n'
        "\n"
        "_TOOLS_EXACT = {\n"
        '    "tools/ccfa/existing.py": (\n'
        '        "tools.tests.test_existing",\n'
        "    ),\n"
        "}\n"
    ),
    "tools/tests/__init__.py": "",
    "tools/tests/test_existing.py": (
        "import unittest\n"
        "\n"
        "\n"
        "class ExistingTests(unittest.TestCase):\n"
        "    def test_ok(self):\n"
        "        self.assertTrue(True)\n"
    ),
    "tools/tests/test_scripts.py": (
        '"""wrappers."""\n'
        "\n"
        "CCFA_WRAPPERS = {\n"
        '    "existing": "existing.ps1",\n'
        "}\n"
    ),
    "tools/tests/test_docs_consistency.py": (
        '"""docs."""\n'
        "\n"
        "CLI_WRAPPERS = {\n"
        '    "existing": "scripts/existing.ps1",\n'
        "}\n"
    ),
    ".github/workflows/tests.yml": (
        "jobs:\n"
        "  tests:\n"
        "    steps:\n"
        "      - name: Compile core modules\n"
        "        run: |\n"
        "          python -m py_compile \\\n"
        "            tools/ccfa/existing.py\n"
    ),
    "scripts/existing.ps1": "# existing wrapper\n",
    "README.md": (
        "# Fixture\n"
        "\n"
        "| 模块 | 一句话作用 | PowerShell 入口 |\n"
        "| --- | --- | --- |\n"
        "| `tools/ccfa/existing.py` | existing gate | `scripts/existing.ps1` |\n"
        "\n"
        "## Next\n"
    ),
}


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture(root: Path) -> None:
    for relative, text in FIXTURE_FILES.items():
        _write(root, relative, text)


class CreateTests(unittest.TestCase):
    def test_create_wires_module_wrapper_test_and_six_inventories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)

            payload = new_module.create(root, "demo_gate", "演示门")

            self.assertEqual(payload["module"], "ccfa.demo_gate")
            self.assertEqual(payload["command"], "demo-gate")
            self.assertEqual(len(payload["files"]), 9)
            module_text = (root / "tools/ccfa/demo_gate.py").read_text("utf-8")
            tree = ast.parse(module_text)
            self.assertTrue(
                any(
                    isinstance(node, ast.FunctionDef) and node.name == "main"
                    for node in tree.body
                )
            )
            self.assertIn('"demo-gate": "ccfa.demo_gate",',
                          (root / "tools/ccfa/dispatch.py").read_text("utf-8"))
            self.assertIn('"demo_gate": "demo-gate.ps1",',
                          (root / "tools/tests/test_scripts.py").read_text("utf-8"))
            self.assertIn('"demo_gate": "scripts/demo-gate.ps1",',
                          (root / "tools/tests/test_docs_consistency.py").read_text("utf-8"))
            self.assertIn("tools/ccfa/demo_gate.py",
                          (root / ".github/workflows/tests.yml").read_text("utf-8"))
            self.assertIn('"tools/ccfa/demo_gate.py":',
                          (root / "tools/ccfa/test_impact.py").read_text("utf-8"))
            self.assertIn("`tools/ccfa/demo_gate.py`",
                          (root / "README.md").read_text("utf-8"))
            self.assertTrue((root / "scripts/demo-gate.ps1").is_file())
            self.assertTrue((root / "tools/tests/test_demo_gate.py").is_file())
            ast.parse((root / "tools/tests/test_demo_gate.py").read_text("utf-8"))

    def test_create_keeps_existing_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)

            new_module.create(root, "demo_gate", "演示门")

            self.assertIn('"existing": "ccfa.existing",',
                          (root / "tools/ccfa/dispatch.py").read_text("utf-8"))
            self.assertIn("`tools/ccfa/existing.py`",
                          (root / "README.md").read_text("utf-8"))

    def test_create_refuses_an_existing_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)

            with self.assertRaisesRegex(new_module.ScaffoldError, "已存在"):
                new_module.create(root, "existing", "重复")

    def test_create_refuses_an_invalid_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)

            for name in ("Demo", "1gate", "demo-gate", "__init__"):
                with self.subTest(name=name):
                    with self.assertRaises(new_module.ScaffoldError):
                        new_module.create(root, name, "非法")

    def test_create_writes_nothing_when_an_anchor_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _write(root, "README.md", "# Fixture\n\n没有模块表。\n")

            with self.assertRaisesRegex(new_module.ScaffoldError, "模块表头"):
                new_module.create(root, "demo_gate", "演示门")

            self.assertFalse((root / "tools/ccfa/demo_gate.py").exists())
            self.assertFalse((root / "scripts/demo-gate.ps1").exists())
            self.assertFalse((root / "tools/tests/test_demo_gate.py").exists())


class AuditTests(unittest.TestCase):
    def test_audit_is_clean_on_a_consistent_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)

            self.assertEqual(new_module.audit(root), [])

    def test_audit_is_clean_after_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            new_module.create(root, "demo_gate", "演示门")

            self.assertEqual(new_module.audit(root), [])

    def test_audit_reports_the_missing_readme_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            new_module.create(root, "demo_gate", "演示门")
            text = (root / "README.md").read_text("utf-8")
            _write(root, "README.md", text.replace("| `tools/ccfa/demo_gate.py`", "| 模块"))

            codes = {problem.code for problem in new_module.audit(root)}

            self.assertIn("new-module-missing-readme", codes)

    def test_audit_reports_a_stale_inventory_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            _write(
                root,
                "tools/ccfa/dispatch.py",
                'COMMANDS: dict[str, str] = {\n'
                '    "existing": "ccfa.existing",\n'
                '    "ghost": "ccfa.ghost",\n'
                "}\n",
            )

            codes = {problem.code for problem in new_module.audit(root)}

            self.assertIn("new-module-stale-dispatch", codes)


class CliTests(unittest.TestCase):
    def test_main_creates_and_audits_through_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)

            exit_code = new_module.main(
                [
                    "ccfa new-module",
                    "create",
                    "demo_gate",
                    "--root",
                    str(root),
                    "--summary",
                    "演示门",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(new_module.main(["ccfa new-module", "audit", "--root", str(root)]), 0)

    def test_main_reports_a_scaffold_error_as_a_tool_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)

            exit_code = new_module.main(
                ["ccfa new-module", "create", "existing", "--root", str(root)]
            )

            self.assertEqual(exit_code, 2)

    def test_main_refuses_an_unknown_command_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                new_module.main(["ccfa new-module", "explode", "--root", tmp])


if __name__ == "__main__":
    unittest.main()
