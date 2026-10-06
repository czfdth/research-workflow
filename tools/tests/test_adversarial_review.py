"""The two adversarial review roles.

These tests pin the properties that make the roles worth having: a claim audit
must not be handed the author's derivations, the two kill-argument lines must be
independent calls, and no unresolved finding may be ignored.
"""

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa import adversarial_review as module


def _payload(*findings):
    return json.dumps(
        {
            "findings": [
                {
                    "kind": kind,
                    "statement": statement,
                    "evidence": evidence,
                }
                for kind, statement, evidence in findings
            ],
            "summary": "summary",
        }
    )


class AdversarialReviewTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper_root = Path(self._temporary.name)
        (self.paper_root / "manuscript" / "sections").mkdir(parents=True)
        (self.paper_root / "data").mkdir()
        (self.paper_root / "manuscript" / "main.tex").write_text(
            "43 works\n",
            encoding="utf-8",
        )
        (
            self.paper_root / "manuscript" / "sections" / "14-appendix-proofs.tex"
        ).write_text(
            "proof text\n",
            encoding="utf-8",
        )
        (self.paper_root / "data" / "matrix.csv").write_text(
            "key\n" + "\n".join(f"k{i}" for i in range(43)) + "\n",
            encoding="utf-8",
        )
        (self.paper_root / "ccfa.yaml").write_text(
            yaml.safe_dump(
                {
                    "target_venue": {"name": "NeurIPS", "mode": "conference"},
                    "stage": {"current": "internal-review"},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        self.codex_config = self.paper_root / "config.toml"
        self.codex_config.write_text(
            'model_provider = "deepseek-provider"\n'
            'model = "deepseek-v4-flash"\n'
            '[model_providers.deepseek-provider]\n'
            'base_url = "https://deepseek.example.test/v1"\n',
            encoding="utf-8",
        )

    def _runner(self, payloads):
        calls = []
        queue = list(payloads)

        def runner(argv, cwd, timeout, prompt):
            cwd_path = Path(cwd)
            calls.append(
                {
                    "argv": argv,
                    "cwd": cwd_path,
                    "prompt": prompt,
                    # Sampled while the reviewer runs: the staging tree is
                    # removed before run_review returns, so a check afterwards
                    # would always see it gone.
                    "staging_is_temp": cwd_path != self.paper_root.resolve(),
                    "excluded_present": (
                        cwd_path
                        / "manuscript"
                        / "sections"
                        / "14-appendix-proofs.tex"
                    ).exists(),
                    "kept_present": (
                        cwd_path / "manuscript" / "main.tex"
                    ).is_file()
                    and (cwd_path / "data" / "matrix.csv").is_file(),
                }
            )
            body = queue.pop(0)
            out_index = argv.index("-o") + 1
            Path(argv[out_index]).write_text(body, encoding="utf-8")
            return 0, ""

        return runner, calls

    def _paths(self):
        return [
            Path("manuscript/main.tex"),
            Path("manuscript/sections/14-appendix-proofs.tex"),
            Path("data/matrix.csv"),
        ]

    def test_claim_audit_excludes_the_authors_derivations(self):
        runner, calls = self._runner(
            [_payload(("mismatch", "43 is wrong", "key"))]
        )

        record = module.run_review(
            self.paper_root,
            role="claim-audit",
            model="gpt-5.6",
            stage="internal-review",
            paths=self._paths(),
            runner=runner,
            codex_config=self.codex_config,
        )

        self.assertIn(
            "manuscript/sections/14-appendix-proofs.tex",
            record["excluded_inputs"],
        )
        self.assertNotIn(
            "manuscript/sections/14-appendix-proofs.tex",
            record["inputs"],
        )
        # The excluded derivation is not merely unlisted: it is absent from the
        # working tree the reviewer is pointed at.
        self.assertTrue(calls[0]["staging_is_temp"])
        self.assertTrue(calls[0]["kept_present"])
        self.assertFalse(calls[0]["excluded_present"])

    def test_kill_argument_runs_two_independent_lines(self):
        runner, calls = self._runner(
            [
                _payload(("concern", "reject reason", "43")),
                _payload(("concern", "defence", "43")),
            ]
        )

        record = module.run_review(
            self.paper_root,
            role="kill-argument",
            model="gpt-5.6",
            stage="internal-review",
            paths=self._paths(),
            runner=runner,
            codex_config=self.codex_config,
        )

        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0]["prompt"], calls[1]["prompt"])
        self.assertNotIn("逐点辩护", calls[0]["prompt"])
        self.assertNotIn("拒稿备忘", calls[1]["prompt"])
        self.assertEqual(
            sorted(record["calls"]),
            ["defend", "reject"],
        )

    def test_unresolved_findings_are_problems(self):
        module.run_review(
            self.paper_root,
            role="claim-audit",
            model="gpt-5.6",
            stage="internal-review",
            paths=[Path("data/matrix.csv")],
            runner=self._runner([_payload(("mismatch", "43 is wrong", "key"))])[0],
            codex_config=self.codex_config,
        )

        problems, advisories = module.check(self.paper_root)

        self.assertEqual(advisories, [])
        self.assertIn(
            "adversarial-review-unresolved",
            [problem.code for problem in problems],
        )

    def test_a_resolved_finding_needs_a_real_resolution(self):
        record = module.run_review(
            self.paper_root,
            role="claim-audit",
            model="gpt-5.6",
            stage="internal-review",
            paths=[Path("data/matrix.csv")],
            runner=self._runner([_payload(("mismatch", "43 is wrong", "key"))])[0],
            codex_config=self.codex_config,
        )
        record["findings"][0]["resolved"] = True
        record["findings"][0]["resolution"] = "too short"
        (self.paper_root / module.ARTIFACT).write_text(
            json.dumps(record),
            encoding="utf-8",
        )

        problems, _advisories = module.check(self.paper_root)

        self.assertIn(
            "adversarial-review-resolution-thin",
            [problem.code for problem in problems],
        )

    def test_advisory_only_reviewer_is_flagged(self):
        record = module.run_review(
            self.paper_root,
            role="claim-audit",
            model="gpt-5.6",
            stage="internal-review",
            paths=[Path("data/matrix.csv")],
            runner=self._runner([_payload(("mismatch", "43 is wrong", "key"))])[0],
            codex_config=self.codex_config,
        )
        record["review_tier"] = "advisory-only"
        record["findings"] = []
        (self.paper_root / module.ARTIFACT).write_text(
            json.dumps(record),
            encoding="utf-8",
        )

        problems, _advisories = module.check(self.paper_root)

        self.assertIn(
            "adversarial-review-advisory-only",
            [problem.code for problem in problems],
        )

    def test_missing_artifact_is_an_advisory_not_a_problem(self):
        problems, advisories = module.check(self.paper_root)

        self.assertEqual(problems, [])
        self.assertIn(
            "adversarial-review-not-configured",
            [advisory.code for advisory in advisories],
        )


if __name__ == "__main__":
    unittest.main()
