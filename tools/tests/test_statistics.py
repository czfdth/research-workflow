import tempfile
import unittest
from pathlib import Path

from ccfa.stats_plan import check

VALID = """\
version: 1
alpha: 0.05
multiple_comparison: holm-bonferroni
claims:
  - id: claim:main
    endpoint: accuracy
    test: paired t-test
    effect_size: 0.5
    target_power: 0.8
    sample_size: 30
    seeds: [0, 1, 2]
    stopping_rule: fixed horizon
    missing_data: complete case
"""


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        (self.root / "data").mkdir()
        self.path = self.root / "data" / "statistics-plan.yaml"
        self.path.write_text(VALID, encoding="utf-8")

    @staticmethod
    def _codes(problems):
        return {problem.code for problem in problems}

    def test_valid_plan_passes(self):
        problems, _advisories = check(self.root)
        self.assertEqual(problems, [])

    def test_multiple_claims_require_correction(self):
        self.path.write_text(
            VALID.replace("multiple_comparison: holm-bonferroni", "multiple_comparison: none")
            + "  - id: claim:second\n"
            "    endpoint: latency\n"
            "    test: paired t-test\n"
            "    effect_size: 0.4\n"
            "    target_power: 0.8\n"
            "    sample_size: 30\n"
            "    seeds: [0]\n"
            "    stopping_rule: fixed horizon\n"
            "    missing_data: complete case\n",
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("statistics-missing-correction", self._codes(problems))

    def test_invalid_alpha_is_a_problem(self):
        self.path.write_text(
            VALID.replace("alpha: 0.05", "alpha: 1.5"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("statistics-invalid", self._codes(problems))

    def test_invalid_sample_size_is_a_problem(self):
        self.path.write_text(
            VALID.replace("sample_size: 30", "sample_size: 0"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("statistics-invalid", self._codes(problems))

    def test_seeds_must_be_present(self):
        self.path.write_text(
            VALID.replace("    seeds: [0, 1, 2]\n", "    seeds: []\n"),
            encoding="utf-8",
        )
        problems, _advisories = check(self.root)
        self.assertIn("statistics-invalid", self._codes(problems))


if __name__ == "__main__":
    unittest.main()
