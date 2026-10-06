"""Opt-in end-to-end tests: drive an SSH host with a scripted cluster on it.

The unit tests inject a fake ``run`` callable, which proves the poll loop but
not the transport. This module builds the image in
``tools/tests/fixtures/slurm-e2e`` (a real sshd answering sbatch/squeue/scancel
with shell scripts, plus a scripted ``nvidia-smi``) and drives two real paths
against it:

* ``ccfa compute run --backend <slurm>`` — submission, polling, budget kill;
* ``ccfa.queue`` against a ``kind: ssh`` backend — remote GPU metering, where
  the meter samples the container's nvidia-smi over ssh.

It is skipped unless ``CCFA_SLURM_E2E=1`` because it needs a Docker daemon and
OpenSSH, and because it is minutes, not milliseconds.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from ccfa import compute
from ccfa import queue

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "slurm-e2e"
IMAGE = "ccfa-slurm-e2e:test"
SSH_READY_TIMEOUT_S = 60.0


def _docker(*args: str, timeout: float = 600.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


@unittest.skipUnless(
    os.environ.get("CCFA_SLURM_E2E") == "1",
    "set CCFA_SLURM_E2E=1 to run the container-backed scheduler test",
)
class HpcEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("docker") is None:
            raise unittest.SkipTest("docker is not installed")
        if shutil.which("ssh") is None or shutil.which("ssh-keygen") is None:
            raise unittest.SkipTest("OpenSSH client tools are not installed")
        probe = _docker("info", "--format", "{{.ServerVersion}}", timeout=60)
        if probe.returncode != 0:
            raise unittest.SkipTest("docker daemon is not reachable")

        build = _docker(
            "build",
            "--build-arg",
            f"APK_MIRROR={os.environ.get('CCFA_APK_MIRROR', 'dl-cdn.alpinelinux.org')}",
            "-t",
            IMAGE,
            str(FIXTURE),
            timeout=900,
        )
        if build.returncode != 0:
            raise AssertionError(f"docker build failed:\n{build.stderr[-2000:]}")

        cls.tempdir = tempfile.TemporaryDirectory()
        cls.workspace = Path(cls.tempdir.name)
        cls.key = cls.workspace / "id_ed25519"
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-f", str(cls.key)],
            check=True,
            capture_output=True,
        )
        cls.container = f"ccfa-slurm-e2e-{os.getpid()}"
        started = _docker(
            "run",
            "-d",
            "--name",
            cls.container,
            "-p",
            "127.0.0.1::22",
            "-v",
            f"{cls.key}.pub:/opt/authorized_keys:ro",
            IMAGE,
        )
        if started.returncode != 0:
            raise AssertionError(f"docker run failed:\n{started.stderr[-2000:]}")
        port = _docker("port", cls.container, "22", timeout=60).stdout.strip()
        if not port:
            raise AssertionError("cannot resolve the container's ssh port")
        cls.port = int(port.rsplit(":", 1)[1])
        cls.paper_root = cls.workspace / "paper"
        (cls.paper_root / "data").mkdir(parents=True)
        (cls.paper_root / "experiments" / "log").mkdir(parents=True)
        (cls.paper_root / "data" / "compute.yaml").write_text(
            "backends:\n"
            "  - kind: slurm\n"
            "    name: cluster\n"
            "    host: 127.0.0.1\n"
            "    user: root\n"
            f"    port: {cls.port}\n"
            f"    identity_file: {cls.key}\n"
            "    workdir: /work\n"
            "    partition: batch\n"
            "    options:\n"
            "      - -o\n"
            "      - StrictHostKeyChecking=no\n"
            "      - -o\n"
            "      - UserKnownHostsFile=/dev/null\n",
            encoding="utf-8",
        )
        cls._wait_for_sshd()

    @classmethod
    def _wait_for_sshd(cls) -> None:
        deadline = time.monotonic() + SSH_READY_TIMEOUT_S
        last = None
        while time.monotonic() < deadline:
            last = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=/dev/null",
                    "-o",
                    "ConnectTimeout=3",
                    "-i",
                    str(cls.key),
                    "-p",
                    str(cls.port),
                    "root@127.0.0.1",
                    "true",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            if last.returncode == 0:
                return
            time.sleep(2)
        raise AssertionError(f"sshd never became reachable: {last.stderr[-500:] if last else ''}")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "container", None):
            _docker("rm", "-f", cls.container, timeout=120)
        if getattr(cls, "tempdir", None):
            cls.tempdir.cleanup()

    def _ledger(self) -> list[dict]:
        path = self.paper_root / "experiments" / "log" / "compute-ledger.jsonl"
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_a_slurm_job_round_trips_and_lands_in_the_ledger(self):
        exit_code = compute.main(
            [
                "compute",
                "run",
                "--paper-root",
                str(self.paper_root),
                "--minutes",
                "2",
                "--backend",
                "cluster",
                "--",
                "sh",
                "-c",
                "echo hello-from-slurm",
            ]
        )

        self.assertEqual(exit_code, 0)
        entries = self._ledger()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["backend"], "slurm:root@127.0.0.1")
        self.assertEqual(entry["returncode"], 0)
        self.assertFalse(entry["timed_out"])
        self.assertTrue(entry["scheduler"]["job_id"].isdigit())
        self.assertEqual(entry["scheduler"]["job_name"][:5], "ccfa-")
        self.assertIn("hello-from-slurm", entry["scheduler"]["stdout_tail"])

    def test_the_budget_kill_cancels_the_job_and_records_the_timeout(self):
        exit_code = compute.main(
            [
                "compute",
                "run",
                "--paper-root",
                str(self.paper_root),
                "--minutes",
                "0.1",
                "--backend",
                "cluster",
                "--",
                "sleep",
                "120",
            ]
        )

        self.assertEqual(exit_code, 1)
        entry = self._ledger()[-1]
        self.assertTrue(entry["timed_out"])
        self.assertEqual(entry["returncode"], -1)
        self.assertEqual(entry["scheduler"]["state"], "cancelled")

    def _ssh_compute_config(self) -> Path:
        """A ``kind: ssh`` backend pointing at the same container."""

        path = self.paper_root / "data" / "compute-ssh.yaml"
        path.write_text(
            "backends:\n"
            "  - kind: ssh\n"
            "    name: box\n"
            "    host: 127.0.0.1\n"
            "    user: root\n"
            f"    port: {self.port}\n"
            f"    identity_file: {self.key}\n"
            "    workdir: /work\n"
            "    options:\n"
            "      - -o\n"
            "      - StrictHostKeyChecking=no\n"
            "      - -o\n"
            "      - UserKnownHostsFile=/dev/null\n",
            encoding="utf-8",
        )
        return path

    def test_the_queue_meters_remote_gpu_seconds_and_stops_on_budget(self):
        config = self._ssh_compute_config()
        manifest = self.paper_root / "queue.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "queue": [
                        {
                            "name": "train",
                            "command": ["sh", "-c", "sleep 8"],
                            "timeout_s": 60,
                        },
                        {
                            "name": "second",
                            "command": ["echo", "second"],
                            "timeout_s": 60,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        log_dir = self.paper_root / "experiments" / "log-queue"

        result = queue.run_queue(
            manifest,
            log_dir=log_dir,
            backend="box",
            compute_config=config,
            gpu_budget_s=0.5,
        )

        self.assertEqual(result["stopped"], "gpu-budget")
        self.assertEqual(result["runs"][1]["status"], "skipped-gpu-budget")
        record = json.loads(
            sorted(log_dir.glob("*.json"))[0].read_text(encoding="utf-8")
        )
        usage = record["resource_usage"]
        self.assertGreater(usage["gpu_seconds"], 0)
        self.assertGreaterEqual(usage["gpu_samples"], 1)


if __name__ == "__main__":
    unittest.main()
