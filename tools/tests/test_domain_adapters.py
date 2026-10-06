"""The domain-adaptation packs: venues, search terms and required elements."""

import io
import contextlib
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa import domain_adapters


def _write_plan(root: Path, payload: dict) -> Path:
    path = root / "research-plan.yaml"
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def _complete_plan(domain: str) -> dict:
    return {
        key: f"concrete value for {key}"
        for key, _description in domain_adapters.get_domain(domain)[
            "required_elements"
        ]
    }


class PackTests(unittest.TestCase):
    def test_three_domains_are_registered(self):
        self.assertEqual(
            domain_adapters.domain_ids(),
            ["architecture-eda", "communications", "robotics"],
        )

    def test_every_pack_declares_venues_terms_and_elements(self):
        for key in domain_adapters.domain_ids():
            with self.subTest(domain=key):
                pack = domain_adapters.get_domain(key)
                self.assertTrue(pack["venues"])
                self.assertTrue(pack["search_terms"])
                self.assertTrue(pack["required_elements"])
                self.assertEqual(pack["id"], key)
                self.assertTrue(pack["pilot_mode"])

    def test_an_unknown_domain_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "未知领域"):
            domain_adapters.get_domain("astrology")

    def test_domain_lookup_is_case_insensitive(self):
        self.assertEqual(
            domain_adapters.get_domain("Robotics")["id"], "robotics"
        )

    def test_render_prompt_names_every_required_element(self):
        text = domain_adapters.render_prompt("communications")

        for key, _description in domain_adapters.get_domain("communications")[
            "required_elements"
        ]:
            self.assertIn(f"`{key}`", text)
        self.assertIn("SIGCOMM", text)


class CheckPlanTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_a_complete_plan_has_no_problems(self):
        path = _write_plan(self.root, _complete_plan("robotics"))

        problems, advisories = domain_adapters.check_plan(path, "robotics")

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_a_missing_required_element_fails_closed(self):
        payload = _complete_plan("communications")
        del payload["channel_model"]
        path = _write_plan(self.root, payload)

        problems, _advisories = domain_adapters.check_plan(
            path, "communications"
        )

        self.assertEqual([p.code for p in problems], ["domain-element-missing"])
        self.assertIn("channel_model", problems[0].message)

    def test_a_placeholder_element_is_rejected(self):
        payload = _complete_plan("architecture-eda")
        payload["technology_node"] = "TODO"
        path = _write_plan(self.root, payload)

        problems, _advisories = domain_adapters.check_plan(
            path, "architecture-eda"
        )

        self.assertEqual([p.code for p in problems], ["domain-element-placeholder"])

    def test_an_empty_element_is_rejected(self):
        payload = _complete_plan("robotics")
        payload["embodiment"] = ""
        path = _write_plan(self.root, payload)

        problems, _advisories = domain_adapters.check_plan(path, "robotics")

        self.assertEqual([p.code for p in problems], ["domain-element-placeholder"])

    def test_an_off_list_venue_is_only_an_advisory(self):
        payload = _complete_plan("robotics")
        payload["venues"] = ["CoRL", "Journal of Vibes"]
        path = _write_plan(self.root, payload)

        problems, advisories = domain_adapters.check_plan(path, "robotics")

        self.assertEqual(problems, [])
        self.assertEqual([a.code for a in advisories], ["domain-venue-off-list"])

    def test_a_missing_plan_file_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "找不到 research plan"):
            domain_adapters.check_plan(self.root / "nope.yaml", "robotics")

    def test_a_non_mapping_plan_is_an_error(self):
        path = self.root / "plan.yaml"
        path.write_text("- a\n- b\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "顶层必须是映射"):
            domain_adapters.check_plan(path, "robotics")


class CliTests(unittest.TestCase):
    def _run(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = domain_adapters.main(["domain-adapters", *argv])
        return code, stdout.getvalue()

    def test_list_prints_the_three_domains(self):
        code, output = self._run(["list"])

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(
            [item["id"] for item in payload],
            ["architecture-eda", "communications", "robotics"],
        )

    def test_show_prints_the_pack(self):
        code, output = self._run(["show", "--domain", "communications"])

        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertIn("INFOCOM", payload["venues"])
        self.assertEqual(payload["schema_version"], 1)

    def test_check_returns_one_when_an_element_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_plan(Path(tmp), _complete_plan("robotics"))
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            del payload["evaluation"]
            path.write_text(yaml.safe_dump(payload), encoding="utf-8")

            code, _output = self._run(
                ["check", "--domain", "robotics", "--plan", str(path)]
            )

        self.assertEqual(code, 1)

    def test_check_returns_zero_for_a_complete_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_plan(Path(tmp), _complete_plan("robotics"))

            code, _output = self._run(
                ["check", "--domain", "robotics", "--plan", str(path)]
            )

        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
