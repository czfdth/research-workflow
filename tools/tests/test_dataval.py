import tempfile
import unittest
from pathlib import Path

from ccfa.dataval import find_tags


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestFindTags(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def _scan(self, body: str):
        path = _write(self.root, "main.tex", body)
        return find_tags([path]), path

    def test_plain_tag(self):
        tags, path = self._scan("\\dataval{results.json:summary.lcoe}{0.143}")
        self.assertEqual(len(tags), 1)
        tag = tags[0]
        self.assertEqual(tag.source_path, "results.json")
        self.assertEqual(tag.key_path, "summary.lcoe")
        self.assertEqual(tag.claimed, "0.143")
        self.assertEqual(tag.line, 1)
        self.assertEqual(tag.path, str(path))

    def test_multiple_tags_on_one_line(self):
        tags, _ = self._scan("\\dataval{a.json:x}{1} and \\dataval{b.csv:0.y}{2}")
        self.assertEqual([t.source_path for t in tags], ["a.json", "b.csv"])

    def test_commented_tag_is_ignored(self):
        tags, _ = self._scan("% \\dataval{a.json:x}{1}\n\\dataval{b.json:y}{2}")
        self.assertEqual([t.source_path for t in tags], ["b.json"])

    def test_tag_after_literal_backslash_comment_is_ignored(self):
        tags, _ = self._scan("line\\\\% \\dataval{ghost.json:x}{1}\n\\dataval{real.json:y}{2}")
        self.assertEqual([t.source_path for t in tags], ["real.json"])

    def test_escaped_percent_does_not_truncate_the_line(self):
        tags, _ = self._scan("100\\% \\dataval{kept.json:x}{1}")
        self.assertEqual([t.source_path for t in tags], ["kept.json"])

    def test_unreadable_file_is_skipped_not_crashed(self):
        self.assertEqual(find_tags([self.root / "gone.tex"]), [])

    def test_line_number_counts_from_one(self):
        tags, _ = self._scan("text\n\n\\dataval{a.json:x}{1}")
        self.assertEqual(tags[0].line, 3)


if __name__ == "__main__":
    unittest.main()
