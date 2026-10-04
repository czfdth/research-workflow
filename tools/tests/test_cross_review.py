import hashlib
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import yaml

import ccfa.cross_review as cross_review_module
from ccfa.cross_review import (
    REVIEW_SCHEMA,
    build_prompt,
    check_review,
    main,
    run_review,
)


class CrossReviewTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper_root = Path(self._temporary.name)
        (self.paper_root / "manuscript").mkdir()
        self.input_path = self.paper_root / "manuscript" / "main.tex"
        self.input_path.write_text("\\documentclass{article}\n", encoding="utf-8")
        state = {
            "target_venue": {"name": "NeurIPS", "mode": "conference"},
            "stage": {"current": "internal-review"},
        }
        (self.paper_root / "ccfa.yaml").write_text(
            yaml.safe_dump(state, sort_keys=False),
            encoding="utf-8",
        )

    def _payload(self, verdict="pass", blocking=None, summary="summary"):
        return {
            "verdict": verdict,
            "blocking": blocking or [],
            "summary": summary,
        }

    def _runner(
        self,
        *,
        payload=None,
        raw=None,
        code=0,
        stderr="",
        write_last=True,
    ):
        calls = []

        def runner(argv, cwd, timeout, prompt):
            calls.append(
                {
                    "argv": list(argv),
                    "cwd": Path(cwd),
                    "timeout": timeout,
                    "prompt": prompt,
                }
            )
            if write_last:
                output_path = Path(argv[argv.index("-o") + 1])
                text = raw if raw is not None else json.dumps(payload or self._payload())
                output_path.write_text(text, encoding="utf-8")
            return code, stderr

        runner.calls = calls
        return runner

    def _run(self, runner, **overrides):
        values = {
            "model": "deepseek-v4-pro",
            "allow_same_family": True,
            "override_reason": (
                "test migration: no second-family provider is configured"
            ),
            "stage": "internal-review",
            "paths": [Path("manuscript/main.tex")],
        }
        values.update(overrides)
        return run_review(self.paper_root, runner=runner, **values)

    def _record_path(self):
        return self.paper_root / "reviews" / "cross-review.json"

    def _run_main(self, argv):
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()


class TestPromptAndArgv(CrossReviewTests):
    def test_build_prompt_contains_gate_criterion_file_list_and_no_write_rule(self):
        prompt = build_prompt(
            self.paper_root,
            "internal-review",
            [Path("manuscript/main.tex")],
        )

        self.assertIn("review_cleared", prompt)
        self.assertIn("跨模型评审报告无 blocking", prompt)
        self.assertIn("manuscript/main.tex", prompt)
        self.assertIn("禁止修改任何文件", prompt)
        self.assertIn("JSON", prompt)
        self.assertIn("本次运行就是在生成当前有效的跨模型评审报告", prompt)
        self.assertIn("不要因为 reviews/cross-review.json 尚不存在", prompt)

    def test_argv_has_exact_required_flags_and_stdin_prompt(self):
        runner = self._runner(payload=self._payload())

        self._run(runner)

        argv = runner.calls[0]["argv"]
        self.assertEqual(argv[:2], ["codex", "exec"])
        self.assertIn("-m", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "deepseek-v4-pro")
        self.assertIn("-s", argv)
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertIn("--ephemeral", argv)
        self.assertIn("--skip-git-repo-check", argv)
        self.assertIn("-C", argv)
        self.assertEqual(argv[argv.index("-C") + 1], str(self.paper_root))
        self.assertIn("--output-schema", argv)
        self.assertIn("-o", argv)
        self.assertEqual(argv[-1], "-")
        self.assertIn("禁止修改任何文件", runner.calls[0]["prompt"])

    def test_review_schema_is_strict(self):
        self.assertEqual(REVIEW_SCHEMA["properties"]["verdict"]["enum"], ["pass", "blocking"])
        self.assertEqual(
            REVIEW_SCHEMA["properties"]["blocking"]["items"]["required"],
            ["title", "evidence"],
        )


