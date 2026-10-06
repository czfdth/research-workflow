import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import ccfa.compute as compute
from ccfa.compute import (
    Attempt,
    LocalResources,
    RemoteBackend,
    append_attempt,
    load_backends,
    parse_nvidia_smi,
    plan,
    probe_local,
    probe_remote,
    run_local,
    run_remote,
    validate_config,
)


NVIDIA_CSV = (
    "0, NVIDIA GeForce RTX 5060 Laptop GPU, 8151 MiB, 12.0\n"
    "1, NVIDIA A100-SXM4-80GB, 81920 MiB, 8.0\n"
)


class _FakeSlurm:
    """A scripted scheduler reached through the real ssh argv builder.

    ``run`` answers the same commands a cluster's login node would: the upload
    pipe, ``sbatch --parsable``, the exit-code probe, ``scancel`` and the
    stdout fetch. Time is virtual so the budget tests do not sleep.
    """

    def __init__(
        self,
        *,
        job_id: str = "4242",
        exit_code: str | None = "0",
        fail_upload: bool = False,
        fail_submit: bool = False,
        finish_after: int = 2,
        scheduler_forgets: bool = False,
    ) -> None:
        self.job_id = job_id
        self.exit_code = exit_code
        self.fail_upload = fail_upload
        self.fail_submit = fail_submit
        self.finish_after = finish_after
        self.scheduler_forgets = scheduler_forgets
        self.calls: list[str] = []
        self._polls = 0
        self._time = 0.0

    def run(self, argv):
        command = argv[-1]
        self.calls.append(command)
        if "base64 -d" in command:
            return (1, "no space left on device") if self.fail_upload else (0, "")
        if command.startswith("sbatch"):
            if self.fail_submit:
                return (1, "sbatch: error: Invalid partition")
            return (0, f"{self.job_id}\n")
        if "exit-code" in command:
            self._polls += 1
            if self.exit_code is not None and self._polls > self.finish_after:
                return (0, f"{self.exit_code}\n")
            return (1, "")
        if command.startswith("scancel"):
            return (0, "")
        if command.startswith("squeue"):
            return (0, "") if self.scheduler_forgets else (0, "RUNNING\n")
        if "stdout" in command:
            return (0, "hello from the cluster\n")
        return (1, "")

    def sleep(self, seconds):
        self._time += seconds

    def clock(self):
        return self._time


class ParseNvidiaSmiTests(unittest.TestCase):
    def test_parses_one_line_per_gpu(self):
        gpus = parse_nvidia_smi(NVIDIA_CSV)

        self.assertEqual(len(gpus), 2)
        self.assertEqual(gpus[0].name, "NVIDIA GeForce RTX 5060 Laptop GPU")
        self.assertEqual(gpus[0].memory_mib, 8151)
        self.assertEqual(gpus[0].compute_cap, "12.0")
        self.assertEqual(gpus[1].index, 1)

    def test_ignores_header_and_malformed_lines(self):
        raw = "index, name, memory.total, compute_cap\n" + NVIDIA_CSV + "garbage\n"

        gpus = parse_nvidia_smi(raw)

        self.assertEqual([gpu.index for gpu in gpus], [0, 1])

    def test_empty_output_yields_no_gpus(self):
        self.assertEqual(parse_nvidia_smi(""), [])


class ProbeLocalTests(unittest.TestCase):
    def test_reports_gpu_and_docker_nvidia_runtime(self):
        def run(argv):
            if argv[0] == "nvidia-smi":
                return 0, NVIDIA_CSV
            return 0, '{"runc":{}, "nvidia":{"path":"nvidia-container-runtime"}}'

        resources = probe_local(
            which=lambda name: f"/usr/bin/{name}",
            run=run,
            cpu_count=24,
            ram_gib=32.0,
        )

        self.assertEqual(resources.gpu_count, 2)
        self.assertTrue(resources.docker)
        self.assertTrue(resources.docker_gpu)
        self.assertEqual(resources.cpu_count, 24)

    def test_without_nvidia_smi_there_are_no_gpus(self):
        resources = probe_local(
            which=lambda name: "/usr/bin/docker" if name == "docker" else None,
            run=lambda argv: (0, '{"runc": {}}'),
            cpu_count=8,
            ram_gib=16.0,
        )

        self.assertEqual(resources.gpu_count, 0)
        self.assertFalse(resources.docker_gpu)

    def test_failing_nvidia_smi_does_not_raise(self):
        resources = probe_local(
            which=lambda name: "/usr/bin/nvidia-smi",
            run=lambda argv: (1, ""),
            cpu_count=4,
            ram_gib=8.0,
        )

        self.assertEqual(resources.gpu_count, 0)

    def test_docker_gpu_is_false_without_the_nvidia_runtime(self):
        resources = probe_local(
            which=lambda name: "/usr/bin/docker",
            run=lambda argv: (0, '{"runc": {}}'),
            cpu_count=4,
            ram_gib=8.0,
        )

        self.assertTrue(resources.docker)
        self.assertFalse(resources.docker_gpu)


