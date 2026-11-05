import datetime
import time
import unittest

from agentfile_lint import frontmatter


class SplitTest(unittest.TestCase):
    def test_no_frontmatter(self):
        for text in ("# Title\n", "", "\n---\na: 1\n---\n", " ---\na: 1\n---\n"):
            self.assertIsNone(frontmatter.parse(text), repr(text))

    def test_unterminated(self):
        r = frontmatter.parse("---\nname: x\n")
        self.assertEqual((r.error, r.end), ("frontmatter has no closing '---' line", 0))

    def test_empty_block(self):
        r = frontmatter.parse("---\n---\nbody\n")
        self.assertEqual((r.value, r.error, r.end), (None, None, 2))

    def test_closing_line_must_be_exact(self):
        r = frontmatter.parse("---\nname: x\n--- \n---\n")   # "--- " is YAML, not the closing line
        self.assertEqual(r.end, 4)


class ParseTest(unittest.TestCase):
    def test_mapping(self):
        r = frontmatter.parse("---\nname: pdf\ndescription: Use when reading PDFs\nmetadata:\n  a: [1, b]\n---\n# Body\n")
        self.assertIsNone(r.error)
        self.assertEqual(r.value, {"name": "pdf", "description": "Use when reading PDFs", "metadata": {"a": [1, "b"]}})
        self.assertEqual(r.end, 6)

    def test_non_mapping_value_is_returned_for_the_rules_to_judge(self):
        self.assertEqual(frontmatter.parse("---\n- a\n- b\n---\n").value, ["a", "b"])

    def test_yaml_1_1_scalars(self):
        r = frontmatter.parse("---\non: yes\nd: 2026-11-06\n---\n")
        self.assertEqual(r.value, {True: True, "d": datetime.date(2026, 11, 6)})

    def test_error_position_is_a_file_position(self):
        r = frontmatter.parse("---\nname: x\ndescription: a: b\n---\n")
        self.assertTrue(r.error.startswith("invalid YAML: "), r.error)
        self.assertEqual((r.line, r.column), (3, 15))
        self.assertEqual(r.end, 4)

    def test_python_tags_are_refused(self):
        # SafeLoader builds plain data only; a full Loader would construct the object.
        r = frontmatter.parse("---\nx: !!python/object/apply:os.getcwd []\n---\n")
        self.assertIsNotNone(r.error)
        self.assertIn("python/object/apply", r.error)
        self.assertIsNone(r.value)

    def test_reader_error_is_one_line_at_the_file_position(self):
        r = frontmatter.parse("---\nname: x\na: \x07\n---\n")
        self.assertEqual((r.error, r.line, r.column), ("invalid YAML: unacceptable character #x0007", 3, 4))

    def test_values_that_fail_conversion_have_no_crash(self):
        for value in ("2026-02-30", "!!int abc", "!!float abc", "!!timestamp foo", "1" * 5000):
            r = frontmatter.parse(f"---\nx: {value}\n---\n")
            self.assertTrue(r.error.startswith("invalid YAML: cannot convert a value: "), (value[:20], r.error))
            self.assertNotIn("\n", r.error)

    def test_leading_bom_is_ignored(self):
        self.assertEqual(frontmatter.parse("\ufeff---\na: 1\n---\n").value, {"a": 1})

    def test_deep_nesting_has_no_crash(self):
        r = frontmatter.parse("---\na: " + "[" * 100000 + "\n---\n")
        self.assertIsNotNone(r.error)



class StringsTest(unittest.TestCase):
    def test_scalars_are_their_text(self):
        r = frontmatter.parse("---\nd: 2026-02-30\ny: yes\nn: 12\nm: [1, {a: b}]\ne:\n---\n", strings=True)
        self.assertIsNone(r.error)
        self.assertEqual(r.value, {"d": "2026-02-30", "y": "yes", "n": "12", "m": ["1", {"a": "b"}], "e": ""})

    def test_tags_are_never_constructed(self):
        r = frontmatter.parse("---\nx: !!python/object/apply:os.system [echo hi]\n---\n", strings=True)
        self.assertEqual(r.value, {"x": ["echo hi"]})

    def test_aliases_share_one_value(self):
        text = "---\na: &a [x, x, x, x, x, x, x, x, x]\n" + "".join(
            f"{k}: &{k} [{', '.join(['*' + p] * 9)}]\n" for p, k in zip("abcdefg", "bcdefgh")) + "---\n"
        r = frontmatter.parse(text, strings=True)   # 9**8 leaves if each alias were copied
        self.assertIs(r.value["h"][0], r.value["g"])

    def test_a_non_scalar_key_is_an_error_not_an_expansion(self):
        text = "---\na: &a [x, x, x, x, x, x, x, x, x]\n" + "".join(
            f"{k}: &{k} [{', '.join(['*' + p] * 9)}]\n" for p, k in zip("abcdefg", "bcdefgh")) + "? *h\n: 1\n---\n"
        start = time.monotonic()
        r = frontmatter.parse(text, strings=True)
        self.assertLess(time.monotonic() - start, 1.0)
        # An alias is its anchor's node, so the error points at the anchor (`h:` on line 9).
        self.assertEqual((r.error, r.line), ("invalid YAML: a mapping key is not a string", 9))
        self.assertEqual(frontmatter.parse("---\n[a, b]: 1\n---\n", strings=True).error,
                         "invalid YAML: a mapping key is not a string")

    def test_duplicate_keys_fail_at_the_second(self):
        r = frontmatter.parse("---\nname: ok\nname: other\n---\n", strings=True)
        self.assertEqual((r.error, r.line), ("invalid YAML: duplicate key 'name'", 3))

    def test_merge_keys_are_applied_and_written_keys_win(self):
        r = frontmatter.parse("---\nbase: &b {name: x, description: d}\n<<: *b\nname: y\n---\n", strings=True)
        self.assertEqual({k: r.value[k] for k in ("name", "description")}, {"name": "y", "description": "d"})
        self.assertEqual(r.keys, {"base": 2, "name": 4, "description": 3})

    def test_key_lines_come_from_the_parse_not_the_text(self):
        text = '---\ndescription: "first\nname: x"\ntags: {a: 1,\nlicense: 2}\nname: n\nlicense: l\n---\n'
        r = frontmatter.parse(text, strings=True)
        self.assertEqual(r.keys, {"description": 2, "tags": 4, "name": 6, "license": 7})

    def test_grammar_errors_still_fail(self):
        r = frontmatter.parse("---\nname: x\ndescription: a: b\n---\n", strings=True)
        self.assertEqual((r.error, r.line), ("invalid YAML: mapping values are not allowed here", 3))


if __name__ == "__main__":
    unittest.main()
