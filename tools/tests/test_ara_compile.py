import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa.ara_compile import compile_ara, validate_ara


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


class AraCompileTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "data").mkdir()
        (self.paper / "experiments" / "log").mkdir(parents=True)
        (self.paper / "figures").mkdir()
        (self.paper / "experiments" / "log" / "RUN1.json").write_text(
            json.dumps(
                {
                    "run_id": "RUN1",
                    "status": "completed",
                    "metrics": {"accuracy": 0.8},
                }
            ),
            encoding="utf-8",
        )
        _write_yaml(
            self.paper / "ccfa.yaml",
            {
                "project": {
                    "title": "Test Paper",
                    "short_name": "test",
                },
                "target_venue": {
                    "name": "NeurIPS",
                    "year": "2027",
                    "mode": "conference",
                },
                "stage": {"current": "internal-review"},
            },
        )
        _write_yaml(
            self.paper / "data" / "claim-registry.yaml",
            {
                "version": 1,
                "claims": [
                    {
                        "id": "claim-1",
                        "statement": "X improves Y",
                        "type": "empirical",
                        "status": "supported",
                        "assumptions": [],
                        "limitations": [],
                        "proof": None,
                        "experiments": ["RUN1"],
                        "figures": ["F1"],
                        "citations": [],
                    }
                ],
            },
        )
        _write_yaml(
            self.paper / "data" / "exploration-graph.yaml",
            {
                "version": 1,
                "entries": [
                    {
                        "id": "X1",
                        "kind": "active",
                        "summary": "Test X against baseline",
                        "claim_ids": ["claim-1"],
                        "run_ids": ["RUN1"],
                        "rationale": "baseline comparison",
                    },
                    {
                        "id": "X2",
                        "kind": "dead-end",
                        "summary": "Alternative without X",
                        "claim_ids": ["claim-1"],
                        "run_ids": ["RUN1"],
                        "rationale": "performance collapsed",
                    },
                ],
            },
        )
        _write_yaml(
            self.paper / "figures" / "manifest.yaml",
            {
                "version": 1,
                "figures": [
                    {
                        "id": "F1",
                        "path": "figures/plot.pdf",
                        "sha256": "sha256:" + "a" * 64,
                        "source": "RUN1",
                    }
                ],
            },
        )

    def test_compile_creates_mandatory_scaffold_and_report(self):
        out = self.paper / "ara"

        report = compile_ara(self.paper, out)

        for rel in (
            "PAPER.md",
            "logic/problem.md",
            "logic/claims.md",
            "logic/concepts.md",
            "logic/experiments.md",
            "logic/solution/architecture.md",
            "logic/solution/algorithm.md",
            "logic/solution/constraints.md",
            "logic/solution/heuristics.md",
            "logic/related_work.md",
            "src/configs/training.md",
            "src/configs/model.md",
            "src/environment.md",
            "trace/exploration_tree.yaml",
            "evidence/README.md",
        ):
            with self.subTest(rel=rel):
                self.assertTrue((out / rel).is_file(), rel)
        self.assertFalse(report["seal_level1_ready"])
        self.assertIn("concepts>=5", report["unmet_requirements"])

    def test_claims_and_trace_are_mapped_from_ledgers(self):
        out = self.paper / "ara"

        compile_ara(self.paper, out)

        claims = (out / "logic" / "claims.md").read_text(encoding="utf-8")
        tree = yaml.safe_load(
            (out / "trace" / "exploration_tree.yaml").read_text(encoding="utf-8")
        )
        self.assertIn("## C01: X improves Y", claims)
        self.assertIn("**Proof**: [E01]", claims)
        self.assertEqual(tree["tree"][0]["id"], "N01")
        self.assertTrue(tree["tree"][0]["children"])

    def test_compile_refuses_to_overwrite(self):
        out = self.paper / "ara"
        compile_ara(self.paper, out)

        with self.assertRaisesRegex(ValueError, "已存在"):
            compile_ara(self.paper, out)

    def test_validator_reports_missing_file(self):
        out = self.paper / "ara"
        compile_ara(self.paper, out)
        (out / "logic" / "concepts.md").unlink()

        problems, _advisories = validate_ara(out)

        self.assertIn(
            "ara-missing-file",
            [problem.code for problem in problems],
        )


if __name__ == "__main__":
    unittest.main()
