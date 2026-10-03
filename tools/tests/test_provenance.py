import json
import tempfile
import unittest
from pathlib import Path

from ccfa.provenance import (
    VALID_CLASSIFICATIONS,
    add_entry,
    load_store,
    save_store,
    sha256_of,
)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / "raw.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        self.store = self.root / "data" / "provenance.json"

    def add(self, **overrides):
        kwargs = dict(source="internal export", classification="real")
        kwargs.update(overrides)
        return add_entry(self.store, self.root, "data/raw.csv", **kwargs)


class TestSha256(BaseCase):
    def test_hash_is_prefixed_and_stable(self):
        first = sha256_of(self.data / "raw.csv")
        self.assertTrue(first.startswith("sha256:"))
        self.assertEqual(first, sha256_of(self.data / "raw.csv"))


class TestStoreRoundTrip(BaseCase):
    def test_missing_store_is_empty(self):
        self.assertEqual(load_store(self.store), {"version": 1, "files": {}})

    def test_save_then_load_round_trips(self):
        save_store(self.store, {"version": 1, "files": {"a": {"source": "x"}}})
        self.assertEqual(load_store(self.store)["files"]["a"]["source"], "x")

    def test_non_object_store_raises(self):
        self.store.write_text("[1, 2]\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_store(self.store)

    def test_malformed_json_raises(self):
        self.store.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_store(self.store)

    def test_save_leaves_no_temporary_file_behind(self):
        save_store(self.store, {"version": 1, "files": {}})
        leftovers = [p.name for p in self.data.iterdir() if p.name != "provenance.json"]
        self.assertEqual([n for n in leftovers if n.startswith("provenance.")], [])


class TestAddEntry(BaseCase):
    def test_records_source_classification_and_checksum(self):
        entry = self.add(units="count", coverage="2020-2024", notes="exported 2026-10")
        self.assertEqual(entry["classification"], "real")
        self.assertEqual(entry["units"], "count")
        self.assertEqual(entry["sha256"], sha256_of(self.data / "raw.csv"))
        self.assertIn("recorded_at", entry)
        self.assertEqual(entry["size"], (self.data / "raw.csv").stat().st_size)

    def test_store_is_written_with_the_entry(self):
        self.add()
        self.assertIn("data/raw.csv", load_store(self.store)["files"])

    def test_invalid_classification_is_rejected(self):
        with self.assertRaises(ValueError):
            self.add(classification="made-up")

    def test_absolute_path_is_rejected(self):
        with self.assertRaises(ValueError):
            add_entry(
                self.store,
                self.root,
                str(self.data / "raw.csv"),
                source="x",
                classification="real",
            )

    def test_missing_source_file_is_rejected(self):
        with self.assertRaises(ValueError):
            add_entry(
                self.store, self.root, "data/gone.csv", source="x", classification="real"
            )

    def test_existing_entry_is_not_overwritten_without_force(self):
        self.add(notes="first")
        with self.assertRaises(ValueError):
            self.add(notes="second")
        self.assertEqual(load_store(self.store)["files"]["data/raw.csv"]["notes"], "first")

    def test_force_allows_rewriting(self):
        self.add(notes="first")
        self.add(notes="second", force=True)
        self.assertEqual(load_store(self.store)["files"]["data/raw.csv"]["notes"], "second")

    def test_classification_list_is_exposed(self):
        self.assertEqual(
            VALID_CLASSIFICATIONS, ("real", "rescaled-real", "documented-substitute")
        )


if __name__ == "__main__":
    unittest.main()
