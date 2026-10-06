"""The one-command entry point (a read-only composition of three views)."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ccfa import quickstart
from ccfa.cli import Problem


def _doctor(problems=(), advisories=()):
    return (
        list(problems),
        list(advisories),
        ["installed    git", "reachable    docker       daemon 可达"],
    )


def _paper_row(name="demo", ready=False, blocking=("gate x failed",)):
    return {
        "paper": name,
        "title": name,
        "profile": "standard",
        "stage": "internal-review",
        "gate": "review_cleared",
        "ready": ready,
        "blocking_count": len(blocking),
        "blocking": list(blocking),
        "next_action": blocking[0] if blocking else "ready",
        "human_review": "pending-human-review" if not ready else "complete",
        "human_pending": [] if ready else ["proof"],
    }


def _summary(rows):
    return {
        "paper_count": len(rows),
        "ready_count": sum(1 for row in rows if row["ready"]),
        "blocked_count": sum(1 for row in rows if not row["ready"]),
        "human_pending_count": sum(1 for row in rows if row["human_pending"]),
        "dirty_count": 0,
        "missing_remote_count": 0,
        "papers": rows,
    }


class CollectTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.papers = self.root / "papers"
        (self.papers / "demo").mkdir(parents=True)
        (self.papers / "demo" / "ccfa.yaml").write_text("version: 1\n", encoding="utf-8")

    def _collect(self, *, rows=None, doctor_result=None, worklist_result=None):
        rows = rows if rows is not None else [_paper_row()]
        doctor_result = doctor_result or _doctor()
        worklist_result = worklist_result or {"items": []}
        with mock.patch.object(
            quickstart.doctor, "check_environment", return_value=doctor_result
        ), mock.patch.object(
            quickstart.dashboard, "collect_reports", return_value=[{}]
        ), mock.patch.object(
            quickstart.dashboard, "summarize", return_value=_summary(rows)
        ), mock.patch.object(
            quickstart.worklist, "collect", return_value=worklist_result
        ):
            return quickstart.collect(self.root, papers_root=self.papers)

    def test_environment_counts_are_reported(self):
        payload = self._collect(
            doctor_result=_doctor(
                problems=[Problem("p1", "x", None, "broken")],
                advisories=[Problem("a1", "x", None, "note")],
            )
        )

        self.assertEqual(payload["environment"]["problem_count"], 1)
        self.assertEqual(payload["environment"]["advisory_count"], 1)
        self.assertEqual(payload["environment"]["problems"][0]["code"], "p1")

    def test_only_informative_service_lines_are_kept(self):
        payload = self._collect()

        self.assertEqual(
            payload["environment"]["service_status"],
            ["reachable    docker       daemon 可达"],
        )

    def test_paper_counts_come_from_the_dashboard_summary(self):
        payload = self._collect(
            rows=[_paper_row("a"), _paper_row("b", ready=True, blocking=())]
        )

        summary = payload["papers"]["summary"]
        self.assertEqual(summary["paper_count"], 2)
        self.assertEqual(summary["ready_count"], 1)
        self.assertEqual(summary["blocked_count"], 1)

    def test_the_focus_paper_is_the_first_blocked_one(self):
        payload = self._collect(
            rows=[_paper_row("demo"), _paper_row("other", ready=True, blocking=())]
        )

        self.assertEqual(payload["focus"], str(self.papers / "demo"))

    def test_an_explicit_paper_root_wins(self):
        explicit = self.root / "somewhere"
        explicit.mkdir()
        (explicit / "ccfa.yaml").write_text("version: 1\n", encoding="utf-8")

        with mock.patch.object(
            quickstart.doctor, "check_environment", return_value=_doctor()
        ), mock.patch.object(
            quickstart.dashboard, "collect_reports", return_value=[{}]
        ), mock.patch.object(
            quickstart.dashboard, "summarize", return_value=_summary([])
        ), mock.patch.object(
            quickstart.worklist, "collect", return_value={"items": []}
        ):
            payload = quickstart.collect(
                self.root, papers_root=self.papers, paper_root=explicit
            )

        self.assertEqual(payload["focus"], str(explicit))

    def test_the_first_worklist_item_becomes_the_next_action(self):
        item = {"id": "proof", "order": 1, "implicated_by_blocking": True}

        payload = self._collect(worklist_result={"items": [item]})

        self.assertEqual(payload["next_action"]["id"], "proof")

    def test_no_worklist_items_means_no_next_action(self):
        payload = self._collect(worklist_result={"items": []})

        self.assertIsNone(payload["next_action"])

    def test_a_missing_papers_root_is_reported_not_raised(self):
        with mock.patch.object(
            quickstart.doctor, "check_environment", return_value=_doctor()
        ):
            payload = quickstart.collect(
                self.root, papers_root=self.root / "nope"
            )

        self.assertEqual(payload["papers"]["summary"]["paper_count"], 0)
        self.assertTrue(payload["papers"]["missing_root"])
        self.assertIsNone(payload["next_action"])

    def test_a_worklist_failure_does_not_take_down_the_brief(self):
        with mock.patch.object(
            quickstart.doctor, "check_environment", return_value=_doctor()
        ), mock.patch.object(
            quickstart.dashboard, "collect_reports", return_value=[{}]
        ), mock.patch.object(
            quickstart.dashboard, "summarize", return_value=_summary([_paper_row()])
        ), mock.patch.object(
            quickstart.worklist,
            "collect",
            side_effect=ValueError("worklist exploded"),
        ):
            payload = quickstart.collect(self.root, papers_root=self.papers)

        self.assertIsNone(payload["next_action"])
        self.assertEqual(payload["papers"]["summary"]["paper_count"], 1)


class RenderTests(unittest.TestCase):
    def _payload(self):
        return {
            "schema_version": 1,
            "repo_root": ".",
            "environment": {
                "problems": [],
                "advisories": [],
                "problem_count": 0,
                "advisory_count": 0,
                "service_status": [],
            },
            "papers": {
                "papers": [
                    {
                        "paper": "demo",
                        "title": "demo",
                        "stage": "internal-review",
                        "gate": "review_cleared",
                        "ready": False,
                        "blocking_count": 2,
                        "human_review": "pending-human-review",
                    }
                ],
                "summary": {
                    "paper_count": 1,
                    "ready_count": 0,
                    "blocked_count": 1,
                    "human_pending_count": 1,
                    "dirty_count": 0,
                },
                "missing_root": None,
            },
            "focus": "papers/demo",
            "next_action": {
                "id": "proof",
                "question": "逐行成立吗？",
                "progress": "人工证明复核 0/8",
                "read_first": ["ccfa-workfiles/human-review/proof-review-packet.md"],
                "write_into": "data/proof-audit.yaml",
                "finished_when": "status=verified 且写 audited_inputs",
                "checked_by": "tools/ccfa/argument_audit.py",
                "implicated_by_blocking": True,
            },
        }

    def test_markdown_shows_environment_papers_and_the_one_next_action(self):
        text = quickstart.render_markdown(self._payload())

        self.assertIn("doctor: 0 problems, 0 advisories", text)
        self.assertIn("共 1 篇", text)
        self.assertIn("### `proof` **[阻塞]**", text)
        self.assertIn("先读：`ccfa-workfiles/human-review/proof-review-packet.md`", text)
        self.assertIn("谁校验：`tools/ccfa/argument_audit.py`", text)

    def test_markdown_states_the_boundary(self):
        text = quickstart.render_markdown(self._payload())

        self.assertIn("只做汇总", text)
        self.assertIn("人工复核只能由人签字", text)

    def test_markdown_renders_without_a_next_action(self):
        payload = self._payload()
        payload["next_action"] = None

        text = quickstart.render_markdown(payload)

        self.assertIn("没有待办项", text)

    def test_markdown_renders_without_a_papers_root(self):
        payload = self._payload()
        payload["papers"]["missing_root"] = "papers"

        text = quickstart.render_markdown(payload)

        self.assertIn("找不到 papers", text)


class CliTests(unittest.TestCase):
    def _run(self, argv, payload):
        stdout = io.StringIO()
        with mock.patch.object(
            quickstart, "collect", return_value=payload
        ), contextlib.redirect_stdout(stdout):
            code = quickstart.main(["quickstart", *argv])
        return code, stdout.getvalue()

    def test_json_mode_emits_the_payload(self):
        payload = {"schema_version": 1, "environment": {}, "papers": {}}

        code, output = self._run(["--json"], payload)

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["schema_version"], 1)

    def test_out_writes_the_markdown(self):
        payload = RenderTests()._payload()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "brief.md"
            code, _output = self._run(["--out", str(target)], payload)
            text = target.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertIn("ccfa quickstart", text)


if __name__ == "__main__":
    unittest.main()
