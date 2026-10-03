import unittest

from ccfa.stages import stages_for
from newpaper.checklists import render_checklist


class TestChecklistRendering(unittest.TestCase):
    def test_every_stage_appears_for_both_modes(self):
        for mode in ("conference", "journal"):
            text = render_checklist(mode)
            for stage in stages_for(mode):
                with self.subTest(mode=mode, stage=stage):
                    self.assertIn(f"[{stage}]", text)

    def test_conference_text_mentions_rebuttal(self):
        self.assertIn("rebuttal", render_checklist("conference"))

    def test_journal_text_mentions_response_letter(self):
        self.assertIn("response-letter", render_checklist("journal"))

    def test_checkbox_count_covers_every_stage(self):
        for mode in ("conference", "journal"):
            text = render_checklist(mode)
            with self.subTest(mode=mode):
                self.assertGreaterEqual(text.count("- [ ]"), len(stages_for(mode)))

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            render_checklist("workshop")
