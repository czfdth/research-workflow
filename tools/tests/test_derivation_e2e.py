"""Derive real venue projects and compile their actual main files.

The venue root is intentionally not patched here: this file is the
end-to-end evidence that the real
``$CODEX_HOME/skills/ccf-latex-templates`` library produces projects whose
actual venue main files compile with the host MiKTeX engine.

``latex_check --compile`` is not invoked directly because it hardcodes
``manuscript/main.tex``, while the real templates use names such as
``neurips_2026.tex`` and ``acl_latex.tex``. The same real compile sequence
(``ccfa.latex_compile.compile_document``) is used on the resolved main file
instead. Its structural scan also reports the upstream templates' placeholder
figures and guideline markup, which would make the CLI exit 1 even when the
real document compiles.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from ccfa.latex_compile import compile_document, find_engine
from ccfa.memory import main as memory_main
from ccfa.milestones import main as milestones_main
from ccfa.texdoc import find_main_tex
from ccfa.validate import main as validate_main
from newpaper.create import create_project


class DerivationEndToEnd(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.papers = Path(self._temporary.name) / "papers"

    def _derive(self, slug: str, venue: str) -> Path:
        return create_project(
            papers_root=self.papers,
            slug=slug,
            venue=venue,
            year="2027",
            mode="conference",
            title=f"{venue} smoke",
            deadline=None,
        )

    def _run(self, command, argv):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = command(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def _assert_skeleton(self, root: Path) -> None:
        self.assertTrue((root / "ccfa.yaml").is_file())
        manuscript = root / "manuscript"
        main_tex = find_main_tex(manuscript)
        self.assertEqual(main_tex.suffix, ".tex")
        self.assertTrue(any(manuscript.glob("*.sty")))
        self.assertTrue((manuscript / "references.bib").is_file())
        self.assertEqual(
            json.loads(
                (root / "data" / "provenance.json").read_text(encoding="utf-8")
            ),
            {"version": 1, "files": {}},
        )
        for rel in (
            "experiments/log",
            "experiments/results",
            "memory/ideas.md",
            "memory/dead-ends.md",
            "reviews",
            "submission/repro",
        ):
            with self.subTest(rel=rel):
                self.assertTrue((root / rel).exists(), f"缺少 {rel}")

    def _assert_toolchain(self, root: Path) -> None:
        code, _, stderr = self._run(
            validate_main,
            ["validate.py", str(root / "ccfa.yaml")],
        )
        self.assertEqual(code, 0, stderr)

        code, stdout, stderr = self._run(
            milestones_main,
            ["milestones.py", "stage", "--paper-root", str(root)],
        )
        self.assertEqual(code, 0, stderr)
        stage = json.loads(stdout)
        self.assertEqual(stage["current"], "idea")
        self.assertEqual(set(stage), {"current", "gate", "updated_at"})

        code, stdout, stderr = self._run(
            milestones_main,
            [
                "milestones.py",
                "due",
                "--paper-root",
                str(root),
                "--today",
                "2026-10-03",
            ],
        )
        self.assertEqual(code, 0, stderr)
        due = json.loads(stdout)
        self.assertEqual(due["mode"], "sequential")
        self.assertIsNone(due["deadline"])
        self.assertEqual(due["due"], [])
        self.assertEqual(due["problems"], [])

        code, stdout, stderr = self._run(
            memory_main,
            ["memory.py", "--paper-root", str(root), "check"],
        )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["problem_count"], 0)

    def _compile_actual_main(self, root: Path):
        manuscript = root / "manuscript"
        main_tex = find_main_tex(manuscript)
        engine = find_engine()
        if engine is None:
            self.skipTest("本机找不到 pdflatex/xelatex，无法完成真编译证据")
        log: list[dict] = []

        def runner(argv, cwd):
            completed = subprocess.run(
                list(argv),
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            output = (completed.stdout or "") + (completed.stderr or "")
            log.append(
                {
                    "argv": list(argv),
                    "cwd": str(cwd),
                    "returncode": completed.returncode,
                    "output": output,
                }
            )
            return completed.returncode, output

        report = compile_document(main_tex, engine, runner=runner)
        return manuscript, main_tex, engine, report, log

    def _failure_diagnostic(self, main_tex: Path, report, log) -> str:
        lines = [
            f"main_tex={main_tex}",
            f"steps={list(report.steps)!r}",
        ]
        failed = next(
            (
                index
                for index, step in enumerate(report.steps)
                if step.status == "failed"
            ),
            None,
        )
        if failed is not None and failed < len(log):
            entry = log[failed]
            lines.append("failed_command=" + " ".join(entry["argv"]))
            lines.append(f"failed_returncode={entry['returncode']}")
            lines.extend(entry["output"].splitlines()[:30])
        return "\n".join(lines)

    def _assert_compiles(self, root: Path):
        manuscript, main_tex, engine, report, log = self._compile_actual_main(root)
        pdf = manuscript / f"{main_tex.stem}.pdf"
        diagnostic = self._failure_diagnostic(main_tex, report, log)
        self.assertTrue(
            report.steps and report.steps[-1].status == "ran",
            f"{engine} 编译序列未成功:\n{diagnostic}",
        )
        self.assertTrue(pdf.is_file(), f"缺少 PDF: {pdf}\n{diagnostic}")
        self.assertGreater(pdf.stat().st_size, 0)
        return main_tex, pdf, engine, report

    def test_derived_neurips_project_compiles_end_to_end(self):
        root = self._derive("neurips-smoke", "NeurIPS")

        self._assert_skeleton(root)
        self._assert_toolchain(root)
        main_tex, pdf, engine, report = self._assert_compiles(root)

        self.assertEqual(main_tex.name, "neurips_2026.tex")
        self.assertEqual(report.engine, engine)
        self.assertGreater(pdf.stat().st_size, 0)

    def test_derived_acl_project_compiles_end_to_end(self):
        root = self._derive("acl-smoke", "ACL")

        self._assert_skeleton(root)
        self._assert_toolchain(root)
        self._assert_compiles(root)

    def test_derived_cvpr_project_preserves_nested_template_tree(self):
        root = self._derive("cvpr-smoke", "CVPR")
        manuscript = root / "manuscript"

        self.assertTrue((manuscript / "main.tex").is_file())
        self.assertTrue((manuscript / "cvpr.sty").is_file())
        for rel in ("sec/1_intro.tex", "sec/3_finalcopy.tex"):
            nested = manuscript / rel
            self.assertTrue(
                nested.is_file(),
                f"递归复制缺失: {nested.relative_to(root).as_posix()}",
            )


if __name__ == "__main__":
    unittest.main()
