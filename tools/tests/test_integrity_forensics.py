"""The pinned launcher for the repo ARIS's /integrity-forensics points at."""

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccfa import integrity_forensics as inf


def _stub(out_payload: dict) -> str:
    """A fake upstream tool: parse ``--out`` and write a fixed payload."""
    return (
        "import argparse, json\n"
        "p = argparse.ArgumentParser()\n"
        "for flag in ('--paper-id', '--ledger', '--out', '--observability-level',\n"
        "             '--taxonomy-version', '--coverage', '--generated-at'):\n"
        "    p.add_argument(flag)\n"
        "p.add_argument('--latex', nargs='*')\n"
        "p.add_argument('--findings', nargs='*')\n"
        "p.add_argument('--md')\n"
        "a = p.parse_args()\n"
        f"open(a.out, 'w', encoding='utf-8').write({json.dumps(json.dumps(out_payload))})\n"
    )


def _fake_checkout(root: Path, *, report: dict | None = None) -> tuple[Path, str]:
    """A git repo containing stub upstream tools; returns (dir, commit)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "tools").mkdir(exist_ok=True)
    payload = report or {
        "report_version": "1",
        "taxonomy_version": "0.5",
        "paper_id": "demo",
        "observability_level": 1,
        "overall_verdict": inf.VERDICT_CLEAN,
        "adjudicator": "deterministic-rules-v2",
        "findings": [],
        "counts": {"critical": 0, "major": 0, "minor": 0},
        "human_review_required": False,
    }
    for name in inf.PIPELINE:
        (root / "tools" / name).write_text(_stub(payload), encoding="utf-8")
    for argv in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.test"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "-A"],
        ["git", "commit", "-qm", "stub"],
    ):
        subprocess.run(argv, cwd=str(root), check=True, capture_output=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()
    return root, commit


def _report_payload(verdict: str, findings: list[dict] | None = None) -> dict:
    return {
        "report_version": "1",
        "taxonomy_version": "0.5",
        "paper_id": "demo",
        "observability_level": 1,
        "overall_verdict": verdict,
        "adjudicator": "deterministic-rules-v2",
        "findings": findings or [],
        "counts": {"critical": 0, "major": 0, "minor": 0},
        "human_review_required": bool(findings),
    }


class PinTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_explicit_checkout_wins(self):
        explicit = self.root / "explicit"

        self.assertEqual(inf.resolve_checkout(explicit), explicit)

    def test_env_var_is_used_when_explicit_is_absent(self):
        target = self.root / "from-env"
        with mock.patch.dict(
            os.environ, {"CCFA_ANTI_AUTORESEARCH": str(target)}, clear=False
        ):
            self.assertEqual(inf.resolve_checkout(None), target)

    def test_the_default_is_used_when_nothing_is_set(self):
        with mock.patch.dict(os.environ, {"CCFA_ANTI_AUTORESEARCH": ""}, clear=False):
            self.assertEqual(inf.resolve_checkout(None), inf.DEFAULT_CHECKOUT)

    def test_a_missing_checkout_fails_closed(self):
        problems, _advisories = inf.verify_checkout(self.root / "nope")

        self.assertEqual(
            [p.code for p in problems], ["integrity-forensics-not-installed"]
        )

    def test_a_non_git_directory_is_reported(self):
        target = self.root / "plain"
        target.mkdir()

        problems, _advisories = inf.verify_checkout(target)

        self.assertEqual(
            [p.code for p in problems], ["integrity-forensics-not-a-git-checkout"]
        )

    def test_a_pin_mismatch_fails_closed(self):
        checkout, commit = _fake_checkout(self.root / "co")

        problems, _advisories = inf.verify_checkout(
            checkout, pin="0" * 40
        )

        self.assertIn("integrity-forensics-pin-mismatch", [p.code for p in problems])
        self.assertEqual(commit, inf.checkout_commit(checkout))

    def test_a_checkout_missing_tools_is_reported(self):
        checkout, commit = _fake_checkout(self.root / "co")
        (checkout / "tools" / "check_stat_consistency.py").unlink()

        problems, _advisories = inf.verify_checkout(checkout, pin=commit)

        self.assertIn("integrity-forensics-incomplete", [p.code for p in problems])

    def test_a_checkout_at_the_pin_passes(self):
        checkout, commit = _fake_checkout(self.root / "co")

        problems, advisories = inf.verify_checkout(checkout, pin=commit)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])


class ObligationTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _finding(self, pattern: str = "A1", severity: str = "critical") -> dict:
        return {
            "id": pattern,
            "pattern_id": pattern,
            "family": "A",
            "severity": severity,
            "summary": f"issue {pattern}",
        }

    def test_fingerprints_are_stable_for_the_same_finding(self):
        first = inf._fingerprint(self._finding())
        second = inf._fingerprint(dict(self._finding()))

        self.assertEqual(first, second)

    def test_a_new_finding_becomes_an_open_obligation(self):
        report = inf.normalise_report(
            _report_payload(inf.VERDICT_HARD, [self._finding()]),
            checkout=Path("co"),
            pin="a" * 40,
        )

        appended, open_items = inf.update_obligations(self.root, report)

        self.assertEqual(len(appended), 1)
        self.assertEqual(appended[0]["kind"], "open")
        self.assertEqual(len(open_items), 1)

    def test_an_unchanged_finding_is_not_reopened(self):
        report = inf.normalise_report(
            _report_payload(inf.VERDICT_HARD, [self._finding()]),
            checkout=Path("co"),
            pin="a" * 40,
        )
        inf.update_obligations(self.root, report)

        appended, open_items = inf.update_obligations(self.root, report)

        self.assertEqual(appended, [])
        self.assertEqual(len(open_items), 1)

    def test_a_vanished_finding_is_never_auto_closed(self):
        hard = inf.normalise_report(
            _report_payload(inf.VERDICT_HARD, [self._finding()]),
            checkout=Path("co"),
            pin="a" * 40,
        )
        inf.update_obligations(self.root, hard)
        clean = inf.normalise_report(
            _report_payload(inf.VERDICT_CLEAN, []),
            checkout=Path("co"),
            pin="a" * 40,
        )

        appended, open_items = inf.update_obligations(self.root, clean)

        self.assertEqual([entry["kind"] for entry in appended], [
            "unresolved-disappearance"
        ])
        self.assertEqual(open_items[0]["status"], "unresolved-disappearance")

    def test_resolve_needs_evidence_and_records_its_hash(self):
        report = inf.normalise_report(
            _report_payload(inf.VERDICT_HARD, [self._finding()]),
            checkout=Path("co"),
            pin="a" * 40,
        )
        _appended, open_items = inf.update_obligations(self.root, report)
        fingerprint = open_items[0]["fingerprint"]
        evidence = self.root / "fix.txt"
        evidence.write_text("fixed the number\n", encoding="utf-8")

        entry = inf.close_obligation(
            self.root,
            fingerprint,
            kind="resolve",
            by="reviewer",
            detail="recomputed from tables/matrix-stats.json",
            evidence_path=evidence,
        )

        self.assertTrue(entry["evidence_sha256"].startswith("sha256:"))
        state = inf.obligation_state(
            inf.load_obligations(self.root / inf.OBLIGATIONS_RELATIVE)
        )
        self.assertEqual(state[fingerprint]["status"], "resolved")

    def test_resolve_without_evidence_is_refused(self):
        report = inf.normalise_report(
            _report_payload(inf.VERDICT_HARD, [self._finding()]),
            checkout=Path("co"),
            pin="a" * 40,
        )
        _appended, open_items = inf.update_obligations(self.root, report)

        with self.assertRaisesRegex(ValueError, "evidence"):
            inf.close_obligation(
                self.root,
                open_items[0]["fingerprint"],
                kind="resolve",
                by="reviewer",
                detail="trust me",
                evidence_path=self.root / "missing.txt",
            )

    def test_a_waiver_is_recorded_separately_from_a_resolution(self):
        report = inf.normalise_report(
            _report_payload(inf.VERDICT_HARD, [self._finding()]),
            checkout=Path("co"),
            pin="a" * 40,
        )
        _appended, open_items = inf.update_obligations(self.root, report)
        fingerprint = open_items[0]["fingerprint"]

        inf.close_obligation(
            self.root,
            fingerprint,
            kind="waive",
            by="pi",
            detail="known rounding convention, accepted for submission",
        )

        state = inf.obligation_state(
            inf.load_obligations(self.root / inf.OBLIGATIONS_RELATIVE)
        )
        self.assertEqual(state[fingerprint]["status"], "waived")
        self.assertNotIn("resolution", state[fingerprint])

    def test_an_unknown_fingerprint_is_refused(self):
        with self.assertRaisesRegex(ValueError, "没有这个 obligation"):
            inf.close_obligation(
                self.root,
                "deadbeef",
                kind="waive",
                by="pi",
                detail="whatever",
            )


class GateTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _write_report(self, report: dict) -> None:
        path = self.root / inf.REPORT_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    def _normalised(self, verdict: str, findings: list[dict] | None = None) -> dict:
        return inf.normalise_report(
            _report_payload(verdict, findings),
            checkout=Path("co"),
            pin="a" * 40,
        )

    def test_a_missing_report_is_only_an_advisory(self):
        problems, advisories = inf.check(self.root)

        self.assertEqual(problems, [])
        self.assertEqual([a.code for a in advisories], ["integrity-forensics-not-run"])

    def test_hard_flags_block(self):
        self._write_report(self._normalised(inf.VERDICT_HARD))

        problems, _advisories = inf.check(self.root)

        self.assertIn("integrity-forensics-blocking", [p.code for p in problems])

    def test_review_unavailable_blocks(self):
        # An incomplete sweep must never be read as a pass.
        self._write_report(self._normalised(inf.VERDICT_UNAVAILABLE))

        problems, _advisories = inf.check(self.root)

        self.assertIn("integrity-forensics-blocking", [p.code for p in problems])

    def test_soft_flags_warn(self):
        self._write_report(self._normalised(inf.VERDICT_SOFT))

        problems, advisories = inf.check(self.root)

        self.assertEqual(problems, [])
        self.assertIn("integrity-forensics-soft", [a.code for a in advisories])

    def test_clean_given_evidence_passes_silently(self):
        self._write_report(self._normalised(inf.VERDICT_CLEAN))

        problems, advisories = inf.check(self.root)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_an_unknown_verdict_is_a_problem(self):
        self._write_report(self._normalised("HONEST"))

        problems, _advisories = inf.check(self.root)

        self.assertIn("integrity-forensics-invalid", [p.code for p in problems])

    def test_an_open_critical_obligation_blocks(self):
        report = self._normalised(
            inf.VERDICT_HARD,
            [
                {
                    "id": "A1",
                    "pattern_id": "A1",
                    "family": "A",
                    "severity": "critical",
                    "summary": "delta does not add up",
                }
            ],
        )
        self._write_report(report)
        inf.update_obligations(self.root, report)

        problems, _advisories = inf.check(self.root)

        self.assertIn("integrity-forensics-obligation", [p.code for p in problems])

    def test_an_open_minor_obligation_is_only_an_advisory(self):
        report = self._normalised(
            inf.VERDICT_SOFT,
            [
                {
                    "id": "F1",
                    "pattern_id": "F1",
                    "family": "F",
                    "severity": "minor",
                    "summary": "layout signal",
                }
            ],
        )
        self._write_report(report)
        inf.update_obligations(self.root, report)

        problems, advisories = inf.check(self.root)

        self.assertEqual(problems, [])
        self.assertIn("integrity-forensics-obligation", [a.code for a in advisories])

    def test_a_resolved_obligation_stops_blocking(self):
        report = self._normalised(
            inf.VERDICT_HARD,
            [
                {
                    "id": "A1",
                    "pattern_id": "A1",
                    "family": "A",
                    "severity": "critical",
                    "summary": "delta does not add up",
                }
            ],
        )
        self._write_report(report)
        _appended, open_items = inf.update_obligations(self.root, report)
        evidence = self.root / "fix.txt"
        evidence.write_text("recomputed\n", encoding="utf-8")
        inf.close_obligation(
            self.root,
            open_items[0]["fingerprint"],
            kind="resolve",
            by="reviewer",
            detail="recomputed from source",
            evidence_path=evidence,
        )

        problems, _advisories = inf.check(self.root)

        # The verdict itself is still HARD_FLAGS: closing the obligation is a
        # human act recorded next to it, not a rewrite of the upstream verdict.
        codes = [p.code for p in problems]
        self.assertIn("integrity-forensics-blocking", codes)
        self.assertNotIn("integrity-forensics-obligation", codes)

    def test_input_hashes_cover_every_manuscript_source(self):
        (self.root / "manuscript").mkdir(parents=True, exist_ok=True)
        (self.root / "manuscript" / "main.tex").write_text("a\n", encoding="utf-8")
        (self.root / "manuscript" / "extra.tex").write_text("b\n", encoding="utf-8")

        hashes = inf.input_hashes(self.root)

        self.assertEqual(
            sorted(hashes), ["manuscript/extra.tex", "manuscript/main.tex"]
        )
        self.assertTrue(all(v.startswith("sha256:") for v in hashes.values()))

    def test_a_manuscript_changed_after_the_sweep_is_stale(self):
        (self.root / "manuscript").mkdir(parents=True, exist_ok=True)
        main = self.root / "manuscript" / "main.tex"
        main.write_text("we report 43 works\n", encoding="utf-8")
        report = self._normalised(inf.VERDICT_CLEAN)
        report["input_hashes"] = inf.input_hashes(self.root)
        self._write_report(report)
        main.write_text("we report 44 works\n", encoding="utf-8")

        problems, _advisories = inf.check(self.root)

        self.assertIn("integrity-forensics-stale", [p.code for p in problems])

    def test_an_unchanged_manuscript_is_not_stale(self):
        (self.root / "manuscript").mkdir(parents=True, exist_ok=True)
        (self.root / "manuscript" / "main.tex").write_text(
            "we report 43 works\n", encoding="utf-8"
        )
        report = self._normalised(inf.VERDICT_CLEAN)
        report["input_hashes"] = inf.input_hashes(self.root)
        self._write_report(report)

        problems, advisories = inf.check(self.root)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])


class SweepTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.paper = self.root / "paper"
        (self.paper / "manuscript").mkdir(parents=True)
        (self.paper / "manuscript" / "main.tex").write_text(
            "\\documentclass{article}\nWe report 43 works.\n", encoding="utf-8"
        )

    def test_the_sweep_drives_the_upstream_chain(self):
        checkout, commit = _fake_checkout(self.root / "co")
        with mock.patch.object(inf, "PIN_COMMIT", commit):
            report = inf.run_sweep(self.paper, checkout, paper_id="demo")

        self.assertEqual(report["overall_verdict"], inf.VERDICT_CLEAN)

    def test_a_paper_without_a_manuscript_is_an_error(self):
        checkout, _commit = _fake_checkout(self.root / "co")
        empty = self.root / "empty"
        empty.mkdir()

        with self.assertRaisesRegex(ValueError, "manuscript"):
            inf.run_sweep(empty, checkout, paper_id="demo")

    def test_a_failing_upstream_tool_is_reported(self):
        checkout, _commit = _fake_checkout(self.root / "co")
        (checkout / "tools" / "check_numeric_consistency.py").write_text(
            "import sys\nsys.exit(3)\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(ValueError, "check_numeric_consistency"):
            inf.run_sweep(self.paper, checkout, paper_id="demo")


class CliTests(unittest.TestCase):
    def _run(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            io.StringIO()
        ):
            code = inf.main(["integrity-forensics", *argv])
        return code, stdout.getvalue()

    def test_pin_reports_the_constant_and_the_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout, commit = _fake_checkout(Path(tmp) / "co")

            code, output = self._run(["pin", "--checkout", str(checkout)])

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["commit"], inf.PIN_COMMIT)
        self.assertEqual(payload["head"], commit)
        self.assertFalse(payload["at_pin"])

    def test_check_returns_zero_when_there_is_no_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _output = self._run(["check", "--paper-root", tmp])

        self.assertEqual(code, 0)

    def test_obligations_prints_the_folded_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = inf.normalise_report(
                _report_payload(
                    inf.VERDICT_HARD,
                    [
                        {
                            "id": "A1",
                            "pattern_id": "A1",
                            "family": "A",
                            "severity": "critical",
                            "summary": "x",
                        }
                    ],
                ),
                checkout=Path("co"),
                pin="a" * 40,
            )
            inf.update_obligations(root, report)

            code, output = self._run(["obligations", "--paper-root", tmp])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)[0]["status"], "open")


if __name__ == "__main__":
    unittest.main()
