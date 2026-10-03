import json
import tempfile
import unittest
from pathlib import Path

from ccfa.citation_ledger import VALID_STATUSES, load_ledger

GOOD = {
    "version": 1,
    "entries": {
        "vaswani2017attention": {
            "doi": "10.48550/arxiv.1706.03762",
            "status": "verified",
            "verified_at": "2026-10-03T12:00:00Z",
            "source": "crossref",
        }
    },
}


def _ledger(payload) -> Path:
    path = Path(tempfile.mkdtemp()) / "citation-ledger.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestLoadLedger(unittest.TestCase):
    def test_loads_a_valid_ledger(self):
        records = load_ledger(_ledger(GOOD))
        record = records["vaswani2017attention"]
        self.assertEqual(record.status, "verified")
        self.assertEqual(record.source, "crossref")
        self.assertEqual(record.doi, "10.48550/arxiv.1706.03762")

    def test_doi_is_normalized(self):
        payload = json.loads(json.dumps(GOOD))
        payload["entries"]["vaswani2017attention"]["doi"] = "https://doi.org/10.1/MiXeD"
        records = load_ledger(_ledger(payload))
        self.assertEqual(records["vaswani2017attention"].doi, "10.1/mixed")

    def test_empty_entries_is_valid(self):
        self.assertEqual(load_ledger(_ledger({"version": 1, "entries": {}})), {})

    def test_missing_file_raises(self):
        with self.assertRaises(ValueError):
            load_ledger(Path(tempfile.mkdtemp()) / "nope.json")

    def test_invalid_json_raises(self):
        path = Path(tempfile.mkdtemp()) / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_ledger(path)

    def test_missing_version_raises(self):
        with self.assertRaises(ValueError):
            load_ledger(_ledger({"entries": {}}))

    def test_entries_must_be_a_mapping(self):
        with self.assertRaises(ValueError):
            load_ledger(_ledger({"version": 1, "entries": []}))

    def test_record_must_be_a_mapping(self):
        with self.assertRaises(ValueError):
            load_ledger(_ledger({"version": 1, "entries": {"k": "verified"}}))

    def test_unknown_status_raises(self):
        payload = {"version": 1, "entries": {"k": {"status": "maybe"}}}
        with self.assertRaises(ValueError):
            load_ledger(_ledger(payload))

    def test_all_declared_statuses_are_accepted(self):
        for status in VALID_STATUSES:
            with self.subTest(status=status):
                payload = {
                    "version": 1,
                    "entries": {"k": {"status": status, "verified_at": "", "source": ""}},
                }
                self.assertEqual(load_ledger(_ledger(payload))["k"].status, status)
