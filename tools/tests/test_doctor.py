import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ccfa.doctor as doctor_module
from ccfa.doctor import (
    DEPENDENCIES,
    Dependency,
    Venv,
    check_environment,
    main,
)


def _locator(available):
    def which(name):
        return available.get(name)

    return which


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _all_available(self):
        found = {dep.key: f"/usr/bin/{dep.key}" for dep in DEPENDENCIES}
        for dep in DEPENDENCIES:
            found[dep.executables[0]] = f"/usr/bin/{dep.executables[0]}"
        return found

    def _check(self, available, *, strict=False, venvs=()):
        return check_environment(
            self.root,
            which=_locator(available),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=venvs,
            strict=strict,
            run=lambda argv: 0,
        )

    @staticmethod
    def _codes(problems):
        return sorted(problem.code for problem in problems)

    def test_all_present_reports_nothing(self):
        problems, advisories, statuses = self._check(self._all_available())

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])
        self.assertTrue(any("git" in line for line in statuses))

    def test_missing_required_command_is_a_problem(self):
        available = self._all_available()
        del available["git"]

        problems, advisories, _statuses = self._check(available)

        self.assertEqual(self._codes(problems), ["doctor-missing-command"])
        messages = " ".join(problem.message for problem in problems)
        self.assertIn("git", messages)
        self.assertIn("版本", messages)
        self.assertEqual(advisories, [])

    def test_missing_optional_command_is_an_advisory(self):
        available = self._all_available()
        del available["docker"]

        problems, advisories, _statuses = self._check(available)

        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["doctor-missing-command"])
        messages = " ".join(advisory.message for advisory in advisories)
        self.assertIn("docker", messages)
        self.assertIn("沙箱", messages)

    def test_strict_promotes_optional_commands_to_problems(self):
        available = self._all_available()
        del available["docker"]

        problems, advisories, _statuses = self._check(available, strict=True)

        self.assertEqual(self._codes(problems), ["doctor-missing-command"])
        self.assertEqual(advisories, [])

    def test_command_aliases_are_tried_in_order(self):
        dependency = Dependency(
            key="tex",
            executables=("pdflatex", "latex"),
            required=False,
            capability="排版",
        )
        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator({"latex": "/usr/bin/latex"}),
            path_exists=lambda path: False,
            dependencies=(dependency,),
            venvs=(),
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_missing_venv_is_reported(self):
        venv = Venv(key="tools", relative="tools/.venv", capability="包装器")

        problems, advisories, statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(venv,),
            run=lambda argv: 0,
        )

        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["doctor-missing-venv"])
        self.assertIn("tools/.venv", advisories[0].message)
        self.assertIn("tools/.venv", " ".join(statuses))

    def test_present_venv_is_not_reported(self):
        venv = Venv(key="tools", relative="tools/.venv", capability="包装器")
        marker = self.root / "tools" / ".venv" / "bin" / "python"

        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: path == marker,
            dependencies=DEPENDENCIES,
            venvs=(venv,),
            run=lambda argv: 0,
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_docker_daemon_down_is_an_advisory(self):
        calls = []

        def run(argv):
            calls.append(argv)
            return 1

        problems, advisories, statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(),
            run=run,
        )

        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["doctor-daemon-down"])
        self.assertTrue(any("docker" in call[0] for call in calls))
        self.assertIn("daemon", " ".join(statuses))

    def test_docker_daemon_up_is_not_reported(self):
        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(),
            run=lambda argv: 0,
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_docker_daemon_check_is_skipped_when_binary_is_missing(self):
        available = self._all_available()
        del available["docker"]

        def run(argv):  # pragma: no cover - must not be called
            raise AssertionError("daemon probe ran without a docker binary")

        _problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(available),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(),
            run=run,
        )

        self.assertEqual(self._codes(advisories), ["doctor-missing-command"])

    def test_strict_promotes_a_daemon_down_to_a_problem(self):
        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(),
            run=lambda argv: 1,
            strict=True,
        )

        self.assertEqual(self._codes(problems), ["doctor-daemon-down"])
        self.assertEqual(advisories, [])

    def test_windows_venv_layout_is_recognised(self):
        venv = Venv(key="tools", relative="tools/.venv", capability="包装器")
        marker = self.root / "tools" / ".venv" / "Scripts" / "python.exe"

        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: path == marker,
            dependencies=DEPENDENCIES,
            venvs=(venv,),
            run=lambda argv: 0,
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_default_run_treats_a_timeout_as_failure(self):
        with mock.patch.object(
            doctor_module.subprocess,
            "run",
            side_effect=doctor_module.subprocess.TimeoutExpired(
                ["docker", "info"], 15
            ),
        ):
            self.assertEqual(
                doctor_module._default_run(["docker", "info"]),
                1,
            )

    def test_default_run_treats_a_missing_binary_as_failure(self):
        with mock.patch.object(
            doctor_module.subprocess,
            "run",
            side_effect=OSError("gone"),
        ):
            self.assertEqual(
                doctor_module._default_run(["docker", "info"]),
                1,
            )

    def test_injected_runner_exception_is_reported_not_raised(self):
        def run(argv):
            raise RuntimeError("boom")

        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            path_exists=lambda path: False,
            dependencies=DEPENDENCIES,
            venvs=(),
            run=run,
        )

        self.assertEqual(problems, [])
        self.assertEqual(self._codes(advisories), ["doctor-daemon-down"])

    def test_plain_command_status_says_found_not_ok(self):
        _problems, _advisories, statuses = self._check(self._all_available())

        git_line = next(line for line in statuses if "git" in line)
        self.assertTrue(git_line.startswith("found"))

    def test_default_path_check_rejects_an_empty_interpreter(self):
        venv = Venv(key="tools", relative="tools/.venv", capability="包装器")
        marker = self.root / "tools" / ".venv" / "bin" / "python"
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b"")

        _problems, advisories, statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            dependencies=(),
            venvs=(venv,),
        )

        self.assertEqual(self._codes(advisories), ["doctor-missing-venv"])
        self.assertIn("MISSING", " ".join(statuses))

    def test_default_path_check_accepts_a_nonempty_interpreter(self):
        venv = Venv(key="tools", relative="tools/.venv", capability="包装器")
        marker = self.root / "tools" / ".venv" / "bin" / "python"
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b"#!/bin/sh\n")

        problems, advisories, _statuses = check_environment(
            self.root,
            which=_locator(self._all_available()),
            dependencies=(),
            venvs=(venv,),
        )

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_main_prints_json_and_exits_zero_when_only_optional_missing(self):
        available = self._all_available()
        del available["docker"]
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            stderr
        ):
            code = main(
                ["doctor", "--repo-root", str(self.root)],
                which=_locator(available),
                path_exists=lambda path: False,
                dependencies=DEPENDENCIES,
                venvs=(),
                run=lambda argv: 0,
            )

        self.assertEqual(code, 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["problem_count"], 0)
        self.assertEqual(
            [item["code"] for item in report["advisories"]],
            ["doctor-missing-command"],
        )

    def test_main_strict_exits_one_and_prints_missing_optional(self):
        available = self._all_available()
        del available["docker"]
        stdout = io.StringIO()
        stderr = io.StringIO()

        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
            stderr
        ):
            code = main(
                ["doctor", "--repo-root", str(self.root), "--strict"],
                which=_locator(available),
                path_exists=lambda path: False,
                dependencies=DEPENDENCIES,
                venvs=(),
                run=lambda argv: 0,
            )

        self.assertEqual(code, 1)
        self.assertIn("docker", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
