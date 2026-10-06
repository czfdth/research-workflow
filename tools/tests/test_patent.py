"""The patent chain gate and the jurisdiction formatter."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from ccfa import patent

CN_CLAIMS = """# 权利要求书

1. 一种示例方法，其特征在于，包括：
   - 步骤 A；
   - 步骤 B。
2. 根据权利要求1所述的方法，其特征在于，所述步骤 A 包括 A1。
3. 根据权利要求2所述的方法，其特征在于，所述 A1 包括 A2。
4. 一种示例装置，其特征在于，包括：
   - 模块 A；
   - 模块 B。
5. 根据权利要求4所述的装置，其特征在于，所述模块 A 包括模块 B。
"""

US_CLAIMS = """# Claims

1. A method for demoing, comprising:
   - step A;
2. The method of claim 1, wherein step A comprises A1.
3. A system, comprising:
   - module A;
"""

EP_CLAIMS = """# Claims

1. A method for demoing, comprising step A, characterised in that step A uses A1.
2. The method according to claim 1, characterised in that A1 uses A2.
3. A system comprising module A, characterised in that the module A uses B.
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _base_patent(root: Path, *, jurisdiction: str = "CN", claims: str = CN_CLAIMS):
    import datetime as dt

    _write(
        root / "PATENT_STATE.json",
        json.dumps(
            {
                "phase": 3,
                "jurisdiction": jurisdiction,
                "patent_type": "invention",
                "status": "in_progress",
                "timestamp": dt.datetime.now(dt.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "invention_title": "一种示例方法",
                "schema_version": 1,
            },
            ensure_ascii=False,
        ),
    )
    _write(
        root / "INVENTION_DISCLOSURE.md",
        "# 发明披露\n\n## Core Inventive Concept\n核心特征。\n\n"
        "## Supporting Features\n支撑特征。\n\n## Optional Features\n可选特征。\n",
    )
    _write(root / "CLAIMS.md", claims)
    _write(
        root / "PRIOR_ART_REPORT.md",
        "# 现有技术\n\n1. https://example.org/a\n2. https://example.org/b\n"
        "3. doi:10.1000/xyz\n",
    )
    _write(
        root / "NOVELTY_ASSESSMENT.md",
        "# 新颖性评估\n\n"
        "与最接近的现有技术相比，本发明的区别技术特征在于：\n"
        "1. 步骤 A 使用 A1；\n"
        "2. 模块 A 与模块 B 的耦合方式不同。\n"
        "建议把 A2 补进从属权利要求，并在说明书中给出对应的实施例。\n",
    )
    for key in patent.SPEC_SECTIONS:
        _write(root / "specification" / f"{key}.md", f"{key} 内容。\n")
    _write(
        root / "patent-review.yaml",
        yaml.safe_dump(
            {
                "objections": [
                    {
                        "id": "O1",
                        "status": "resolved",
                        "resolution": "已补入从属项 3。",
                    }
                ]
            },
            sort_keys=False,
            allow_unicode=True,
        ),
    )
    return root


class ClaimParsingTests(unittest.TestCase):
    def test_numbers_and_dependencies_are_parsed(self):
        claims = patent.parse_claims(CN_CLAIMS)

        self.assertEqual([c["number"] for c in claims], [1, 2, 3, 4, 5])
        self.assertTrue(claims[0]["independent"])
        self.assertEqual(claims[1]["dependent_on"], 1)
        self.assertEqual(claims[4]["dependent_on"], 4)

    def test_us_dependency_is_parsed(self):
        claims = patent.parse_claims(US_CLAIMS)

        self.assertEqual(claims[1]["dependent_on"], 1)
        self.assertTrue(claims[2]["independent"])

    def test_ep_dependency_is_parsed(self):
        claims = patent.parse_claims(EP_CLAIMS)

        self.assertEqual(claims[1]["dependent_on"], 1)
        self.assertTrue(claims[0]["independent"])


class ClaimCheckTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def _check(self, claims: str, *, patent_type="invention", jurisdictions=("CN",)):
        _write(self.root / "CLAIMS.md", claims)
        return patent.check_claims(
            self.root, patent_type=patent_type, jurisdictions=jurisdictions
        )

    def test_valid_cn_claims_pass(self):
        problems, advisories = self._check(CN_CLAIMS)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_a_numbering_gap_fails(self):
        broken = CN_CLAIMS.replace("3. 根据权利要求2", "4. 根据权利要求2")

        problems, _advisories = self._check(broken)

        self.assertIn("patent-claim-numbering", [p.code for p in problems])

    def test_too_few_independent_claims_fails(self):
        broken = "\n".join(
            line
            for line in CN_CLAIMS.splitlines()
            if not line.startswith("4.") and not line.startswith("5.")
        )

        problems, _advisories = self._check(broken)

        self.assertIn(
            "patent-insufficient-independent-claims",
            [p.code for p in problems],
        )

    def test_a_forward_dependency_fails(self):
        broken = CN_CLAIMS.replace(
            "2. 根据权利要求1所述的方法", "2. 根据权利要求9所述的方法"
        )

        problems, _advisories = self._check(broken)

        self.assertIn("patent-claim-dependency", [p.code for p in problems])

    def test_a_cn_independent_claim_without_the_phrase_fails(self):
        broken = CN_CLAIMS.replace(
            "1. 一种示例方法，其特征在于", "1. 一种示例方法"
        )

        problems, _advisories = self._check(broken)

        self.assertIn(
            "patent-claim-characterising-missing", [p.code for p in problems]
        )

    def test_a_us_independent_claim_without_comprising_fails(self):
        broken = US_CLAIMS.replace("1. A method for demoing, comprising:", "1. A method for demoing:")

        problems, _advisories = self._check(broken, jurisdictions=("US",))

        self.assertIn(
            "patent-claim-characterising-missing", [p.code for p in problems]
        )

    def test_an_ep_independent_claim_without_two_part_form_fails(self):
        broken = EP_CLAIMS.replace(
            "1. A method for demoing, comprising step A, characterised in that step A uses A1.",
            "1. A method for demoing, comprising step A and step A1.",
        )

        problems, _advisories = self._check(broken, jurisdictions=("EP",))

        self.assertIn(
            "patent-claim-characterising-missing", [p.code for p in problems]
        )

    def test_a_utility_model_method_claim_fails(self):
        problems, _advisories = self._check(
            CN_CLAIMS, patent_type="utility_model", jurisdictions=("CN",)
        )

        self.assertIn(
            "patent-utility-model-method-claim", [p.code for p in problems]
        )

    def test_too_many_claims_is_only_an_advisory(self):
        extra = "\n".join(
            f"{number}. 根据权利要求4所述的装置，其特征在于，特征 {number}。"
            for number in range(6, 24)
        )
        broken = CN_CLAIMS + extra + "\n"

        problems, advisories = self._check(broken)

        self.assertEqual(problems, [])
        self.assertIn("patent-too-many-claims", [a.code for a in advisories])

    def test_unparsable_claims_are_an_error(self):
        problems, _advisories = self._check("没有编号的权利要求。\n")

        self.assertEqual([p.code for p in problems], ["patent-claims-unparsable"])


class StateTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_a_missing_state_file_is_a_problem(self):
        problems, _advisories = patent.check_state(self.root)

        self.assertEqual([p.code for p in problems], ["patent-state-missing"])

    def test_a_utility_model_outside_cn_is_rejected(self):
        _write(
            self.root / "PATENT_STATE.json",
            json.dumps(
                {
                    "phase": 1,
                    "jurisdiction": "US",
                    "patent_type": "utility_model",
                    "status": "completed",
                }
            ),
        )

        problems, _advisories = patent.check_state(self.root)

        self.assertIn(
            "patent-type-jurisdiction-mismatch", [p.code for p in problems]
        )

    def test_a_stale_in_progress_state_is_an_advisory(self):
        import datetime as dt

        _write(
            self.root / "PATENT_STATE.json",
            json.dumps(
                {
                    "phase": 2,
                    "jurisdiction": "CN",
                    "patent_type": "invention",
                    "status": "in_progress",
                    "timestamp": "2026-10-01T00:00:00Z",
                }
            ),
        )

        problems, advisories = patent.check_state(
            self.root, now=dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc)
        )

        self.assertEqual(problems, [])
        self.assertEqual([a.code for a in advisories], ["patent-state-stale"])

    def test_write_state_rejects_a_utility_model_outside_cn(self):
        with self.assertRaisesRegex(ValueError, "实用新型"):
            patent.write_state(
                self.root,
                phase=1,
                status="in_progress",
                jurisdiction="US",
                patent_type="utility_model",
            )

    def test_write_then_read_round_trips(self):
        patent.write_state(
            self.root,
            phase=4,
            status="completed",
            jurisdiction="CN",
            patent_type="invention",
            invention_title="一种示例方法",
            claims_count=5,
        )

        state = patent.read_state(self.root)

        self.assertEqual(state["phase"], 4)
        self.assertEqual(state["claims_count"], 5)
        self.assertEqual(state["status"], "completed")


class WholeGateTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name) / "patent"

    def test_a_complete_patent_directory_passes(self):
        _base_patent(self.root)

        problems, advisories = patent.check(self.root)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_an_unstructured_disclosure_fails(self):
        _base_patent(self.root)
        _write(self.root / "INVENTION_DISCLOSURE.md", "# 只有标题\n")

        problems, _advisories = patent.check(self.root)

        self.assertIn(
            "patent-disclosure-unstructured", [p.code for p in problems]
        )

    def test_a_thin_prior_art_report_fails(self):
        _base_patent(self.root)
        _write(self.root / "PRIOR_ART_REPORT.md", "# 现有技术\n\n1. 某篇文章\n")

        problems, _advisories = patent.check(self.root)

        self.assertIn("patent-prior-art-thin", [p.code for p in problems])

    def test_an_unresolved_objection_fails(self):
        _base_patent(self.root)
        _write(
            self.root / "patent-review.yaml",
            yaml.safe_dump(
                {"objections": [{"id": "O1", "status": "open"}]},
                sort_keys=False,
            ),
        )

        problems, _advisories = patent.check(self.root)

        self.assertIn("patent-review-unresolved", [p.code for p in problems])

    def test_a_missing_patent_root_is_an_error(self):
        problems, _advisories = patent.check(self.root / "nope")

        self.assertEqual([p.code for p in problems], ["patent-root-missing"])


class OutputCheckTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name) / "patent"
        _base_patent(self.root)

    def test_format_cn_writes_the_three_files(self):
        result = patent.format_patent(self.root, "CN")

        self.assertEqual(result["missing_sections"], [])
        self.assertTrue((self.root / "output" / "CN" / "claims.md").is_file())
        self.assertTrue(
            (self.root / "output" / "CN" / "description.md").is_file()
        )
        self.assertIn("output/CN/description.md", result["files"])
        self.assertEqual(
            (self.root / "output" / "CN" / "description.md")
            .read_text(encoding="utf-8")
            .count("发明名称"),
            1,
        )

    def test_format_reports_missing_specification_sections(self):
        (self.root / "specification" / "background.md").unlink()

        result = patent.format_patent(self.root, "CN")

        self.assertIn("background", result["missing_sections"])

    def test_compiled_cn_output_passes_the_output_gate(self):
        patent.format_patent(self.root, "CN")

        problems, advisories = patent.check_output(self.root)

        self.assertEqual(problems, [])
        self.assertEqual(advisories, [])

    def test_chinese_text_in_a_us_output_is_rejected(self):
        patent.format_patent(self.root, "US")
        (self.root / "output" / "US" / "abstract.md").write_text(
            "这是中文摘要。\n", encoding="utf-8"
        )

        problems, _advisories = patent.check_output(self.root)

        self.assertIn("patent-output-language", [p.code for p in problems])

    def test_claim_drift_between_outputs_is_rejected(self):
        patent.format_patent(self.root, "CN")
        (self.root / "output" / "CN" / "claims.md").write_text(
            "# 权利要求书\n\n1. 只剩一条。\n", encoding="utf-8"
        )

        problems, _advisories = patent.check_output(self.root)

        self.assertIn("patent-output-claim-drift", [p.code for p in problems])

    def test_an_over_long_cn_abstract_is_rejected(self):
        _write(
            self.root / "specification" / "abstract.md",
            "中" * 320,
        )
        patent.format_patent(self.root, "CN")

        problems, _advisories = patent.check_output(self.root)

        self.assertIn(
            "patent-output-abstract-too-long", [p.code for p in problems]
        )

    def test_a_missing_output_file_is_reported(self):
        patent.format_patent(self.root, "CN")
        (self.root / "output" / "CN" / "description.md").unlink()

        problems, _advisories = patent.check_output(self.root)

        self.assertIn("patent-output-missing", [p.code for p in problems])

    def test_an_unknown_output_folder_is_only_an_advisory(self):
        _write(self.root / "output" / "XX" / "claims.md", "# claims\n")

        _problems, advisories = patent.check_output(self.root)

        self.assertIn(
            "patent-output-unknown-jurisdiction", [a.code for a in advisories]
        )


class CliTests(unittest.TestCase):
    def _run(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = patent.main(["patent", *argv])
        return code, stdout.getvalue()

    def test_check_returns_zero_for_a_complete_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base_patent(Path(tmp) / "patent")

            code, output = self._run(["check", "--patent-root", str(root)])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["problem_count"], 0)

    def test_check_returns_one_when_the_state_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base_patent(Path(tmp) / "patent")
            (root / "PATENT_STATE.json").unlink()

            code, output = self._run(["check", "--patent-root", str(root)])

        self.assertEqual(code, 1)
        self.assertGreaterEqual(json.loads(output)["problem_count"], 1)

    def test_state_writes_and_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "patent"
            root.mkdir(parents=True)

            code, output = self._run(
                [
                    "state",
                    "--patent-root",
                    str(root),
                    "--phase",
                    "2",
                    "--status",
                    "in_progress",
                    "--jurisdiction",
                    "CN",
                    "--patent-type",
                    "invention",
                    "--title",
                    "一种示例方法",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["phase"], 2)

            code, output = self._run(["state", "--patent-root", str(root)])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["invention_title"], "一种示例方法")

    def test_format_all_writes_three_jurisdictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base_patent(Path(tmp) / "patent")

            code, output = self._run(
                [
                    "format",
                    "--patent-root",
                    str(root),
                    "--jurisdiction",
                    "ALL",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                [item["jurisdiction"] for item in json.loads(output)],
                ["CN", "US", "EP"],
            )
            for jurisdiction in ("CN", "US", "EP"):
                self.assertTrue(
                    (root / "output" / jurisdiction / "claims.md").is_file()
                )

    def test_format_rejects_an_unknown_jurisdiction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _base_patent(Path(tmp) / "patent")

            code, _output = self._run(
                ["format", "--patent-root", str(root), "--jurisdiction", "XX"]
            )

        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
