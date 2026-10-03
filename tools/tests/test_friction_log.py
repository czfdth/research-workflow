import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ccfa.friction_log import (
    add_entry,
    check_store,
    filter_entries,
    load_store,
    save_store,
)


class FrictionLogTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.store_path = self.root / "friction_log.json"

    def _add(self, **overrides):
        values = {
            "stage": "writing",
            "component": "citation-manager",
            "category": "tool-bug",
            "severity": "high",
            "description": "The citation manager dropped a key.",
        }
        values.update(overrides)
        return add_entry(self.store_path, **values)

    def _write_store(self, store):
        self.store_path.write_text(
            json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def test_load_store_missing_file_returns_empty_store(self):
        self.assertEqual(load_store(self.store_path), {"version": 1, "entries": []})

    def test_add_entry_assigns_incrementing_ids_and_complete_fields(self):
        first = self._add(description="first")
        second = self._add(
            stage="revision",
            component="latex-check",
            category="environment",
            severity="medium",
            description="second",
            workaround="used a fallback",
        )

        self.assertEqual(first["id"], 1)
        self.assertEqual(second["id"], 2)
        self.assertEqual(
            set(first),
            {
                "id",
                "created_at",
                "stage",
                "component",
                "category",
                "severity",
                "description",
                "workaround",
            },
        )
        self.assertIsNone(first["workaround"])
        self.assertEqual(second["workaround"], "used a fallback")
        datetime.strptime(first["created_at"], "%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(load_store(self.store_path)["entries"], [first, second])

    def test_add_entry_rejects_invalid_category(self):
        with self.assertRaises(ValueError):
            self._add(category="not-a-category")

    def test_add_entry_rejects_invalid_severity(self):
        with self.assertRaises(ValueError):
            self._add(severity="urgent")

    def test_check_store_revalidates_hand_edited_enums_for_all_entries(self):
        self._add(description="first")
        self._add(description="second")
        store = load_store(self.store_path)
        store["entries"][0]["category"] = "whatever"
        store["entries"][1]["severity"] = "urgent"
        self._write_store(store)

        problems = check_store(self.store_path)

        invalid = [p for p in problems if p.code == "friction-invalid-enum"]
        self.assertEqual(len(invalid), 2)

    def test_check_store_reports_missing_description_and_required_fields(self):
        self._write_store(
            {
                "version": 1,
                "entries": [
                    {
                        "id": 1,
                        "stage": "writing",
                        "component": "citation-manager",
                        "category": "tool-bug",
                        "severity": "high",
                        "description": "",
                    },
                    {
                        "id": 2,
                        "stage": "writing",
                        "category": "tool-bug",
                        "severity": "high",
                        "description": "missing component",
                    },
                    {
                        "id": 3,
                        "component": "citation-manager",
                        "category": "tool-bug",
                        "severity": "high",
                        "description": "missing stage",
                    },
                ],
            }
        )

        problems = check_store(self.store_path)

        self.assertEqual(
            [p.code for p in problems].count("friction-missing-description"),
            1,
        )
        self.assertEqual(
            [p.code for p in problems].count("friction-missing-field"),
            2,
        )

    def test_load_store_rejects_invalid_version_and_shape(self):
        cases = [
            {"entries": []},
            {"version": 2, "entries": []},
            {"version": 1, "entries": {}},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                self._write_store(payload)
                with self.assertRaises(ValueError):
                    load_store(self.store_path)

    def test_save_store_replaces_atomically_and_leaves_no_temporary_file(self):
        store = {"version": 1, "entries": [{"id": 1, "description": "kept"}]}

        with patch("ccfa.cli.os.replace", wraps=os.replace) as replace:
            save_store(self.store_path, store)

        replace.assert_called_once()
        self.assertEqual(Path(replace.call_args.args[1]), self.store_path)
        self.assertEqual(load_store(self.store_path), store)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_filter_entries_by_category(self):
        store = {
            "version": 1,
            "entries": [
                {"id": 1, "category": "tool-bug"},
                {"id": 2, "category": "environment"},
            ],
        }
        self.assertEqual(
            filter_entries(store, category="environment"),
            [{"id": 2, "category": "environment"}],
        )

    def test_filter_entries_by_component(self):
        store = {
            "version": 1,
            "entries": [
                {"id": 1, "component": "citation-manager"},
                {"id": 2, "component": "latex-check"},
            ],
        }
        self.assertEqual(
            filter_entries(store, component="latex-check"),
            [{"id": 2, "component": "latex-check"}],
        )

    def test_filter_entries_by_severity(self):
        store = {
            "version": 1,
            "entries": [
                {"id": 1, "severity": "low"},
                {"id": 2, "severity": "high"},
            ],
        }
        self.assertEqual(
            filter_entries(store, severity="high"),
            [{"id": 2, "severity": "high"}],
        )

    def test_check_store_is_read_only(self):
        self._write_store(
            {
                "version": 1,
                "entries": [
                    {
                        "id": 1,
                        "stage": "writing",
                        "component": "citation-manager",
                        "category": "invalid",
                        "severity": "high",
                        "description": "invalid category",
                    }
                ],
            }
        )
        before = self.store_path.read_bytes()

        check_store(self.store_path)

        self.assertEqual(self.store_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