class TestRunReview(CrossReviewTests):
    def test_pass_writes_json_and_markdown_records(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run(runner)

        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["family_judgement"], "same-family")
        self.assertTrue(self._record_path().is_file())
        self.assertTrue((self.paper_root / "reviews" / "cross-review.md").is_file())
        self.assertEqual(result["model"], "deepseek-v4-pro")

    def test_same_family_requires_explicit_override(self):
        runner = self._runner(payload=self._payload("pass"))

        with self.assertRaisesRegex(ValueError, "allow-same-family"):
            self._run(runner, allow_same_family=False)

        self.assertEqual(runner.calls, [])
        self.assertFalse(self._record_path().exists())

    def test_same_family_override_requires_a_reason(self):
        runner = self._runner(payload=self._payload("pass"))

        with self.assertRaisesRegex(ValueError, "override-reason"):
            self._run(
                runner,
                allow_same_family=True,
                override_reason=None,
            )

        self.assertEqual(runner.calls, [])
        self.assertFalse(self._record_path().exists())

    def test_same_family_override_reason_is_recorded(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run(runner)

        self.assertTrue(result["family_override"])
        self.assertIn("no second-family provider", result["family_override_reason"])
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(
            record["family_override_reason"],
            result["family_override_reason"],
        )

    def test_cross_family_does_not_need_override_reason(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
            override_reason=None,
        )

        self.assertEqual(result["family_judgement"], "cross-family")
        self.assertFalse(result["family_override"])
        self.assertIsNone(result["family_override_reason"])

    def test_cross_family_model_is_allowed_without_override(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
        )

        self.assertEqual(result["family_judgement"], "cross-family")
        self.assertFalse(result["family_override"])

    def test_provider_is_passed_to_codex_and_recorded(self):
        runner = self._runner(payload=self._payload("pass"))

        result = self._run(
            runner,
            model="gpt-5.6",
            provider="other-provider",
            allow_same_family=False,
        )

        argv = runner.calls[0]["argv"]
        self.assertIn("-c", argv)
        self.assertIn("model_provider=other-provider", argv)
        self.assertEqual(result["provider"], "other-provider")

    def test_blocking_verdict_preserves_evidence_exactly(self):
        blocking = [
            {
                "title": "Missing ablation",
                "evidence": "Table 2 has no seed variance.",
            }
        ]
        runner = self._runner(payload=self._payload("blocking", blocking))

        result = self._run(runner)

        self.assertEqual(result["verdict"], "blocking")
        self.assertEqual(result["blocking"], blocking)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["blocking"], blocking)

    def test_missing_last_message_is_malformed_and_not_pass(self):
        runner = self._runner(write_last=False)

        result = self._run(runner)

        self.assertEqual(result["verdict"], "malformed")
        self.assertNotEqual(result["verdict"], "pass")
        self.assertTrue(self._record_path().is_file())

    def test_invalid_json_is_malformed(self):
        runner = self._runner(raw="{not json", write_last=True)

        result = self._run(runner)

        self.assertEqual(result["verdict"], "malformed")

    def test_nonzero_exit_writes_failure_record_and_raises(self):
        runner = self._runner(code=7, stderr="model unavailable", write_last=False)

        with self.assertRaisesRegex(ValueError, "codex exec"):
            self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["exit_code"], 7)
        self.assertIn("model unavailable", record["stderr"])

    def test_missing_codex_names_codex_exec(self):
        def runner(argv, cwd, timeout, prompt):
            raise FileNotFoundError("codex")

        with self.assertRaisesRegex(ValueError, "codex exec"):
            self._run(runner)

    def test_record_is_not_overwritten_without_force(self):
        first = self._runner(payload=self._payload("pass"))
        second = self._runner(payload=self._payload("blocking", [{"title": "x", "evidence": "y"}]))
        self._run(first)

        with self.assertRaises(ValueError):
            self._run(second)
        self.assertEqual(len(second.calls), 0)

        result = self._run(second, force=True)
        self.assertEqual(result["verdict"], "blocking")

    def test_input_hashes_normalize_text_line_endings(self):
        path = self.paper_root / "manuscript" / "crlf.tex"
        path.write_bytes(b"line one\r\nline two\r\n")

        result = self._run(
            self._runner(),
            paths=[Path("manuscript/crlf.tex")],
        )

        digest = hashlib.sha256(b"line one\nline two\n").hexdigest()
        self.assertEqual(
            result["input_hashes"]["manuscript/crlf.tex"],
            f"sha256:{digest}",
        )

    def test_input_hashes_keep_binary_bytes_exact(self):
        path = self.paper_root / "manuscript" / "blob.bin"
        path.write_bytes(b"line one\r\nline two\r\n")

        result = self._run(
            self._runner(),
            paths=[Path("manuscript/blob.bin")],
        )

        digest = hashlib.sha256(
            b"line one\r\nline two\r\n"
        ).hexdigest()
        self.assertEqual(
            result["input_hashes"]["manuscript/blob.bin"],
            f"sha256:{digest}",
        )

    def test_input_hashes_are_recorded(self):
        runner = self._runner(payload=self._payload())

        result = self._run(runner)

        self.assertEqual(
            set(result["input_hashes"]),
            {"manuscript/main.tex"},
        )
        self.assertTrue(result["input_hashes"]["manuscript/main.tex"].startswith("sha256:"))

    def test_prompt_hash_is_recorded_and_matches_the_prompt_sent(self):
        runner = self._runner(payload=self._payload())

        result = self._run(runner)

        digest = hashlib.sha256(
            runner.calls[0]["prompt"].encode("utf-8")
        ).hexdigest()
        self.assertEqual(result["prompt_sha256"], f"sha256:{digest}")

    def test_long_stderr_is_bounded_in_complete_record(self):
        runner = self._runner(
            payload=self._payload(),
            stderr="x" * 100_000,
        )

        self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertLessEqual(
            len(record["stderr"]),
            4000 + len("...[truncated]"),
        )
        self.assertTrue(record["stderr"].endswith("...[truncated]"))

    def test_long_stderr_is_bounded_in_malformed_record(self):
        runner = self._runner(
            write_last=False,
            stderr="x" * 100_000,
        )

        self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "malformed")
        self.assertLessEqual(
            len(record["stderr"]),
            4000 + len("...[truncated]"),
        )
        self.assertTrue(record["stderr"].endswith("...[truncated]"))

    def test_long_stderr_is_bounded_in_failure_record(self):
        runner = self._runner(
            code=7,
            write_last=False,
            stderr="x" * 100_000,
        )

        with self.assertRaisesRegex(ValueError, "codex exec"):
            self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertLessEqual(
            len(record["stderr"]),
            4000 + len("...[truncated]"),
        )
        self.assertTrue(record["stderr"].endswith("...[truncated]"))

    def test_short_stderr_is_not_marked_truncated(self):
        runner = self._runner(
            payload=self._payload(),
            stderr="short stderr",
        )

        self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["stderr"], "short stderr")
        self.assertNotIn("...[truncated]", record["stderr"])

    def test_long_raw_last_message_is_marked_truncated(self):
        runner = self._runner(raw="x" * 20_000)

        result = self._run(runner)

        self.assertEqual(result["verdict"], "malformed")
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertLessEqual(
            len(record["raw_last_message"]),
            10_000 + len("...[truncated]"),
        )
        self.assertTrue(record["raw_last_message"].endswith("...[truncated]"))

    def test_short_raw_last_message_is_not_marked_truncated(self):
        runner = self._runner(raw="{short malformed")

        self._run(runner)

        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        self.assertEqual(record["raw_last_message"], "{short malformed")
        self.assertNotIn("...[truncated]", record["raw_last_message"])