class LoadBackendsTests(unittest.TestCase):
    def test_missing_config_means_no_remote(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_backends(Path(tmp)), [])

    def test_valid_backends_are_parsed_and_invalid_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "compute.yaml").write_text(
                "backends:\n"
                "  - kind: slurm\n"
                "    host: hpc.example.edu\n"
                "    user: alice\n"
                "    partition: gpu\n"
                "    gpus: 4\n"
                "  - kind: kubernetes\n"
                "    host: ignored\n"
                "  - kind: pbs\n"
                "    host: legacy.example.edu\n",
                encoding="utf-8",
            )

            backends = load_backends(root)

        self.assertEqual(len(backends), 2)
        self.assertEqual(backends[0].target, "alice@hpc.example.edu")
        self.assertEqual(backends[0].gpus, 4)
        self.assertEqual(backends[1].kind, "pbs")

    def test_malformed_yaml_is_treated_as_unconfigured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "compute.yaml").write_text("backends: [", encoding="utf-8")
            self.assertEqual(load_backends(root), [])


class PlanTests(unittest.TestCase):
    def _resources(self, gpus=0, docker_gpu=False):
        return (
            LocalResources(cpu_count=8, ram_gib=16.0, gpus=[], docker=True, docker_gpu=docker_gpu)
            if gpus == 0
            else LocalResources(
                cpu_count=8,
                ram_gib=16.0,
                gpus=[compute.Gpu(0, "gpu", 8192, "12.0")],
                docker=True,
                docker_gpu=docker_gpu,
            )
        )

    def test_cpu_pilot_runs_locally(self):
        payload = plan(
            Path("."),
            budget_minutes=10,
            needs_gpu=False,
            resources=self._resources(),
            backends=[],
        )

        self.assertTrue(payload["local"]["usable"])
        self.assertEqual(payload["recommendation"], "local")

    def test_gpu_pilot_without_gpu_or_remote_is_blocked(self):
        payload = plan(
            Path("."),
            budget_minutes=10,
            needs_gpu=True,
            resources=self._resources(),
            backends=[],
        )

        self.assertFalse(payload["local"]["usable"])
        self.assertEqual(payload["recommendation"], "blocked")

    def test_gpu_pilot_uses_local_gpu_when_present(self):
        payload = plan(
            Path("."),
            budget_minutes=30,
            needs_gpu=True,
            resources=self._resources(gpus=1, docker_gpu=True),
            backends=[],
        )

        self.assertTrue(payload["local"]["usable"])
        self.assertTrue(payload["local"]["docker_gpu"])
        self.assertEqual(payload["recommendation"], "local")

    def test_configured_remote_is_recommended(self):
        payload = plan(
            Path("."),
            budget_minutes=30,
            needs_gpu=True,
            resources=self._resources(),
            backends=[RemoteBackend(kind="slurm", host="hpc", user="bob", gpus=8)],
        )

        self.assertTrue(payload["remote_configured"])
        self.assertEqual(payload["recommendation"], "remote")
        self.assertEqual(payload["remote"][0]["host"], "hpc")


