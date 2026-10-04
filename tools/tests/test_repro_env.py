import hashlib
import tempfile
import unittest
from pathlib import Path

from ccfa.repro_env import check


class ReproEnvTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()
        (self.root / "tools").mkdir()
        (self.root / "evidence").mkdir()
        (self.root / "tools" / "requirements.txt").write_text(
            "pyyaml==6.0\n",
            encoding="utf-8",
        )
        (self.root / "tools" / "requirements.lock").write_text(
            "pyyaml==6.0\n",
            encoding="utf-8",
        )
        (self.root / "evidence" / "pdflatex.txt").write_text(
            "MiKTeX-pdfTeX 4.11 (MiKTeX 24.1)\n",
            encoding="utf-8",
        )
        digest = "sha256:" + hashlib.sha256(
            (self.root / "tools" / "requirements.lock").read_bytes()
        ).hexdigest()
        self.path = self.root / "data" / "repro-environment.yaml"
        self.path.write_text(
            "version: 1\n"
            "python: '3.12.14'\n"
            "package_manager: pip\n"
            "requirements: tools/requirements.txt\n"
            "lockfile: tools/requirements.lock\n"
            f"lockfile_sha256: '{digest}'\n"
            "system_tools:\n"
            "  - name: MiKTeX\n"
            "    version: '24.1'\n"
            "    command: pdflatex --version\n"
            "    evidence: evidence/pdflatex.txt\n"
            "container:\n"
            "  image: python:3.12-slim\n"
            "  digest: sha256:" + "a" * 64 + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _codes(problems):
        return {problem.code for problem in problems}

    def test_valid_ledger_passes(self):
        problems, _advisories = check(self.root)
        self.assertEqual(problems, [])

    def test_missing_ledger_is_a_problem(self):
        self.path.unlink()
        problems, _advisories = check(self.root)
        self.assertIn("repro-env-ledger-missing", self._codes(problems))

    def test_lockfile_drift_is_a_problem(self):
        (self.root / "tools" / "requirements.lock").write_text(
            "pyyaml==6.0\nnew-package==1.0\n",
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("repro-env-lockfile-drift", self._codes(problems))

    def test_missing_requirements_is_a_problem(self):
        (self.root / "tools" / "requirements.txt").unlink()
        problems, _advisories = check(self.root)
        self.assertIn("repro-env-requirements-missing", self._codes(problems))

    def test_missing_evidence_is_a_problem(self):
        (self.root / "evidence" / "pdflatex.txt").unlink()
        problems, _advisories = check(self.root)
        self.assertIn("repro-env-evidence-missing", self._codes(problems))

    def test_evidence_mismatch_is_a_problem(self):
        (self.root / "evidence" / "pdflatex.txt").write_text(
            "different version output\n",
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("repro-env-evidence-mismatch", self._codes(problems))

    def test_invalid_container_digest_is_a_problem(self):
        self.path.write_text(
            self.path.read_text(encoding="utf-8").replace(
                "sha256:" + "a" * 64,
                "sha256:not-a-digest",
            ),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("repro-env-invalid-hash", self._codes(problems))

    def test_duplicate_system_tool_is_a_problem(self):
        text = self.path.read_text(encoding="utf-8")
        text = text.replace(
            "container:\n",
            "  - name: MiKTeX\n"
            "    version: '24.1'\n"
            "    command: pdflatex --version\n"
            "    evidence: evidence/pdflatex.txt\n"
            "container:\n",
        )
        self.path.write_text(text, encoding="utf-8")
        problems, _advisories = check(self.root)
        self.assertIn("repro-env-duplicate-tool", self._codes(problems))


if __name__ == "__main__":
    unittest.main()
