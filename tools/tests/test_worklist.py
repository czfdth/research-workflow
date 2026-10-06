"""The ordered human worklist (a read-only view over existing records)."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccfa import worklist


def _checkpoint(checkpoint_id, stage):
    ledgers = {
        "proof": "data/proof-audit.yaml",
        "citation-support": "data/citation-support.yaml",
        "figure-support": "data/figure-support.yaml",
        "claim-candidates": "data/claim-candidates.yaml",
        "research-plans": "data/research-plan-candidates.yaml",
    }
    return {
        "id": checkpoint_id,
        "type": "approve",
        "stage": stage,
        "question": f"judge {checkpoint_id}?",
        "ledger": ledgers.get(checkpoint_id),
    }


REPORT = {
    "ready": False,
    "blocking": [
        "argument-audit gate failed: proof-review-not-verified, citation-support-missing",
        "cross-review gate failed: review-blocking",
    ],
    "stage": {"current": "internal-review", "gate": "review_cleared"},
    "deadline": {"deadline": "2026-10-15", "days_left": 9},
    "human_review": {
        "checkpoints": [
            _checkpoint("research-plans", "idea"),
            _checkpoint("figure-support", "writing"),
            _checkpoint("cross-review", "internal-review"),
            _checkpoint("proof", "internal-review"),
            _checkpoint("claim-candidates", "idea"),
            _checkpoint("citation-support", "writing"),
        ]
    },
    "gate_results": [
        {
            "name": "argument-audit",
            "problems": [
                {"code": "proof-review-not-verified"},
                {"code": "citation-support-missing"},
                {"code": "figure-support-missing"},
            ],
            "advisories": [
                {"code": "proof-audit-coverage", "message": "人工证明复核 0/8"}
            ],
        },
        {
            "name": "cross-review",
            "problems": [{"code": "review-blocking"}],
            "advisories": [],
        },
    ],
}


class PacketTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        directory = self.root / worklist.HUMAN_REVIEW_DIR
        directory.mkdir(parents=True)
        (directory / "README.md").write_text("# human review\n", encoding="utf-8")
        (directory / "citation-support-packet.md").write_text("c\n", encoding="utf-8")
        (directory / "figure-support-packet.md").write_text("f\n", encoding="utf-8")
        (directory / "proof-review-packet.md").write_text("p\n", encoding="utf-8")

    def test_every_token_must_match(self):
        # "support" alone would otherwise pull the figure packet into the
        # citation task.
        citation = worklist._packets(self.root, "citation-support")
        figure = worklist._packets(self.root, "figure-support")

        self.assertEqual(
            citation, ["ccfa-workfiles/human-review/citation-support-packet.md"]
        )
        self.assertEqual(
            figure, ["ccfa-workfiles/human-review/figure-support-packet.md"]
        )

    def test_a_single_token_checkpoint_matches_its_packet(self):
        self.assertEqual(
            worklist._packets(self.root, "proof"),
            ["ccfa-workfiles/human-review/proof-review-packet.md"],
        )

    def test_a_checkpoint_without_a_packet_returns_nothing(self):
        self.assertEqual(worklist._packets(self.root, "cross-review"), [])

    def test_readme_is_never_treated_as_a_packet(self):
        self.assertNotIn(
            "ccfa-workfiles/human-review/README.md",
            worklist._packets(self.root, "proof"),
        )


class RankingTests(unittest.TestCase):
    def test_problem_order_supplies_the_ranks(self):
        ranks = worklist._problem_rank(Path("."), REPORT)

        self.assertEqual(ranks["proof"], 0)
        self.assertEqual(ranks["citation-support"], 1)
        self.assertEqual(ranks["figure-support"], 2)
        self.assertNotIn("cross-review", ranks)


class CollectTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        directory = self.root / worklist.HUMAN_REVIEW_DIR
        directory.mkdir(parents=True)
        (directory / "proof-review-packet.md").write_text("p\n", encoding="utf-8")

    def _collect(self) -> dict:
        with mock.patch.object(worklist, "build_report", return_value=REPORT):
            return worklist.collect(self.root)

    def test_blocking_items_come_first_in_the_workflows_own_order(self):
        payload = self._collect()

        self.assertEqual(
            [item["id"] for item in payload["items"]],
            [
                "proof",
                "citation-support",
                "figure-support",
                "cross-review",
                "claim-candidates",
                "research-plans",
            ],
        )
        self.assertEqual(
            [item["order"] for item in payload["items"]], [1, 2, 3, 4, 5, 6]
        )

    def test_only_implicated_items_are_marked_as_blocking(self):
        payload = self._collect()
        marked = [
            item["id"] for item in payload["items"] if item["implicated_by_blocking"]
        ]

        self.assertEqual(
            marked, ["proof", "citation-support", "figure-support", "cross-review"]
        )

    def test_progress_is_read_from_the_gate_advisories(self):
        payload = self._collect()
        proof = next(item for item in payload["items"] if item["id"] == "proof")

        self.assertEqual(proof["progress"], "人工证明复核 0/8")

    def test_a_checkpoint_without_a_ledger_falls_back_to_its_artifact(self):
        payload = self._collect()
        cross = next(
            item for item in payload["items"] if item["id"] == "cross-review"
        )

        self.assertEqual(cross["write_into"], "reviews/cross-review.json")

    def test_finished_criteria_come_with_the_checker_that_enforces_them(self):
        payload = self._collect()
        proof = next(item for item in payload["items"] if item["id"] == "proof")

        self.assertIn("reviewer", proof["finished_when"])
        self.assertEqual(proof["checked_by"], "tools/ccfa/argument_audit.py")

    def test_the_payload_never_claims_more_than_the_records_say(self):
        payload = self._collect()

        self.assertFalse(payload["ready"])
        self.assertEqual(payload["pending_count"], 6)
        self.assertEqual(payload["open_integrity_obligations"], 0)


class RenderTests(unittest.TestCase):
    def test_markdown_lists_each_item_with_its_targets(self):
        with mock.patch.object(worklist, "build_report", return_value=REPORT):
            payload = worklist.collect(Path("."))

        text = worklist.render_markdown(payload)

        self.assertIn("## 1. `proof` **[阻塞]**", text)
        self.assertIn("写进：`data/proof-audit.yaml`", text)
        self.assertIn("谁校验：`tools/ccfa/argument_audit.py`", text)
        self.assertIn("只是**视图**", text)
        self.assertIn("不证明任何结论正确", text)

    def test_markdown_does_not_mark_a_blocking_item_as_done(self):
        with mock.patch.object(worklist, "build_report", return_value=REPORT):
            payload = worklist.collect(Path("."))

        text = worklist.render_markdown(payload)

        # The criteria quote the checker's vocabulary (which includes the word
        # "verified"), so assert on completion claims instead.
        self.assertNotIn("已完成", text)
        self.assertNotIn("✅", text)
        self.assertIn("仍然需要真人签字", text)


class CliTests(unittest.TestCase):
    def _run(self, argv, payload=None):
        stdout = io.StringIO()
        patcher = mock.patch.object(worklist, "build_report", return_value=REPORT)
        with patcher, contextlib.redirect_stdout(stdout):
            code = worklist.main(["worklist", *argv])
        return code, stdout.getvalue()

    def test_json_output_is_the_full_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self._run(["--paper-root", tmp, "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["pending_count"], 6)

    def test_next_prints_only_the_first_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, output = self._run(["--paper-root", tmp, "--next"])

        self.assertEqual(code, 0)
        item = json.loads(output)
        self.assertEqual(item["id"], "proof")
        self.assertTrue(item["implicated_by_blocking"])

    def test_out_writes_the_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "worklist.md"
            code, _output = self._run(
                ["--paper-root", tmp, "--out", str(target)]
            )
            text = target.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertIn("人工待办", text)


if __name__ == "__main__":
    unittest.main()
