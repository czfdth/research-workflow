"""Tests for :mod:`ccfa.experiment_audit`."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa import experiment_audit

RUN_ID = "20261005T101010-01"


def _root(tmp: str) -> Path:
    root = Path(tmp)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "experiments" / "log").mkdir(parents=True, exist_ok=True)
    (root / "tables").mkdir(parents=True, exist_ok=True)
    (root / "tables" / "t1.tex").write_text("table body\n", encoding="utf-8")
    return root


def _run_log(root: Path, run_id: str = RUN_ID, **overrides) -> None:
    payload = {
        "run_id": run_id,
        "declared_purpose": "experiment",
        "started_at": "2026-10-05T10:10:10Z",
        "finished_at": "2026-10-05T10:20:10Z",
        "status": "completed",
        "exit_code": 0,
        "git_dirty": False,
    }
    payload.update(overrides)
    (root / "experiments" / "log" / f"{run_id}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _entry(**overrides) -> dict:
    entry = {
        "id": "e-main",
        "run_ids": [RUN_ID],
        "ground_truth": {
            "source": "dataset",
            "producer": "ragbench-v2",
            "verified_by": "none",
        },
        "evaluation": {
            "systems": ["target-llm"],
            "datasets": ["ragbench-v2"],
            "seeds": [1, 2, 3],
        },
        "metrics": [
            {
                "name": "attack-success-rate",
                "normalization": "none",
                "fit_on": "none",
                "selection": "single",
                "selection_on": "none",
            }
        ],
        "results": [
            {
                "id": "r-asr",
                "artifact": "tables/t1.tex",
                "run_ids": [RUN_ID],
            }
        ],
        "limits": "只覆盖英文单跳检索问答；不声称跨语言或长文档泛化。",
    }
    entry.update(overrides)
    return entry


def _audit(root: Path, entries: list[dict] | None = None) -> None:
    payload = {"version": 1, "experiments": entries if entries is not None else [_entry()]}
    (root / "data" / "experiment-audit.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


class ExperimentAuditTests(unittest.TestCase):
    def test_a_clean_audit_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(root)

            problems, advisories = experiment_audit.check(root)

            self.assertEqual(problems, [])
            self.assertEqual(advisories, [])

    def test_a_missing_ledger_is_advisory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)

            problems, advisories = experiment_audit.check(root)

            self.assertEqual(problems, [])
            self.assertEqual(
                [item.code for item in advisories],
                ["experiment-audit-missing"],
            )

    def test_ground_truth_generated_by_the_system_under_test_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(
                root,
                [
                    _entry(
                        ground_truth={
                            "source": "model",
                            "producer": "target-llm",
                            "verified_by": "human",
                            "n_reviewed": 30,
                            "agreement": 0.9,
                        }
                    )
                ],
            )

            problems, _advisories = experiment_audit.check(root)

            self.assertIn(
                "experiment-audit-ground-truth-self-generated",
                {item.code for item in problems},
            )

    def test_model_labels_without_a_human_spot_check_are_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(
                root,
                [
                    _entry(
                        ground_truth={
                            "source": "model",
                            "producer": "gpt-5.6",
                            "verified_by": "none",
                        }
                    )
                ],
            )

            problems, _advisories = experiment_audit.check(root)

            self.assertIn(
                "experiment-audit-ground-truth-unverified",
                {item.code for item in problems},
            )

    def test_a_thin_human_spot_check_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(
                root,
                [
                    _entry(
                        ground_truth={
                            "source": "model",
                            "producer": "gpt-5.6",
                            "verified_by": "human",
                            "n_reviewed": 5,
                            "agreement": 0.6,
                        }
                    )
                ],
            )

            problems, _advisories = experiment_audit.check(root)

            self.assertIn(
                "experiment-audit-ground-truth-weak-verification",
                {item.code for item in problems},
            )

    def test_a_second_model_review_is_an_advisory_not_an_acquittal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(
                root,
                [
                    _entry(
                        ground_truth={
                            "source": "model",
                            "producer": "gpt-5.6",
                            "verified_by": "second-model",
                            "n_reviewed": 30,
                            "agreement": 0.9,
                        }
                    )
                ],
            )

            problems, advisories = experiment_audit.check(root)

            self.assertEqual(problems, [])
            self.assertIn(
                "experiment-audit-ground-truth-model-verified",
                {item.code for item in advisories},
            )

    def test_normalisation_fitted_on_test_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(
                root,
                [
                    _entry(
                        metrics=[
                            {
                                "name": "attack-success-rate",
                                "normalization": "z-score",
                                "fit_on": "test",
                                "selection": "single",
                                "selection_on": "none",
                            }
                        ]
                    )
                ],
            )

            problems, _advisories = experiment_audit.check(root)

            self.assertIn(
                "experiment-audit-normalization-leak",
                {item.code for item in problems},
            )

    def test_best_of_n_selected_on_test_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(
                root,
                [
                    _entry(
                        metrics=[
                            {
                                "name": "attack-success-rate",
                                "normalization": "none",
                                "fit_on": "none",
                                "selection": "best-of-n",
                                "selection_on": "test",
                            }
                        ]
                    )
                ],
            )

            problems, _advisories = experiment_audit.check(root)

            self.assertIn(
                "experiment-audit-selection-leak",
                {item.code for item in problems},
            )

    def test_selection_without_a_declared_split_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(
                root,
                [
                    _entry(
                        metrics=[
                            {
                                "name": "attack-success-rate",
                                "normalization": "none",
                                "fit_on": "none",
                                "selection": "threshold",
                                "selection_on": "none",
                            }
                        ]
                    )
                ],
            )

            problems, _advisories = experiment_audit.check(root)

            self.assertIn(
                "experiment-audit-selection-undeclared",
                {item.code for item in problems},
            )

    def test_a_result_pointing_at_a_missing_artifact_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(
                root,
                [
                    _entry(
                        results=[
                            {
                                "id": "r-asr",
                                "artifact": "tables/never-written.tex",
                                "run_ids": [RUN_ID],
                            }
                        ]
                    )
                ],
            )

            problems, _advisories = experiment_audit.check(root)

            self.assertIn(
                "experiment-audit-result-artifact-missing",
                {item.code for item in problems},
            )

    def test_results_bound_to_missing_failed_or_build_runs_are_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root, "20261005T101010-02", status="failed", exit_code=1)
            _run_log(root, "20261005T101010-03", declared_purpose="build")
            _audit(
                root,
                [
                    _entry(
                        run_ids=[
                            "20261005T101010-99",
                            "20261005T101010-02",
                            "20261005T101010-03",
                        ],
                        results=[],
                    )
                ],
            )

            problems, _advisories = experiment_audit.check(root)

            codes = {item.code for item in problems}
            self.assertIn("experiment-audit-run-missing", codes)
            self.assertIn("experiment-audit-run-failed", codes)
            self.assertIn("experiment-audit-run-is-build", codes)

    def test_a_dirty_run_without_a_waiver_is_an_advisory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root, git_dirty=True)
            _audit(root)

            problems, advisories = experiment_audit.check(root)

            self.assertEqual(problems, [])
            self.assertIn(
                "experiment-audit-run-dirty",
                {item.code for item in advisories},
            )

    def test_missing_limits_is_a_scope_inflation_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(root, [_entry(limits="")])

            problems, _advisories = experiment_audit.check(root)

            self.assertIn(
                "experiment-audit-limits-missing",
                {item.code for item in problems},
            )

    def test_a_single_seed_is_an_advisory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(
                root,
                [_entry(evaluation={"systems": ["target-llm"], "datasets": ["d"], "seeds": [1]})],
            )

            problems, advisories = experiment_audit.check(root)

            self.assertEqual(problems, [])
            self.assertIn(
                "experiment-audit-few-seeds",
                {item.code for item in advisories},
            )

    def test_an_unknown_claim_id_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            (root / "data" / "claim-registry.yaml").write_text(
                yaml.safe_dump(
                    {"claims": [{"id": "c-known"}]},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            _audit(
                root,
                [
                    _entry(
                        results=[
                            {
                                "id": "r-asr",
                                "artifact": "tables/t1.tex",
                                "run_ids": [RUN_ID],
                                "claims": ["c-ghost"],
                            }
                        ]
                    )
                ],
            )

            problems, _advisories = experiment_audit.check(root)

            self.assertIn(
                "experiment-audit-claim-unknown",
                {item.code for item in problems},
            )

    def test_an_entry_without_metrics_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(root, [_entry(metrics=[])])

            problems, _advisories = experiment_audit.check(root)

            self.assertIn(
                "experiment-audit-entry-invalid",
                {item.code for item in problems},
            )


class CliTests(unittest.TestCase):
    def test_check_reports_problems_with_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _root(tmp)
            _run_log(root)
            _audit(root, [_entry(limits="")])

            code = experiment_audit.main(
                ["ccfa experiment-audit", "check", "--paper-root", tmp]
            )

            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
