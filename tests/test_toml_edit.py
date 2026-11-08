"""The `[[allowlist.entries]]` locator and the text-edit primitives that fixes are built from."""
import tomllib
import unittest

from agentfile_lint import fix, toml_edit
from agentfile_lint.finding import Edit

ENTRY = '[[allowlist.entries]]\nrule = "R1d"\npath = "AGENTS.md"\ncount = 3\nreason = "x"\nexpires = 2026-06-30\n'


class LocatorTest(unittest.TestCase):
    def test_blocks_and_count(self):
        text = "[rules.R1d]\nlevel = \"error\"\n\n" + ENTRY + "\n# next\n" + ENTRY.replace("count = 3", "count  =  12 # n") + "[rules.R2]\nlevel = \"warn\"\n"
        a, b = toml_edit.entry_blocks(text, 2)
        self.assertEqual((a.header, a.last, a.removal_start, a.removal_end, a.count), (4, 9, 4, 10, (7, 9, 10)))
        self.assertEqual((b.header, b.last, b.removal_end, b.count), (12, 17, 17, (15, 11, 13)))

    def test_last_block_takes_the_blank_lines_before_it(self):
        text = ENTRY + "\n\n" + ENTRY
        _, b = toml_edit.entry_blocks(text, 2)
        self.assertEqual((b.removal_start, b.removal_end), (7, 14))
        self.assertEqual(fix.apply_edits(text, [fix.line_delete("c", text, b.removal_start, b.removal_end)]), ENTRY)

    def test_header_spacing_and_comment(self):
        self.assertIsNotNone(toml_edit.entry_blocks("[[ allowlist . entries ]]  # one\ncount = 1\n", 1))

    def test_gives_up_when_the_header_count_differs(self):
        self.assertIsNone(toml_edit.entry_blocks(ENTRY, 2))
        self.assertIsNone(toml_edit.entry_blocks('[[allowlist."entries"]]\ncount = 1\n', 1))
        self.assertIsNone(toml_edit.entry_blocks('allowlist.entries = [{count = 1}]\n', 1))


class EditTest(unittest.TestCase):
    def test_apply_edits_in_any_order(self):
        text = "ab\r\ncd\nef"
        edits = [Edit("f", (3, 2), (3, 3), "X"), Edit("f", (1, 1), (2, 1), "")]
        self.assertEqual(fix.apply_edits(text, edits), "cd\neX")

    def test_overlapping_edits_fail(self):
        with self.assertRaises(ValueError):
            fix.apply_edits("abc\n", [Edit("f", (1, 1), (1, 3), ""), Edit("f", (1, 2), (1, 4), "")])

    def test_position_outside_the_file_fails(self):
        for edit in (Edit("f", (3, 1), (3, 1), ""), Edit("f", (1, 9), (1, 9), "")):
            with self.assertRaises(ValueError):
                fix.apply_edits("abc\n", [edit])

    def test_line_delete(self):
        cases = [
            ("a\nb\nc\n", 2, "a\nc\n"),
            ("a\nb\nc", 3, "a\nb"),       # no final newline: the one before goes
            ("a\nbc", 2, "a"),
            ("a", 1, ""),
            ("a\r\nb\r\n", 1, "b\r\n"),
            ("a\rb\r", 2, "a\r"),
        ]
        for text, line, want in cases:
            with self.subTest(text=text, line=line):
                self.assertEqual(fix.apply_edits(text, [fix.line_delete("f", text, line, line)]), want)

    def test_line_moves(self):
        old = "1\n2\n3\n4\n5xx\n6\n7\n8\n"
        edits = [Edit("f", (2, 1), (3, 1), ""), Edit("f", (5, 3), (6, 1), "x\ny\n")]
        new = fix.apply_edits(old, edits)
        self.assertEqual(fix.line_moves(old, edits, new), {1: 1, 2: None, 3: 2, 4: 3, 5: 4, 6: 6, 7: 7, 8: 8})

    def test_line_moves_for_a_removed_last_line(self):
        # The last line has no newline, so the edit takes the newline before it: line 3 is gone.
        old = "a\nb\nc"
        edit = fix.line_delete("f", old, 3, 3)
        self.assertEqual(fix.line_moves(old, [edit], fix.apply_edits(old, [edit])), {1: 1, 2: 2, 3: None})

    def test_widened(self):
        from agentfile_lint.allowlist import Entry
        import datetime
        day = datetime.date(2026, 6, 30)
        a, b = Entry("R1d", "a.md", 2, "x", day), Entry("R1d", "b.md", 1, "x", day)
        self.assertEqual(fix.widened([a, b], [Entry("R1d", "a.md", 1, "x", day)]), [])     # lower, remove
        self.assertEqual(fix.widened([a], [a, b]), ["R1d b.md"])                             # a new entry
        self.assertEqual(fix.widened([a], [Entry("R1d", "a.md", 3, "x", day)]), ["R1d a.md"])  # a higher count

    def test_choosing_edits(self):
        a = Edit("f", (1, 1), (3, 1), "")
        edits = {}
        b = Edit("f", (6, 1), (6, 2), "x")
        self.assertTrue(fix._add(edits, (a, b)))
        self.assertTrue(fix._add(edits, (a, b)))                            # the same edits: once
        self.assertTrue(fix._add(edits, (Edit("f", (2, 1), (4, 1), ""),)))  # overlapping deletions merge
        self.assertEqual(edits, {"f": [b, Edit("f", (1, 1), (4, 1), "")]})
        self.assertFalse(fix._add(edits, (Edit("f", (3, 1), (3, 2), "x"),)))  # a replacement inside: next pass
        self.assertEqual(fix.apply_edits("1\n2\n3\n4\n5\n6\n", edits["f"]), "4\n5\nx\n")

    def test_toml_checked(self):
        text = ENTRY
        good = (Edit("c", (4, 9), (4, 10), "1"),)
        bad = (Edit("c", (5, 11), (5, 12), "y"),)  # edits the reason instead
        d = tomllib.loads(text)
        lower = {"allowlist": {"entries": [{**d["allowlist"]["entries"][0], "count": 1}]}}
        self.assertTrue(fix.toml_checked(text, good, lower))
        self.assertFalse(fix.toml_checked(text, bad, lower))
        self.assertFalse(fix.toml_checked(text, (Edit("c", (4, 1), (4, 10), "count ="),), lower))  # invalid TOML
        gone = fix.apply_edits(text, [fix.line_delete("c", text, 1, 6)])
        self.assertEqual(tomllib.loads(gone), {})
        self.assertTrue(fix.toml_checked(text, (fix.line_delete("c", text, 1, 6),), {"allowlist": {"entries": []}}))


if __name__ == "__main__":
    unittest.main()