class RunLocalTests(unittest.TestCase):
    def test_success_records_wall_time_and_gpu_minutes(self):
        attempt = run_local(
            [sys.executable, "-c", "print('ok')"],
            budget_minutes=1,
            gpus_used=2,
        )

        self.assertEqual(attempt.returncode, 0)
        self.assertFalse(attempt.timed_out)
        self.assertEqual(attempt.backend, "local")
        self.assertGreaterEqual(attempt.wall_seconds, 0.0)
        self.assertAlmostEqual(
            attempt.gpu_minutes,
            round(attempt.wall_seconds / 60.0 * 2, 3),
        )

    def test_command_over_budget_is_killed_and_flagged(self):
        attempt = run_local(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            budget_minutes=1 / 600,  # 0.1 s
        )

        self.assertTrue(attempt.timed_out)
        self.assertLess(attempt.wall_seconds, 15)

    def test_nonzero_exit_is_preserved(self):
        attempt = run_local(
            [sys.executable, "-c", "raise SystemExit(3)"],
            budget_minutes=1,
        )

        self.assertEqual(attempt.returncode, 3)
        self.assertFalse(attempt.timed_out)

    def test_nonpositive_budget_is_rejected(self):
        with self.assertRaises(ValueError):
            run_local([sys.executable, "-c", "pass"], budget_minutes=0)

    def test_attempt_is_appended_as_jsonl(self):
        attempt = Attempt(
            command="python train.py",
            backend="local",
            budget_minutes=5,
            wall_seconds=120.0,
            returncode=0,
            gpus_used=1,
            timed_out=False,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = append_attempt(Path(tmp), attempt)
            lines = path.read_text(encoding="utf-8").strip().splitlines()

        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["gpu_minutes"], 2.0)
        self.assertEqual(record["backend"], "local")
        self.assertRegex(
            record["recorded_at"],
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
        )


class CheckEnvironmentTests(unittest.TestCase):
    def test_no_gpu_and_no_remote_is_advisory_not_blocking(self):
        import unittest.mock as mock

        resources = LocalResources(cpu_count=4, ram_gib=8.0)
        with (
            mock.patch.object(compute, "probe_local", return_value=resources),
            mock.patch.object(compute, "load_backends", return_value=[]),
        ):
            problems, advisories = compute.check_environment(Path("."))

        self.assertEqual(problems, [])
        codes = {advisory.code for advisory in advisories}
        self.assertIn("compute-no-gpu-no-remote", codes)
        self.assertIn("compute-remote-unconfigured", codes)


class ComputeCliTests(unittest.TestCase):
    def test_check_accepts_a_paper_root(self):
        # `compute check` used to hardcode Path("."), so from the repository
        # root it inspected the wrong directory.
        import unittest.mock as mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(
                compute,
                "check_environment",
                return_value=([], []),
            ) as probe:
                code = compute.main(
                    ["compute", "check", "--paper-root", str(root)]
                )

        self.assertEqual(code, 0)
        probe.assert_called_once_with(root)


def _write_config(root: Path, body: str) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "compute.yaml").write_text(body, encoding="utf-8")


class _FakeProcess:
    def __init__(self, returncode=0):
        self.returncode = returncode

    def communicate(self, timeout=None):
        return "", ""

    def kill(self):
        pass


class _TimeoutProcess:
    returncode = -1

    def __init__(self):
        self._raised = False

    def communicate(self, timeout=None):
        if not self._raised:
            self._raised = True
            raise subprocess.TimeoutExpired(cmd="ssh", timeout=timeout)
        return "", ""

    def kill(self):
        pass


def _recording_popen(record, process=None):
    def popen(argv, **kwargs):
        record.append({"argv": list(argv), "kwargs": kwargs})
        return process or _FakeProcess()

    return popen