class TestCheckReview(CrossReviewTests):
    def test_missing_record_is_review_missing(self):
        problems = check_review(self.paper_root)
        self.assertEqual([problem.code for problem in problems], ["review-missing"])

    def test_changed_input_is_review_stale(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        self.input_path.write_text("changed\n", encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual([problem.code for problem in problems], ["review-stale"])

    def test_same_family_record_is_a_problem_without_override(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["family_override"] = False
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-same-family"],
        )
        self.assertEqual(
            check_review(self.paper_root, allow_same_family=True),
            [],
        )

    def test_same_family_override_without_reason_is_a_problem(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("family_override_reason", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(
            self.paper_root,
            allow_same_family=True,
        )

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-override-reason-missing"],
        )

    def test_strict_cross_family_reports_override(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)

        problems = check_review(
            self.paper_root,
            allow_same_family=True,
            strict_cross_family=True,
        )

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-family-override"],
        )

    def test_edited_family_judgement_cannot_bypass_recomputation(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["family_override"] = False
        record["family_judgement"] = "cross-family"
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-family-mismatch", "review-same-family"],
        )
        self.assertEqual(
            [problem.code for problem in check_review(
                self.paper_root,
                allow_same_family=True,
            )],
            ["review-family-mismatch"],
        )

    def test_legacy_record_without_family_fields_requires_explicit_migration(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("family_judgement", None)
        record.pop("family_override", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-same-family"],
        )
        self.assertEqual(
            check_review(self.paper_root, allow_same_family=True),
            [],
        )

    def test_legacy_record_with_family_but_no_execution_model_is_only_same_family(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("execution_model", None)
        record.pop("provider", None)
        record.pop("family_override", None)
        record["family_judgement"] = "same-family"
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-same-family"],
        )
        self.assertEqual(
            check_review(self.paper_root, allow_same_family=True),
            [],
        )

    def test_missing_provenance_is_flagged_even_for_a_cross_family_looking_model(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
        )
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("execution_model", None)
        record.pop("provider", None)
        record.pop("family_override", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-same-family"],
        )
        self.assertEqual(
            check_review(self.paper_root, allow_same_family=True),
            [],
        )

    def test_foreign_execution_model_is_not_complete_provenance(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            model="gpt-5.6",
            allow_same_family=False,
        )
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["execution_model"] = "gpt-5.6"
        record["family_judgement"] = "cross-family"
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-same-family"],
        )
        self.assertEqual(
            check_review(self.paper_root, allow_same_family=True),
            [],
        )

    def test_mismatch_survives_incomplete_provenance_and_allow_flag(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["family_override"] = False
        record["family_judgement"] = "cross-family"
        record.pop("provider", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-family-mismatch", "review-same-family"],
        )
        self.assertEqual(
            [
                problem.code
                for problem in check_review(
                    self.paper_root,
                    allow_same_family=True,
                )
            ],
            ["review-family-mismatch"],
        )

    def test_unknown_family_mismatch_survives_allow_flag(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            model="mystery-v1",
            allow_same_family=True,
        )
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["family_override"] = False
        record["family_judgement"] = "same-family"
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-family-mismatch", "review-same-family"],
        )
        self.assertEqual(
            [
                problem.code
                for problem in check_review(
                    self.paper_root,
                    allow_same_family=True,
                )
            ],
            ["review-family-mismatch"],
        )

    def test_matching_prompt_hash_is_not_reported(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(problems, [])

    def test_repeated_path_does_not_cause_prompt_drift(self):
        runner = self._runner(payload=self._payload())
        self._run(
            runner,
            paths=[
                Path("manuscript/main.tex"),
                Path("manuscript/main.tex"),
            ],
        )

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(problems, [])

    def test_record_without_prompt_hash_is_review_prompt_unknown(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record.pop("prompt_sha256", None)
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-prompt-unknown"],
        )

    def test_stale_prompt_hash_is_review_prompt_drift(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["prompt_sha256"] = "sha256:" + "0" * 64
        self._record_path().write_text(json.dumps(record), encoding="utf-8")

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-prompt-drift"],
        )

    def test_changed_gate_criterion_is_review_prompt_drift(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        original = cross_review_module.gate_for

        def rewritten(mode, stage):
            gate = original(mode, stage)
            return gate._replace(criterion=gate.criterion + "（改写）")

        with mock.patch.object(cross_review_module, "gate_for", rewritten):
            problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-prompt-drift"],
        )

    def test_unbuildable_prompt_is_review_prompt_unknown(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        state = {
            "target_venue": {"name": "NeurIPS", "mode": "not-a-mode"},
            "stage": {"current": "internal-review"},
        }
        (self.paper_root / "ccfa.yaml").write_text(
            yaml.safe_dump(state, sort_keys=False), encoding="utf-8"
        )

        problems = check_review(self.paper_root, allow_same_family=True)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-prompt-unknown"],
        )

    def test_blocking_record_is_review_blocking(self):
        quote = (
            "The baseline comparison omits the strongest published method "
            "entirely."
        )
        self.input_path.write_text(
            "\\documentclass{article}\n"
            "The baseline comparison omits the strongest\n"
            "published method entirely.\n",
            encoding="utf-8",
        )
        blocking = [{"title": "gap", "evidence": f'main.tex: "{quote}"'}]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)

        problems = check_review(self.paper_root)

        self.assertEqual([problem.code for problem in problems], ["review-blocking"])

    def test_fabricated_blocking_quote_is_uncited(self):
        self.input_path.write_text(
            "\\documentclass{article}\n"
            "The paper reports a small controlled study.\n",
            encoding="utf-8",
        )
        blocking = [
            {
                "title": "gap",
                "evidence": (
                    'main.tex: "The baseline comparison omits the strongest '
                    'published method entirely."'
                ),
            }
        ]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)

        problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-blocking", "review-uncited-blocking"],
        )
        uncited = next(
            problem
            for problem in problems
            if problem.code == "review-uncited-blocking"
        )
        self.assertIn("gap", uncited.message)

    def test_quote_shorter_than_twenty_characters_is_uncited(self):
        self.input_path.write_text("short quote here\n", encoding="utf-8")
        blocking = [
            {"title": "short", "evidence": 'main.tex: "short quote here"'}
        ]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)

        problems = check_review(self.paper_root)

        self.assertIn(
            "review-uncited-blocking",
            [problem.code for problem in problems],
        )

    def test_whole_evidence_substring_short_circuits_the_matcher(self):
        sentence = (
            "The baseline comparison omits the strongest published method "
            "entirely."
        )
        self.input_path.write_text(sentence + "\n", encoding="utf-8")
        blocking = [{"title": "gap", "evidence": sentence}]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)
        calls = []
        real = cross_review_module._longest_quote_length

        def counting(evidence, corpus):
            calls.append((evidence, corpus))
            return real(evidence, corpus)

        with mock.patch(
            "ccfa.cross_review._longest_quote_length",
            side_effect=counting,
        ):
            problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-blocking"],
        )
        self.assertEqual(calls, [], "short path must not call the matcher")

    def test_cross_newline_quote_falls_back_to_the_substring_match(self):
        sentence = (
            "The baseline comparison omits the strongest published method "
            "entirely."
        )
        self.input_path.write_text(
            "The baseline comparison omits the strongest\n"
            "published method entirely.\n",
            encoding="utf-8",
        )
        blocking = [{"title": "gap", "evidence": f'main.tex: "{sentence}"'}]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)
        calls = []
        real = cross_review_module._longest_quote_length

        def counting(evidence, corpus):
            calls.append((evidence, corpus))
            return real(evidence, corpus)

        with mock.patch(
            "ccfa.cross_review._longest_quote_length",
            side_effect=counting,
        ):
            problems = check_review(self.paper_root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["review-blocking"],
        )
        self.assertEqual(len(calls), 1)

    def test_uncited_blocking_check_exits_one(self):
        self.input_path.write_text(
            "\\documentclass{article}\n",
            encoding="utf-8",
        )
        blocking = [
            {
                "title": "gap",
                "evidence": (
                    'main.tex: "This sentence was never in the manuscript '
                    'at all, honestly."'
                ),
            }
        ]
        runner = self._runner(payload=self._payload("blocking", blocking))
        self._run(runner)

        code, stdout, stderr = self._run_main(
            [
                "cross-review",
                "check",
                "--paper-root",
                str(self.paper_root),
            ]
        )

        self.assertEqual(code, 1)
        payload = json.loads(stdout)
        self.assertIn(
            "review-uncited-blocking",
            [problem["code"] for problem in payload["problems"]],
        )
        self.assertIn("review-uncited-blocking", stderr)

    def test_malformed_record_is_review_malformed(self):
        path = self._record_path()
        path.parent.mkdir(parents=True)
        path.write_text("{bad json", encoding="utf-8")

        problems = check_review(self.paper_root)

        self.assertEqual([problem.code for problem in problems], ["review-malformed"])

    def test_input_hash_path_escape_is_record_invalid(self):
        runner = self._runner(payload=self._payload())
        self._run(runner)
        outside = self.paper_root.parent / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        record = json.loads(self._record_path().read_text(encoding="utf-8"))
        record["input_hashes"] = {
            "../outside.txt": "sha256:"
            + hashlib.sha256(outside.read_bytes()).hexdigest()
        }
        self._record_path().write_text(
            json.dumps(record),
            encoding="utf-8",
        )

        problems = check_review(self.paper_root)

        self.assertEqual([problem.code for problem in problems], ["review-record-invalid"])

    def test_check_out_dir_reads_non_default_record(self):
        runner = self._runner(payload=self._payload())
        self._run(runner, out_dir=Path("custom-reviews"))

        code, stdout, stderr = self._run_main(
            [
                "cross-review",
                "check",
                "--paper-root",
                str(self.paper_root),
                "--out-dir",
                "custom-reviews",
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["problem_count"], 0)
        self.assertEqual(stderr, "")

    def test_check_default_out_dir_behavior_is_unchanged(self):
        code, stdout, stderr = self._run_main(
            [
                "cross-review",
                "check",
                "--paper-root",
                str(self.paper_root),
            ]
        )

        report = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(report["problems"][0]["code"], "review-missing")
        self.assertIn("review-missing", stderr)


class TestMainAndHelp(CrossReviewTests):
    def test_help_states_same_family_different_scale_not_cross_family(self):
        stdout = StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            main(["cross-review", "--help"])

        self.assertEqual(raised.exception.code, 0)
        text = stdout.getvalue()
        self.assertIn("同族不同规模", text)
        self.assertIn("非跨族", text)
        self.assertNotIn("--execution-model", text)

    def test_main_run_pass_zero_blocking_one_and_oserror_two(self):
        pass_runner = self._runner(payload=self._payload("pass"))
        with mock.patch("ccfa.cross_review.run_review", side_effect=lambda *a, **k: {"verdict": "pass"}):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "cross-review",
                            "run",
                            "--paper-root",
                            str(self.paper_root),
                            "--stage",
                            "internal-review",
                            "--path",
                            "manuscript/main.tex",
                        ]
                    ),
                    0,
                )

        with mock.patch("ccfa.cross_review.run_review", side_effect=lambda *a, **k: {"verdict": "blocking"}):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "cross-review",
                            "run",
                            "--paper-root",
                            str(self.paper_root),
                            "--stage",
                            "internal-review",
                            "--path",
                            "manuscript/main.tex",
                        ]
                    ),
                    1,
                )

        with mock.patch(
            "ccfa.cross_review.run_review",
            side_effect=ValueError("无法运行 codex exec"),
        ):
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "cross-review",
                            "run",
                            "--paper-root",
                            str(self.paper_root),
                            "--stage",
                            "internal-review",
                            "--path",
                            "manuscript/main.tex",
                        ]
                    ),
                    2,
                )


if __name__ == "__main__":
    unittest.main()
