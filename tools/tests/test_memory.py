import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ccfa.memory import (
    DEAD_ENDS_FILE,
    IDEAS_FILE,
    VALID_IDEA_STATUSES,
    add_dead_end,
    add_idea,
    list_memory,
    load_memory,
    main,
    save_memory,
)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper_root = Path(self._temporary.name)

    def _ideas_path(self):
        return self.paper_root / IDEAS_FILE

    def _dead_ends_path(self):
        return self.paper_root / DEAD_ENDS_FILE

    def _write(self, relative, text):
        path = self.paper_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _add_idea(self, **overrides):
        values = {
            "idea": "使用对比学习替代多任务损失",
            "date": "2026-10-03",
        }
        values.update(overrides)
        return add_idea(self.paper_root, **values)

    def _add_dead_end(self, **overrides):
        values = {
            "idea": "使用对比学习替代多任务损失",
            "reason": "增益来自 batch size 变化",
            "evidence": "experiments/results/ablation.csv",
            "reopen_if": "出现新的负样本采样策略",
            "date": "2026-10-03",
        }
        values.update(overrides)
        return add_dead_end(self.paper_root, **values)


class TestAddIdea(MemoryTests):
    def test_first_add_creates_file_with_comment_header_and_fixed_fields(self):
        entry = self._add_idea(notes="initial note")
        path = self._ideas_path()

        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.splitlines()[0], "# 研究记忆（脚本读写，勿改字段名）")
        self.assertEqual(
            list(entry),
            ["id", "date", "idea", "status", "notes"],
        )
        self.assertEqual(
            entry,
            {
                "id": "I1",
                "date": "2026-10-03",
                "idea": "使用对比学习替代多任务损失",
                "status": "active",
                "notes": "initial note",
            },
        )

    def test_second_add_appends_without_overwriting_first_entry(self):
        first = self._add_idea(idea="first idea")
        second = self._add_idea(idea="second idea")

        self.assertEqual(first["id"], "I1")
        self.assertEqual(second["id"], "I2")
        self.assertEqual(
            [entry["idea"] for entry in load_memory(self._ideas_path())],
            ["first idea", "second idea"],
        )

    def test_next_id_uses_max_numeric_suffix_and_skips_used_numbers(self):
        save_memory(
            self._ideas_path(),
            [
                {
                    "id": "I1",
                    "date": "2026-10-01",
                    "idea": "first",
                    "status": "active",
                    "notes": None,
                },
                {
                    "id": "I3",
                    "date": "2026-10-02",
                    "idea": "third",
                    "status": "active",
                    "notes": None,
                },
            ],
        )

        entry = self._add_idea(idea="fourth")

        self.assertEqual(entry["id"], "I4")

    def test_invalid_date_status_and_idea_are_rejected(self):
        with self.assertRaises(ValueError):
            self._add_idea(date="2026-2-3")
        with self.assertRaises(ValueError):
            self._add_idea(status="whatever")
        for value in ("", "   ", None, 7):
            with self.subTest(idea=value):
                with self.assertRaises(ValueError):
                    self._add_idea(idea=value)

    def test_valid_status_enum_is_exposed(self):
        self.assertEqual(
            VALID_IDEA_STATUSES,
            ("active", "abandoned", "merged"),
        )


class TestAddDeadEnd(MemoryTests):
    def test_add_dead_end_has_six_fields_in_fixed_order(self):
        entry = self._add_dead_end()
        path = self._dead_ends_path()

        text = path.read_text(encoding="utf-8")
        self.assertEqual(
            text.splitlines()[0],
            "# 反重复记忆（脚本读写，勿改字段名）",
        )
        self.assertEqual(
            list(entry),
            ["id", "date", "idea", "reason", "evidence", "reopen_if"],
        )
        self.assertEqual(entry["id"], "DE1")
        self.assertEqual(entry["reopen_if"], "出现新的负样本采样策略")
        self.assertEqual(tuple(load_memory(path)[0]), tuple(entry))

    def test_reason_evidence_and_reopen_if_are_required(self):
        with self.assertRaises(ValueError):
            add_dead_end(
                self.paper_root,
                idea="missing reopen_if",
                reason="why",
                evidence="evidence.csv",
                date="2026-10-03",
            )

        for field in ("reason", "evidence", "reopen_if"):
            values = {
                "reason": "why",
                "evidence": "evidence.csv",
                "reopen_if": "when",
            }
            values[field] = ""
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self._add_dead_end(**values)

    def test_dead_end_ids_are_independent_from_idea_ids(self):
        self._add_idea()
        self._add_idea()

        first = self._add_dead_end()
        second = self._add_dead_end()

        self.assertEqual((first["id"], second["id"]), ("DE1", "DE2"))
        self.assertEqual(
            [entry["id"] for entry in load_memory(self._ideas_path())],
            ["I1", "I2"],
        )