class SshBackendTests(unittest.TestCase):
    def test_ssh_backend_keeps_optional_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_config(
                root,
                "backends:\n"
                "  - kind: ssh\n"
                "    name: lab-gpu\n"
                "    host: gpu.example.edu\n"
                "    user: alice\n"
                "    port: 2222\n"
                "    workdir: /srv/runs\n"
                "    gpus: 1\n",
            )

            backends = load_backends(root)

        self.assertEqual(len(backends), 1)
        self.assertEqual(backends[0].label, "lab-gpu")
        self.assertEqual(backends[0].target, "alice@gpu.example.edu")
        self.assertEqual(backends[0].port, 2222)
        self.assertEqual(backends[0].workdir, "/srv/runs")
        self.assertTrue(backends[0].executable)

    def test_a_backend_without_a_name_falls_back_to_kind_and_target(self):
        backend = RemoteBackend(kind="ssh", host="h.example", user="bob")

        self.assertEqual(backend.label, "ssh:bob@h.example")

    def test_probe_remote_ssh_reports_the_receipt_and_visible_gpus(self):
        calls = []

        def run(argv):
            calls.append(list(argv))
            return 0, "ccfa-ok\nGPU 0: NVIDIA A100-SXM4-80GB (UUID: GPU-1)\n"

        result = probe_remote(
            RemoteBackend(kind="ssh", host="gpu.example", user="alice", port=2222),
            run=run,
        )

        argv = calls[0]
        self.assertEqual(argv[0], "ssh")
        self.assertIn("BatchMode=yes", argv)
        self.assertEqual(argv[argv.index("-p") + 1], "2222")
        self.assertEqual(argv[-2], "alice@gpu.example")
        self.assertIn("ccfa-ok", argv[-1])
        self.assertTrue(result["reachable"])
        self.assertTrue(result["ccfa_ok"])
        self.assertEqual(result["gpus_observed"], 1)

    def test_probe_remote_ssh_without_the_receipt_is_not_ok(self):
        result = probe_remote(
            RemoteBackend(kind="ssh", host="gpu.example"),
            run=lambda argv: (255, ""),
        )

        self.assertFalse(result["reachable"])
        self.assertFalse(result["ccfa_ok"])
        self.assertEqual(result["gpus_observed"], 0)

    def test_run_remote_builds_one_ssh_call_with_port_and_workdir(self):
        record = []
        backend = RemoteBackend(
            kind="ssh",
            host="gpu.example",
            user="alice",
            port=2222,
            workdir="/srv/runs",
        )

        attempt = run_remote(
            backend,
            ["python", "train.py", "--seed", "1"],
            budget_minutes=5,
            gpus_used=1,
            popen=_recording_popen(record),
        )

        argv = record[0]["argv"]
        self.assertEqual(argv[0], "ssh")
        self.assertEqual(argv[argv.index("-p") + 1], "2222")
        self.assertEqual(argv[-2], "alice@gpu.example")
        self.assertEqual(argv[-1], "cd /srv/runs && python train.py --seed 1")
        self.assertEqual(attempt.backend, "ssh:alice@gpu.example")
        self.assertEqual(attempt.command, "cd /srv/runs && python train.py --seed 1")
        self.assertEqual(attempt.gpus_used, 1)
        self.assertFalse(attempt.timed_out)

    def test_run_remote_that_overruns_the_budget_is_killed_and_flagged(self):
        attempt = run_remote(
            RemoteBackend(kind="ssh", host="gpu.example"),
            ["sleep", "3600"],
            budget_minutes=1,
            popen=_recording_popen([], process=_TimeoutProcess()),
        )

        self.assertTrue(attempt.timed_out)
        self.assertEqual(attempt.returncode, -1)

    def test_run_remote_passes_identity_and_extra_options_before_the_target(self):
        record = []
        backend = RemoteBackend(
            kind="ssh",
            host="h.example",
            user="u",
            identity_file="/keys/id_ed25519",
            options=("-o", "StrictHostKeyChecking=no"),
        )

        run_remote(
            backend,
            ["true"],
            budget_minutes=1,
            popen=_recording_popen(record),
        )

        argv = record[0]["argv"]
        self.assertEqual(argv[argv.index("-i") + 1], "/keys/id_ed25519")
        self.assertIn("StrictHostKeyChecking=no", argv)
        # Options must precede the destination, otherwise ssh reads them as the
        # remote command.
        self.assertLess(
            argv.index("StrictHostKeyChecking=no"),
            argv.index("u@h.example"),
        )

    def test_run_remote_submits_a_slurm_backend_and_records_the_job_id(self):
        cluster = _FakeSlurm()

        attempt = run_remote(
            RemoteBackend(kind="slurm", host="cluster.example", name="cluster"),
            ["python", "train.py"],
            budget_minutes=1,
            gpus_used=1,
            runner=cluster.run,
            sleep=cluster.sleep,
        )

        self.assertEqual(attempt.returncode, 0)
        self.assertEqual(attempt.backend, "slurm:cluster.example")
        self.assertEqual(attempt.scheduler["job_id"], "4242")
        self.assertEqual(attempt.scheduler["state"], "completed")
        self.assertEqual(attempt.gpus_used, 1)
        self.assertTrue(any(call.startswith("sbatch --parsable") for call in cluster.calls))
        self.assertTrue(any("base64 -d" in call for call in cluster.calls))

    def test_run_scheduler_cancels_the_job_when_the_budget_expires(self):
        cluster = _FakeSlurm(exit_code=None)

        attempt = compute.run_scheduler(
            RemoteBackend(kind="slurm", host="cluster.example"),
            ["sleep", "3600"],
            budget_minutes=1,
            poll_seconds=5.0,
            run=cluster.run,
            sleep=cluster.sleep,
            clock=cluster.clock,
        )

        self.assertTrue(attempt.timed_out)
        self.assertEqual(attempt.returncode, -1)
        self.assertEqual(attempt.scheduler["state"], "cancelled")
        self.assertTrue(
            any(call.startswith("scancel 4242") for call in cluster.calls)
        )

    def test_run_scheduler_reports_a_failed_submission(self):
        cluster = _FakeSlurm(fail_submit=True)

        with self.assertRaisesRegex(ValueError, "sbatch 提交失败"):
            compute.run_scheduler(
                RemoteBackend(kind="slurm", host="cluster.example"),
                ["true"],
                budget_minutes=1,
                run=cluster.run,
                sleep=cluster.sleep,
                clock=cluster.clock,
            )

    def test_run_scheduler_stops_when_the_scheduler_no_longer_knows_the_job(self):
        cluster = _FakeSlurm(exit_code=None, scheduler_forgets=True)

        attempt = compute.run_scheduler(
            RemoteBackend(kind="slurm", host="cluster.example"),
            ["python", "train.py"],
            budget_minutes=30,
            run=cluster.run,
            sleep=cluster.sleep,
            clock=cluster.clock,
        )

        self.assertEqual(attempt.scheduler["state"], "gone")
        self.assertEqual(attempt.returncode, -1)
        self.assertFalse(attempt.timed_out)
        self.assertTrue(any(call.startswith("squeue") for call in cluster.calls))

    def test_run_scheduler_reports_a_failed_upload(self):
        cluster = _FakeSlurm(fail_upload=True)

        with self.assertRaisesRegex(ValueError, "上传作业脚本"):
            compute.run_scheduler(
                RemoteBackend(kind="slurm", host="cluster.example"),
                ["true"],
                budget_minutes=1,
                run=cluster.run,
                sleep=cluster.sleep,
                clock=cluster.clock,
            )

    def test_run_remote_rejects_a_nonpositive_budget(self):
        with self.assertRaises(ValueError):
            run_remote(
                RemoteBackend(kind="ssh", host="h.example"),
                ["true"],
                budget_minutes=0,
            )

    def test_remote_argv_overrides_the_backend_workdir(self):
        backend = RemoteBackend(
            kind="ssh",
            host="h.example",
            user="u",
            workdir="/base",
        )

        argv = compute.remote_argv(
            backend,
            ["python", "train.py"],
            workdir="/other",
        )

        self.assertEqual(argv[-1], "cd /other && python train.py")

    def test_remote_argv_refuses_a_pbs_backend(self):
        with self.assertRaisesRegex(ValueError, "kind: ssh"):
            compute.remote_argv(
                RemoteBackend(kind="pbs", host="cluster.example"),
                ["true"],
            )

    def test_remote_argv_refuses_to_flatten_a_slurm_backend(self):
        with self.assertRaisesRegex(ValueError, "sbatch"):
            compute.remote_argv(
                RemoteBackend(kind="slurm", host="cluster.example"),
                ["true"],
            )

    def test_the_job_script_carries_the_workdir_and_the_exit_code(self):
        script = compute._slurm_job_script(
            RemoteBackend(kind="slurm", host="h", workdir="/srv/runs"),
            ["python", "train.py", "--seed", "1"],
            "ccfa-jobs/job-1",
        )

        self.assertIn("cd /srv/runs", script)
        self.assertIn("python train.py --seed 1", script)
        self.assertIn("> ccfa-jobs/job-1/stdout 2>&1", script)
        self.assertIn("echo $? > ccfa-jobs/job-1/exit-code", script)

    def test_load_backend_file_reads_an_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "cluster-compute.yaml"
            config.write_text(
                "backends:\n"
                "  - kind: ssh\n"
                "    name: box\n"
                "    host: box.example\n",
                encoding="utf-8",
            )

            backends, problems = compute.load_backend_file(config)

        self.assertEqual([backend.label for backend in backends], ["box"])
        self.assertEqual(problems, [])


