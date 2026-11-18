import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from ccfa.repro_container import DEFAULT_IMAGE, verify_container
from ccfa.repro_package import build_manifest, create_bundle


PINNED = "python@sha256:" + "a" * 64


class ReproContainerTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.paper = Path(self._temporary.name)
        (self.paper / "src").mkdir()
        (self.paper / "src" / "main.py").write_text(
            "print('reproduced')\n",
            encoding="utf-8",
        )
        manifest = build_manifest(
            self.paper,
            ["src/main.py"],
            ["{python}", "src/main.py"],
            None,
            "test bundle",
        )
        self.bundle = self.paper / "bundle"
        create_bundle(self.paper, self.bundle, manifest)

    def test_default_image_is_digest_pinned(self):
        self.assertIn("@sha256:", DEFAULT_IMAGE)

    def test_unpinned_image_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "sha256"):
            verify_container(self.bundle, image="python:3.12-slim")

    def test_successful_run_writes_receipt(self):
        seen = {}

        def runner(argv, *, timeout):
            seen["argv"] = list(argv)
            return 0, "reproduced\n", ""

        receipt = {}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "receipt.json"
            receipt = verify_container(
                self.bundle,
                image=PINNED,
                out_path=out,
                runner=runner,
            )
            loaded = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(receipt["status"], "pass")
        self.assertEqual(loaded["status"], "pass")
        self.assertEqual(loaded["exit_code"], 0)
        self.assertEqual(loaded["network"], "none")
        self.assertIn("python", seen["argv"])
        self.assertNotIn("{python}", seen["argv"])
        self.assertTrue(loaded["output_sha256"].startswith("sha256:"))

    def test_copied_workspace_is_writable_without_root_capabilities(self):
        if os.name != "posix":
            self.skipTest("POSIX mode bits are not enforced on Windows")
        seen = {}

        def runner(argv, *, timeout):
            mount = argv[argv.index("--mount") + 1]
            source = Path(mount.split("source=", 1)[1].split(",", 1)[0])
            seen["file_mode"] = stat.S_IMODE((source / "src/main.py").stat().st_mode)
            seen["dir_mode"] = stat.S_IMODE(source.stat().st_mode)
            return 0, "", ""

        verify_container(self.bundle, image=PINNED, runner=runner)

        self.assertTrue(
            seen["file_mode"] & stat.S_IWOTH,
            f"bundle file is not world-writable: {seen['file_mode']:o}",
        )
        self.assertTrue(
            seen["dir_mode"] & (stat.S_IWOTH | stat.S_IXOTH),
            f"bundle directory is not traversable/writable: {seen['dir_mode']:o}",
        )

    def test_nonzero_exit_is_a_failure_receipt(self):
        receipt = verify_container(
            self.bundle,
            image=PINNED,
            runner=lambda argv, *, timeout: (7, "", "boom\n"),
        )

        self.assertEqual(receipt["status"], "fail")
        self.assertEqual(receipt["exit_code"], 7)
        self.assertIn("boom", receipt["stderr_tail"])


if __name__ == "__main__":
    unittest.main()
