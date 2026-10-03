import json
import tempfile
import unittest
from pathlib import Path

from ccfa.repro_package import (
    MANIFEST_NAME,
    build_manifest,
    create_bundle,
    load_manifest,
    sha256_of,
)


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "src").mkdir()
        (self.root / "src" / "train.py").write_text("print('train')\n", encoding="utf-8")
        (self.root / "configs").mkdir()
        (self.root / "configs" / "a.yaml").write_text("epochs: 5\n", encoding="utf-8")
        (self.root / "requirements.txt").write_text("numpy\n", encoding="utf-8")
        self.out = self.root / "bundles" / "result3"

    def manifest(self, **overrides):
        kwargs = dict(
            paper_root=self.root,
            files=["src/train.py", "configs/a.yaml"],
            command=["{python}", "src/train.py", "--config", "configs/a.yaml"],
            requirements="requirements.txt",
            notes="Table 3",
        )
        kwargs.update(overrides)
        return build_manifest(**kwargs)


class TestBuildManifest(BaseCase):
    def test_records_files_sorted_with_hashes_and_sizes(self):
        manifest = self.manifest()
        self.assertEqual([item["path"] for item in manifest["files"]], ["configs/a.yaml", "src/train.py"])
        first = manifest["files"][0]
        self.assertEqual(first["sha256"], sha256_of(self.root / "configs" / "a.yaml"))
        self.assertEqual(first["size"], (self.root / "configs" / "a.yaml").stat().st_size)

    def test_records_command_verbatim_as_argv(self):
        manifest = self.manifest()
        self.assertEqual(manifest["command"][0], "{python}")
        self.assertEqual(manifest["command"][2], "--config")

    def test_records_requirements_hash(self):
        manifest = self.manifest()
        self.assertEqual(manifest["requirements"]["path"], "requirements.txt")
        self.assertTrue(manifest["requirements"]["sha256"].startswith("sha256:"))

    def test_requirements_is_null_when_absent(self):
        self.assertIsNone(self.manifest(requirements=None)["requirements"])

    def test_absolute_path_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manifest(files=[str(self.root / "src" / "train.py")])

    def test_parent_escape_is_rejected(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("x\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.manifest(files=["../outside.txt"])

    def test_missing_file_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manifest(files=["src/gone.py"])

    def test_version_is_one_and_platform_is_recorded(self):
        manifest = self.manifest()
        self.assertEqual(manifest["version"], 1)
        self.assertIn("python", manifest)
        self.assertIn("platform", manifest)
        self.assertIn("created_at", manifest)


class TestCreateBundle(BaseCase):
    def test_copies_files_preserving_structure(self):
        create_bundle(self.root, self.out, self.manifest())
        self.assertTrue((self.out / "files" / "src" / "train.py").is_file())
        self.assertTrue((self.out / "files" / "configs" / "a.yaml").is_file())

    def test_writes_a_readable_manifest(self):
        create_bundle(self.root, self.out, self.manifest())
        loaded = load_manifest(self.out)
        self.assertEqual(loaded["version"], 1)
        self.assertEqual(len(loaded["files"]), 2)

    def test_manifest_hashes_match_the_copied_bytes(self):
        create_bundle(self.root, self.out, self.manifest())
        loaded = load_manifest(self.out)
        for item in loaded["files"]:
            self.assertEqual(sha256_of(self.out / "files" / item["path"]), item["sha256"])

    def test_existing_bundle_is_not_overwritten_without_force(self):
        create_bundle(self.root, self.out, self.manifest())
        (self.out / "KEEP").write_text("keep\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            create_bundle(self.root, self.out, self.manifest())
        self.assertTrue((self.out / "KEEP").is_file())

    def test_force_rebuilds_the_bundle(self):
        create_bundle(self.root, self.out, self.manifest())
        (self.out / "KEEP").write_text("keep\n", encoding="utf-8")
        create_bundle(self.root, self.out, self.manifest(), force=True)
        self.assertFalse((self.out / "KEEP").is_file())
        self.assertTrue((self.out / MANIFEST_NAME).is_file())

    def test_missing_manifest_version_is_rejected(self):
        bad = self.manifest()
        del bad["version"]
        with self.assertRaises(ValueError):
            create_bundle(self.root, self.out, bad)


if __name__ == "__main__":
    unittest.main()