class ValidateConfigTests(unittest.TestCase):
    def test_a_missing_file_has_no_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            backends, problems = validate_config(Path(tmp))

        self.assertEqual(backends, [])
        self.assertEqual(problems, [])

    def test_broken_entries_are_reported_instead_of_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_config(
                root,
                "backends:\n"
                "  - kind: kubernetes\n"
                "    host: ignored\n"
                "  - kind: ssh\n"
                "  - kind: ssh\n"
                "    host: bad-port\n"
                "    port: 70000\n"
                "  - kind: ssh\n"
                "    host: dup-a\n"
                "    name: gpu\n"
                "  - kind: ssh\n"
                "    host: dup-b\n"
                "    name: gpu\n"
                "  - kind: ssh\n"
                "    host: good.example\n"
                "    name: good\n",
            )

            backends, problems = validate_config(root)

        # The first entry keeps the name; the later duplicate is dropped and
        # reported instead of silently creating two backends with one label.
        self.assertEqual([backend.label for backend in backends], ["gpu", "good"])
        codes = {problem.code for problem in problems}
        self.assertIn("compute-backend-unknown-kind", codes)
        self.assertIn("compute-backend-missing-host", codes)
        self.assertIn("compute-config-invalid", codes)
        self.assertIn("compute-backend-duplicate-name", codes)

    def test_malformed_yaml_is_a_problem_not_a_silent_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_config(root, "backends: [")

            backends, problems = validate_config(root)

        self.assertEqual(backends, [])
        self.assertEqual(
            [problem.code for problem in problems],
            ["compute-config-invalid"],
        )

    def test_options_must_be_a_string_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_config(
                root,
                "backends:\n"
                "  - kind: ssh\n"
                "    host: h.example\n"
                "    options:\n"
                "      key: value\n",
            )

            _backends, problems = validate_config(root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["compute-config-invalid"],
        )

    def test_check_environment_turns_a_broken_config_into_a_problem(self):
        import unittest.mock as mock

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_config(root, "backends:\n  - kind: nope\n    host: h\n")
            with mock.patch.object(
                compute,
                "probe_local",
                return_value=LocalResources(cpu_count=4, ram_gib=8.0),
            ):
                problems, _advisories = compute.check_environment(root)

        self.assertEqual(
            [problem.code for problem in problems],
            ["compute-backend-unknown-kind"],
        )


class ComputeRemoteCliTests(unittest.TestCase):
    def test_validate_reports_a_broken_config_with_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_config(root, "backends:\n  - kind: nope\n    host: h\n")

            code = compute.main(
                ["compute", "validate", "--paper-root", str(root)]
            )

        self.assertEqual(code, 1)

    def test_run_with_an_unknown_backend_is_a_tool_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_config(root, "backends: []\n")

            code = compute.main(
                [
                    "compute",
                    "run",
                    "--paper-root",
                    str(root),
                    "--minutes",
                    "1",
                    "--backend",
                    "nope",
                    "--",
                    "true",
                ]
            )

        self.assertEqual(code, 2)

    def test_run_refuses_a_declared_scheduler_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_config(
                root,
                "backends:\n"
                "  - kind: slurm\n"
                "    host: cluster.example\n"
                "    name: cluster\n",
            )

            code = compute.main(
                [
                    "compute",
                    "run",
                    "--paper-root",
                    str(root),
                    "--minutes",
                    "1",
                    "--backend",
                    "cluster",
                    "--",
                    "true",
                ]
            )

        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
