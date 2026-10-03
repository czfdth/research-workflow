import hashlib
import tempfile
import unittest
from pathlib import Path

from ccfa.figure_manifest import check_manifest, load_manifest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 8


class TestLoadManifest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _write(self, body: str) -> Path:
        path = self.root / "manifest.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_loads_a_list_of_dicts(self):
        items = load_manifest(self._write("- name: a\n  bytes_format: png\n"))
        self.assertEqual(items[0]["name"], "a")

    def test_empty_file_is_an_empty_list(self):
        self.assertEqual(load_manifest(self._write("")), [])

    def test_top_level_must_be_a_list(self):
        with self.assertRaises(ValueError):
            load_manifest(self._write("name: a\n"))

    def test_each_item_must_be_an_object(self):
        with self.assertRaises(ValueError):
            load_manifest(self._write("- just-a-string\n"))

    def test_malformed_yaml_raises_value_error(self):
        with self.assertRaises(ValueError):
            load_manifest(self._write("- name: [unclosed\n"))

    def test_missing_file_raises_value_error(self):
        with self.assertRaises(ValueError):
            load_manifest(self.root / "gone.yaml")


class TestCheckManifest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.figures = self.root / "figures"
        self.figures.mkdir()

    def _item(self, **overrides):
        item = {
            "name": "plot",
            "file": "figures/plot.png",
            "bytes_format": "png",
            "generator": "src/plot.py",
            "generator_hash": "",
            "referenced_in": ["manuscript/main.tex:1"],
        }
        item.update(overrides)
        return item

    def _write_generator(self, body: str = "print('x')\n") -> str:
        path = self.root / "src" / "plot.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def test_consistent_entry_is_clean(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(generator_hash=self._write_generator())
        problems, advisories = check_manifest([item], self.root)
        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_declared_format_mismatch_is_reported(self):
        (self.figures / "plot.png").write_bytes(JPEG)
        item = self._item(generator_hash=self._write_generator())
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-manifest-format", [p.code for p in problems])

    def test_generator_hash_mismatch_is_reported(self):
        (self.figures / "plot.png").write_bytes(PNG)
        self._write_generator()
        item = self._item(generator_hash="sha256:deadbeef")
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-hash", [p.code for p in problems])
        self.assertIn("哈希不符", problems[0].message)
        self.assertNotIn("不存在", problems[0].message)

    def test_missing_generator_script_is_reported(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(generator="src/gone.py", generator_hash="sha256:x")
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-hash", [p.code for p in problems])

    def test_missing_delivered_figure_is_reported(self):
        item = self._item(generator_hash=self._write_generator())
        problems, _ = check_manifest([item], self.root)
        self.assertIn("figure-missing", [p.code for p in problems])

    def test_absent_file_field_falls_back_and_warns(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(generator_hash=self._write_generator())
        del item["file"]
        problems, advisories = check_manifest([item], self.root)
        self.assertEqual([p.code for p in advisories], ["manifest-missing-file"])
        self.assertNotIn("figure-missing", [p.code for p in problems])

    def test_empty_referenced_in_is_an_advisory(self):
        (self.figures / "plot.png").write_bytes(PNG)
        item = self._item(generator_hash=self._write_generator(), referenced_in=[])
        problems, advisories = check_manifest([item], self.root)
        self.assertEqual(problems, [])
        self.assertIn("unreferenced-figure", [p.code for p in advisories])


if __name__ == "__main__":
    unittest.main()
