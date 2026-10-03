import unittest

from ccfa.texcomment import strip_comment


class TestStripComment(unittest.TestCase):
    def test_plain_percent_starts_a_comment(self):
        self.assertEqual(strip_comment("\\cite{a} % \\cite{ghost}"), "\\cite{a} ")

    def test_escaped_percent_is_not_a_comment(self):
        self.assertEqual(strip_comment("100\\% of \\cite{a}"), "100\\% of \\cite{a}")

    def test_two_backslashes_then_percent_starts_a_comment(self):
        # A literal backslash followed by a percent: the percent is not escaped.
        self.assertEqual(strip_comment("line\\\\% \\cite{ghost}"), "line\\\\")

    def test_three_backslashes_then_percent_is_escaped(self):
        self.assertEqual(strip_comment("line\\\\\\% x"), "line\\\\\\% x")

    def test_no_percent_returns_line_unchanged(self):
        self.assertEqual(strip_comment("\\cite{a}"), "\\cite{a}")

    def test_percent_at_position_zero_yields_empty(self):
        self.assertEqual(strip_comment("% hidden"), "")


if __name__ == "__main__":
    unittest.main()
