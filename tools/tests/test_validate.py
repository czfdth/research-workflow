import tempfile
import unittest
from pathlib import Path

from ccfa.validate import validate_yaml

VALID = """\
version: "0.4.0"
project:
  title: "Demo"
  short_name: "demo"
  root: "."
target_venue:
  name: "NeurIPS"
  year: "2027"
  mode: "conference"
stage:
  current: "idea"
  gate: "scope_defined"
  updated_at: "2026-10-03"
artifacts:
  manuscript: "manuscript/main.tex"
  bibliography: "manuscript/references.bib"
claims: []
experiments: []
reviews: []
revision_ledger:
  path: "reviews/revision-ledger.md"
  status: "not_started"
submission_checks:
  path: "submission/checks.md"
  status: "not_started"
"""


def _write(text: str) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "ccfa.yaml"
    tmp.write_text(text, encoding="utf-8")
    return tmp


class TestValidateYaml(unittest.TestCase):
    def test_valid_file_has_no_problems(self):
        self.assertEqual(validate_yaml(_write(VALID)), [])

    def test_missing_required_top_level_field(self):
        broken = VALID.replace("claims: []\n", "")
        problems = validate_yaml(_write(broken))
        self.assertTrue(any("claims" in p for p in problems), problems)

    def test_invalid_mode_is_reported(self):
        broken = VALID.replace('mode: "conference"', 'mode: "workshop"')
        problems = validate_yaml(_write(broken))
        self.assertTrue(any("mode" in p for p in problems), problems)

    def test_invalid_stage_for_conference_mode(self):
        broken = VALID.replace('current: "idea"', 'current: "major-revision"')
        problems = validate_yaml(_write(broken))
        self.assertTrue(any("major-revision" in p for p in problems), problems)

    def test_unparsable_yaml_raises_not_returns(self):
        with self.assertRaises(ValueError):
            validate_yaml(_write("version: [unclosed\n"))

    def test_non_mapping_target_venue_reports_instead_of_crashing(self):
        broken = VALID.replace(
            'target_venue:\n  name: "NeurIPS"\n  year: "2027"\n  mode: "conference"\n',
            'target_venue: "not-a-mapping"\n',
        )
        problems = validate_yaml(_write(broken))
        self.assertIn("target_venue 必须是映射", problems)

    def test_missing_or_null_deadline_is_valid(self):
        without = VALID
        with_null = VALID.replace(
            '  mode: "conference"\n',
            '  mode: "conference"\n  deadline: null\n',
        )
        self.assertEqual(validate_yaml(_write(without)), [])
        self.assertEqual(validate_yaml(_write(with_null)), [])

    def test_invalid_deadline_format_and_calendar_are_reported(self):
        for value in ("2027-5-1", "2027-02-30"):
            with self.subTest(value=value):
                broken = VALID.replace(
                    '  mode: "conference"\n',
                    f'  mode: "conference"\n  deadline: "{value}"\n',
                )
                problems = validate_yaml(_write(broken))
                self.assertTrue(
                    any("deadline" in problem for problem in problems),
                    problems,
                )
