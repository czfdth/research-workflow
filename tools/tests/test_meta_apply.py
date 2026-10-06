"""The privileged landing gate for the workflow's own guidance corpus."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ccfa import meta_apply as module
from ccfa.cross_review import _sha256_text


def _pass():
    return {"verdict": "pass", "findings": []}


def _block(statement="这条改动削弱了 gate", evidence="- gate: yes"):
    return {
        "verdict": "block",
        "findings": [
            {"kind": "risk", "statement": statement, "evidence": evidence}
        ],
    }


def _runner(payloads):
    calls = []
    queue = list(payloads)

    def runner(argv, cwd, timeout, prompt):
        calls.append({"argv": list(argv), "prompt": prompt})
        body = queue.pop(0)
        out_index = argv.index("-o") + 1
        Path(argv[out_index]).write_text(
            json.dumps(body, ensure_ascii=False),
            encoding="utf-8",
        )
        return 0, ""

    return runner, calls


def _raw_runner(payloads):
    """Like _runner but writes the model's text verbatim."""
    calls = []
    queue = list(payloads)

    def runner(argv, cwd, timeout, prompt):
        calls.append({"argv": list(argv), "prompt": prompt})
        body = queue.pop(0)
        out_index = argv.index("-o") + 1
        Path(argv[out_index]).write_text(body, encoding="utf-8")
        return 0, ""

    return runner, calls


class MetaApplyTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "docs").mkdir()
        self.target = self.root / "docs" / "guide.md"
        self.target.write_text("gate: yes\nkeep: yes\n", encoding="utf-8")
        self.source = self.root / "proposal.md"
        self.source.write_text("gate: no\nkeep: yes\n", encoding="utf-8")
        self.codex_config = self.root / "config.toml"
        self.codex_config.write_text(
            'model_provider = "exec-provider"\n'
            'model = "deepseek-v4-flash"\n'
            '[model_providers.exec-provider]\n'
            'base_url = "https://exec.example.test/v1"\n',
            encoding="utf-8",
        )

    def _stage(self, **overrides):
        kwargs = {
            "proposal": "p1",
            "target": "docs/guide.md",
            "content": self.source.read_bytes(),
        }
        kwargs.update(overrides)
        return module.stage(self.root, **kwargs)

    def _review(self, models=("gpt-5.6", "claude-sonnet-4"), payloads=None):
        runner, calls = _runner(payloads or [_pass(), _pass()])
        plan = module.review(
            self.root,
            proposal="p1",
            models=list(models),
            runner=runner,
            codex_config=self.codex_config,
        )
        return plan, calls

    def _stage_and_review(self, **stage_overrides):
        self._stage(**stage_overrides)
        plan, _calls = self._review()
        return plan

    def test_stage_keeps_the_working_tree_untouched(self):
        before = self.target.read_bytes()

        plan = self._stage()

        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(plan["target"], "docs/guide.md")
        self.assertEqual(plan["reviews"], [])
        staged = (
            self.root
            / module.WORKFILES
            / "p1"
            / module.STAGED_DIR
            / "docs"
            / "guide.md"
        )
        self.assertEqual(staged.read_bytes(), self.source.read_bytes())
        self.assertNotEqual(plan["before_sha256"], plan["after_sha256"])
        self.assertIn("-gate: yes", plan["diff"])
        self.assertIn("+gate: no", plan["diff"])

    def test_stage_preserves_crlf_bytes(self):
        content = b"gate: no\r\nkeep: yes\r\n"
        self.source.write_bytes(content)

        plan = self._stage()

        staged = (
            self.root
            / module.WORKFILES
            / "p1"
            / module.STAGED_DIR
            / "docs"
            / "guide.md"
        )
        self.assertEqual(staged.read_bytes(), content)
        self.assertEqual(
            plan["after_sha256"],
            "sha256:" + hashlib.sha256(content).hexdigest(),
        )

    def test_stage_refuses_a_denied_area(self):
        (self.root / "papers").mkdir()
        (self.root / "papers" / "main.tex").write_text("x\n", encoding="utf-8")
        self.source.write_text("y\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "禁写区"):
            self._stage(target="papers/main.tex")

    def test_stage_refuses_code_without_the_escalation(self):
        (self.root / "tools").mkdir()
        (self.root / "tools" / "tool.py").write_text("x = 1\n", encoding="utf-8")
        self.source.write_text("x = 2\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "--allow-code"):
            self._stage(target="tools/tool.py")

        plan = self._stage(target="tools/tool.py", allow_code=True)

        self.assertTrue(plan["allow_code"])

    def test_stage_refuses_paths_that_escape_the_root(self):
        for target in ("../outside.md", "/etc/passwd", "docs/../../x.md"):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    self._stage(target=target)

    def test_stage_refuses_to_reuse_a_proposal_id(self):
        self._stage()

        with self.assertRaisesRegex(ValueError, "已有计划"):
            self._stage()

    def test_stage_refuses_identical_content(self):
        with self.assertRaisesRegex(ValueError, "没有可落地的改动"):
            self._stage(content=self.target.read_bytes())

    def test_review_records_family_tier_and_verdict(self):
        self._stage()

        plan, calls = self._review()

        self.assertEqual(len(calls), 2)
        self.assertEqual(plan["reviews"][0]["family"], "openai")
        self.assertEqual(plan["reviews"][1]["family"], "anthropic")
        self.assertEqual(plan["reviews"][0]["review_tier"], "gate-capable")
        self.assertEqual(plan["reviews"][0]["family_judgement"], "cross-family")
        self.assertEqual(
            plan["reviewed_diff_sha256"],
            _sha256_text(plan["diff"]),
        )

    def test_review_refuses_when_the_staged_file_moved(self):
        self._stage()
        staged = (
            self.root
            / module.WORKFILES
            / "p1"
            / module.STAGED_DIR
            / "docs"
            / "guide.md"
        )
        staged.write_text("gate: maybe\n", encoding="utf-8")
        runner, _calls = _runner([_pass(), _pass()])

        with self.assertRaisesRegex(ValueError, "staged 文件已变化"):
            module.review(
                self.root,
                proposal="p1",
                models=["gpt-5.6", "claude-sonnet-4"],
                runner=runner,
                codex_config=self.codex_config,
            )

    def test_review_resolves_a_provider_per_model(self):
        self.codex_config.write_text(
            'model_provider = "exec-provider"\n'
            'model = "deepseek-v4-flash"\n'
            '[model_providers.exec-provider]\n'
            'base_url = "https://exec.example.test/v1"\n'
            '[model_providers.alt]\n'
            'base_url = "https://alt.example.test/v1"\n',
            encoding="utf-8",
        )
        self._stage()
        runner, calls = _runner([_pass(), _pass()])

        plan = module.review(
            self.root,
            proposal="p1",
            models=["gpt-5.6", "claude-sonnet-4"],
            model_providers={"claude-sonnet-4": "alt"},
            runner=runner,
            codex_config=self.codex_config,
        )

        self.assertEqual(plan["reviews"][0]["provider"], "exec-provider")
        self.assertEqual(plan["reviews"][1]["provider"], "alt")
        self.assertNotIn("model_provider=alt", calls[0]["argv"])
        self.assertIn("model_provider=alt", calls[1]["argv"])

    def test_review_rejects_output_that_breaks_the_contract(self):
        # Observed in a real run: the reviewer answered in a key=value format
        # instead of JSON. Parsing the nested finding would have looked like a
        # verdict, so the whole contract failure must be reported.
        self._stage()
        runner, _calls = _raw_runner(
            [
                "verdict=block\n"
                "findings=[\n"
                '  {"kind": "risk", "statement": "x", "evidence": "y"}\n'
                "]\n"
            ]
        )

        with self.assertRaisesRegex(ValueError, "不符合契约"):
            module.review(
                self.root,
                proposal="p1",
                models=["gpt-5.6"],
                provider="exec-provider",
                runner=runner,
                codex_config=self.codex_config,
            )

    def test_review_rejects_a_block_without_findings(self):
        self._stage()
        runner, _calls = _runner([{"verdict": "block", "findings": []}])

        with self.assertRaisesRegex(ValueError, "没有任何 finding"):
            module.review(
                self.root,
                proposal="p1",
                models=["gpt-5.6"],
                provider="exec-provider",
                runner=runner,
                codex_config=self.codex_config,
            )

    def test_apply_lands_the_change_with_a_backup_and_ledger(self):
        before = self.target.read_bytes()
        self._stage_and_review()

        applied = module.apply_change(self.root, proposal="p1")

        self.assertEqual(self.target.read_text(encoding="utf-8"), "gate: no\nkeep: yes\n")
        self.assertEqual(applied["target"], "docs/guide.md")
        self.assertEqual(applied["applied_sha256"], applied["after_sha256"])
        backup = self.root / applied["backup"]
        self.assertEqual(backup.read_bytes(), before)
        ledger = self.root / module.WORKFILES / module.LEDGER_NAME
        records = [
            json.loads(line)
            for line in ledger.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(records), 1)
        self.assertEqual(
            sorted(records[0]["passing_reviewers"]),
            ["claude-sonnet-4", "gpt-5.6"],
        )

    def test_apply_refuses_fewer_than_two_gate_capable_passers(self):
        self._stage()
        self._review(
            models=("gpt-5.6",),
            payloads=[_pass()],
        )

        with self.assertRaisesRegex(ValueError, "至少需要 2 个"):
            module.apply_change(self.root, proposal="p1")
        self.assertIn("gate: yes", self.target.read_text(encoding="utf-8"))

    def test_apply_refuses_an_advisory_only_reviewer_as_the_quorum(self):
        self._stage()
        self._review(
            models=("qwen3:30b", "qwen3:30b-instruct"),
            payloads=[_pass(), _pass()],
        )

        with self.assertRaisesRegex(ValueError, "gate-capable 通过的评审只有 0 个"):
            module.apply_change(self.root, proposal="p1")

    def test_apply_refuses_a_gate_capable_block(self):
        self._stage()
        # One reviewer blocks the same staged diff.
        runner, _calls = _runner([_block(), _pass()])
        module.review(
            self.root,
            proposal="p1",
            models=["gpt-5.6", "claude-sonnet-4"],
            runner=runner,
            codex_config=self.codex_config,
        )

        with self.assertRaisesRegex(ValueError, "给出 block"):
            module.apply_change(self.root, proposal="p1")
        self.assertIn("gate: yes", self.target.read_text(encoding="utf-8"))

    def test_apply_refuses_a_single_family_jury(self):
        self._stage()
        self._review(
            models=("gpt-5.6", "gpt-4o"),
            payloads=[_pass(), _pass()],
        )

        with self.assertRaisesRegex(ValueError, "模型族"):
            module.apply_change(self.root, proposal="p1")

    def test_apply_refuses_when_no_reviewer_is_cross_family(self):
        # An unknown executor family means nobody can be cross-family, so the
        # gate fails closed even though the jury spans two families.
        self.codex_config.write_text(
            'model_provider = "exec-provider"\n'
            'model = "mystery-model"\n'
            '[model_providers.exec-provider]\n'
            'base_url = "https://exec.example.test/v1"\n',
            encoding="utf-8",
        )
        self._stage_and_review()

        with self.assertRaisesRegex(ValueError, "跨族评审"):
            module.apply_change(self.root, proposal="p1")

    def test_apply_refuses_when_the_target_drifted(self):
        self._stage_and_review()
        self.target.write_text("gate: yes\nkeep: no\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "被改动"):
            module.apply_change(self.root, proposal="p1")

    def test_apply_refuses_when_the_staged_file_changed(self):
        self._stage_and_review()
        staged = (
            self.root
            / module.WORKFILES
            / "p1"
            / module.STAGED_DIR
            / "docs"
            / "guide.md"
        )
        staged.write_text("gate: whatever\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "staged 文件哈希"):
            module.apply_change(self.root, proposal="p1")

    def test_apply_refuses_when_the_reviewed_diff_changed(self):
        self._stage_and_review()
        plan_path = self.root / module.WORKFILES / "p1" / module.PLAN_NAME
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["diff"] = plan["diff"] + "-sneaky\n"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "评审覆盖的 diff"):
            module.apply_change(self.root, proposal="p1")

    def test_apply_refuses_before_any_review(self):
        self._stage()

        with self.assertRaisesRegex(ValueError, "还没有任何评审记录"):
            module.apply_change(self.root, proposal="p1")

    def test_check_reports_the_missing_ledger_as_an_advisory(self):
        problems, advisories = module.check(self.root)

        self.assertEqual(problems, [])
        self.assertEqual(
            [advisory.code for advisory in advisories],
            ["meta-apply-no-ledger"],
        )

    def test_check_flags_a_tampered_backup(self):
        self._stage_and_review()
        applied = module.apply_change(self.root, proposal="p1")
        (self.root / applied["backup"]).write_text("tampered\n", encoding="utf-8")

        problems, _advisories = module.check(self.root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["meta-apply-backup-drift"],
        )

    def test_check_passes_on_a_clean_ledger(self):
        self._stage_and_review()
        module.apply_change(self.root, proposal="p1")

        problems, advisories = module.check(self.root)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])


class MetaApplyCliTests(unittest.TestCase):
    def test_stage_and_apply_fail_closed_through_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "g.md").write_text("a\n", encoding="utf-8")
            source = root / "new.md"
            source.write_text("b\n", encoding="utf-8")

            stage_code = module.main(
                [
                    "meta-apply",
                    "--root",
                    str(root),
                    "stage",
                    "--proposal",
                    "p1",
                    "--target",
                    "docs/g.md",
                    "--source",
                    str(source),
                ]
            )
            apply_code = module.main(
                [
                    "meta-apply",
                    "--root",
                    str(root),
                    "apply",
                    "--proposal",
                    "p1",
                ]
            )

        self.assertEqual(stage_code, 0)
        # No jury was recorded, so apply must refuse with the tool-error code.
        self.assertEqual(apply_code, 2)

    def test_cli_rejects_an_unknown_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = module.main(
                [
                    "meta-apply",
                    "--root",
                    tmp,
                    "apply",
                    "--proposal",
                    "nope",
                ]
            )

        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