class TestMemoryStore(MemoryTests):
    def test_load_memory_missing_file_returns_empty_list(self):
        self.assertEqual(load_memory(self._ideas_path()), [])

    def test_load_memory_rejects_broken_yaml(self):
        path = self._write(IDEAS_FILE, "- id: [unterminated\n")

        with self.assertRaises(ValueError):
            load_memory(path)

    def test_load_memory_rejects_mapping_top_level(self):
        path = self._write(IDEAS_FILE, "id: I1\nidea: wrong shape\n")

        with self.assertRaises(ValueError):
            load_memory(path)

    def test_save_memory_is_atomic_orders_fields_and_leaves_no_tmp(self):
        path = self._ideas_path()
        entries = [
            {
                "notes": None,
                "idea": "中文内容",
                "status": "active",
                "date": "2026-10-03",
                "id": "I1",
            }
        ]

        with patch("ccfa.cli.os.replace", wraps=os.replace) as replace:
            save_memory(path, entries)

        replace.assert_called_once()
        self.assertEqual(Path(replace.call_args.args[1]), path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("中文内容", text)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(list(load_memory(path)[0]), ["id", "date", "idea", "status", "notes"])
        self.assertEqual(list(path.parent.glob(f"{path.name}.tmp")), [])


class TestListMemory(MemoryTests):
    def test_list_memory_filters_kind_and_status(self):
        self._add_idea(idea="active idea", status="active")
        self._add_idea(idea="abandoned idea", status="abandoned")
        self._add_dead_end(idea="dead end")

        active = list_memory(self.paper_root, kind="ideas", status="active")
        dead_ends = list_memory(self.paper_root, kind="dead-ends")
        everything = list_memory(self.paper_root)

        self.assertEqual([entry["idea"] for entry in active["ideas"]], ["active idea"])
        self.assertEqual(active["dead_ends"], [])
        self.assertEqual(dead_ends["ideas"], [])
        self.assertEqual([entry["idea"] for entry in dead_ends["dead_ends"]], ["dead end"])
        self.assertEqual(len(everything["ideas"]), 2)
        self.assertEqual(len(everything["dead_ends"]), 1)


class TestMain(MemoryTests):
    def test_add_and_list_commands_emit_json(self):
        add_stdout = StringIO()
        list_stdout = StringIO()

        with redirect_stdout(add_stdout), redirect_stderr(StringIO()):
            add_code = main(
                [
                    "memory",
                    "--paper-root",
                    str(self.paper_root),
                    "add-idea",
                    "--idea",
                    "cli idea",
                    "--date",
                    "2026-10-03",
                ]
            )
        with redirect_stdout(list_stdout), redirect_stderr(StringIO()):
            list_code = main(
                ["memory", "--paper-root", str(self.paper_root), "list"]
            )

        self.assertEqual(add_code, 0)
        self.assertEqual(list_code, 0)
        self.assertEqual(json.loads(add_stdout.getvalue())["id"], "I1")
        self.assertEqual(
            json.loads(list_stdout.getvalue())["ideas"][0]["idea"],
            "cli idea",
        )

    def test_invalid_add_is_a_tool_error(self):
        stderr = StringIO()

        with redirect_stderr(stderr):
            code = main(
                [
                    "memory",
                    "--paper-root",
                    str(self.paper_root),
                    "add-dead-end",
                    "--idea",
                    "dead end",
                    "--reason",
                    "reason",
                    "--evidence",
                    "evidence.csv",
                    "--reopen-if",
                    "",
                    "--date",
                    "2026-10-03",
                ]
            )

        self.assertEqual(code, 2)
        self.assertIn("工具错误", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
