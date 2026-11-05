"""Per-line directives, one test per clause of docs/adr/0006 (per-line suppression)."""
import unittest

import helpers

TODAY = "2026-06-01"
BIG = "x" * 600 + "\n"  # an R1d finding under R1_LINE
R1_LINE = "[rules.R1d]\nlevel = \"error\"\nmax_chars = 500\n"


def directive(body="R1d -- generated table, wrapped upstream"):
    return f"<!-- agentfile-lint-disable-next-line {body} -->\n"


def run(files, toml="", *extra):
    root = helpers.make_repo({**files, ".agentfile-lint.toml": R1_LINE + toml})
    return helpers.run_new(root, "--today", TODAY, *extra)


class DisableTest(unittest.TestCase):
    def test_suppresses_the_next_line_only(self):
        r = run({"AGENTS.md": "# T\n" + directive() + BIG + BIG})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("AGENTS.md:3:", r.stdout)
        self.assertIn("AGENTS.md:4: error: R1d:", r.stdout)
        self.assertNotIn("disable", r.stdout)

    def test_only_the_named_rules(self):
        dup = "Run make check before every push to the remote.\n"
        files = {"AGENTS.md": dup, "sub/AGENTS.md": directive("R1d -- long on purpose") + dup}
        r = run(files)
        self.assertIn("sub/AGENTS.md:2: warning: R5a:", r.stdout)
        self.assertIn("sub/AGENTS.md:1: warning: disable: directive for R1d suppresses nothing", r.stdout)

    def test_several_ids_and_aliases(self):
        dup = "Run make check before every push to the remote.\n"
        line = dup.rstrip("\n") + " " + "x" * 600 + "\n"
        files = {"AGENTS.md": line, "sub/AGENTS.md": directive("line-length, R5a -- copied on purpose") + line}
        r = run(files)
        self.assertEqual(r.returncode, 1, r.stdout)  # the ancestor's own R1d
        self.assertNotIn("sub/AGENTS.md", r.stdout)

    def test_duplicate_is_suppressed_in_the_reporting_file(self):
        dup = "Run make check before every push to the remote.\n"
        files = {"AGENTS.md": directive("R5a -- not here") + dup, "sub/AGENTS.md": directive("R5a -- copy for the tool") + dup}
        r = run(files)
        self.assertNotIn("sub/AGENTS.md:2", r.stdout)
        self.assertIn("AGENTS.md:1: warning: disable: directive for R5a suppresses nothing", r.stdout)

    def test_reason_is_required(self):
        for body in ("R1d", "R1d --", "R1d -- ", "R1d --reason"):
            with self.subTest(body=body):
                r = run({"AGENTS.md": directive(body) + BIG})
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertIn("AGENTS.md:1: error: disable: directive needs a reason", r.stdout)
                self.assertIn("AGENTS.md:2: error: R1d:", r.stdout)

    def test_rule_id_is_required(self):
        r = run({"AGENTS.md": directive("-- no id") + BIG})
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGENTS.md:1: error: disable: directive names no rule id", r.stdout)

    def test_unknown_rule_is_an_error_not_a_config_error(self):
        for name in ("R9", "E0", "allowlist"):
            with self.subTest(name=name):
                r = run({"AGENTS.md": directive(f"{name} -- typo") + "ok\n"})
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertIn(f"AGENTS.md:1: error: disable: unknown rule '{name}'", r.stdout)

    def test_whole_file_rules_are_rejected(self):
        for name in ("R1a", "R1b", "R1c", "file-lines", "C1"):
            with self.subTest(name=name):
                r = run({"AGENTS.md": directive(f"{name} -- too long") + "ok\n"})
                self.assertEqual(r.returncode, 1)
                self.assertIn("is a whole-file rule", r.stdout)

    def test_malformed_directive_is_an_error(self):
        for line in ("<!-- agentfile-lint-disable R1d -- x -->\n", "text <!-- agentfile-lint-disable-next-line R1d -- x -->\n",
                     "<!-- agentfile-lint-disable-next-line R1d -- x\n"):
            with self.subTest(line=line):
                r = run({"AGENTS.md": "# T\n" + line + "ok\n"})
                if line.startswith("text"):
                    self.assertNotIn("disable", r.stdout)  # not on its own line: plain text, not a directive
                    continue
                self.assertEqual(r.returncode, 1)
                self.assertIn("AGENTS.md:2: error: disable: malformed directive", r.stdout)

    def test_unused_directive_warns(self):
        r = run({"AGENTS.md": directive() + "short\n"})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("AGENTS.md:1: warning: disable: directive for R1d suppresses nothing on the next line", r.stdout)
        r = run({"AGENTS.md": "ok\n" + directive()})  # last line: there is no next line
        self.assertIn("AGENTS.md:2: warning: disable:", r.stdout)

    def test_level_settings_do_not_change_disable(self):
        toml = '[[overrides]]\npaths = ["AGENTS.md"]\nrules = { R1d = "off" }\nreason = "x"\n'
        r = run({"AGENTS.md": directive("R9 -- typo") + "ok\n"}, toml, "--warn-as-error")
        self.assertEqual(r.returncode, 1)
        self.assertIn("error: disable: unknown rule", r.stdout)

    def test_directive_in_fenced_code_is_ignored(self):
        r = run({"AGENTS.md": "```\n" + directive("bogus") + "```\n"})
        self.assertNotIn("disable", r.stdout)

    def test_suppressed_findings_do_not_count_toward_allowlist(self):
        entry = ('[[allowlist.entries]]\nrule = "R1d"\npath = "AGENTS.md"\ncount = 1\n'
                 'reason = "cleanup"\nexpires = 2026-08-01\n')
        r = run({"AGENTS.md": directive() + BIG + BIG}, entry)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("allowlist", r.stdout)

    def test_directive_counts_toward_size_rules(self):
        toml = '[rules.R1b]\nlevel = "error"\nlimits = [{ glob = "**", max_lines = 2 }]\n'
        r = run({"AGENTS.md": "a\nb\n" + directive()}, toml)
        self.assertIn("AGENTS.md: error: R1b: file is 3 lines, limit 2", r.stdout)
        r = run({"AGENTS.md": directive("R1d -- " + "y" * 600)})
        self.assertIn("AGENTS.md:1: error: R1d:", r.stdout)

    def test_next_line_uses_lf_crlf_cr_only(self):
        # U+2028 and form feed do not end a line; CR does.
        text = "a b\x0cc\n" + directive().rstrip("\n") + "\r" + BIG + BIG
        r = run({"AGENTS.md": text})
        self.assertNotIn("AGENTS.md:3:", r.stdout)
        self.assertIn("AGENTS.md:4: error: R1d:", r.stdout)

    def test_retired_id_names_its_replacements(self):
        r = run({"AGENTS.md": directive("R5 -- old id") + "ok\n"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGENTS.md:1: error: disable: R5 (duplicates) was split in 0.7.0 into R5a", r.stdout)

    def test_stacked_directives_are_an_error(self):
        r = run({"AGENTS.md": directive() + directive("R5a -- copy") + BIG})
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGENTS.md:1: error: disable: directive is followed by another directive", r.stdout)
        self.assertIn("AGENTS.md:3: error: R1d:", r.stdout)

    def test_directive_in_html_comment_or_indented_code_is_ignored(self):
        # An unclosed fence inside a comment does not hide the directives after the comment.
        text = "<!--\n```bash\nold\n-->\n" + directive() + BIG
        r = run({"AGENTS.md": text})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("disable", r.stdout)
        r = run({"AGENTS.md": "text\n\n    " + directive("bogus")})
        self.assertNotIn("disable", r.stdout)
        r = run({"AGENTS.md": "   " + directive() + BIG})
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_list_rules_shows_disable(self):
        root = helpers.make_repo({"AGENTS.md": "ok\n"})
        r = helpers.run_new(root, "--list-rules")
        self.assertRegex(r.stdout, r"(?m)^disable  error  ")

    def test_disable_is_not_a_configurable_rule(self):
        for toml in ('[rules.disable]\nlevel = "off"\n',
                     '[[overrides]]\npaths = ["AGENTS.md"]\nrules = { disable = "off" }\nreason = "x"\n'):
            with self.subTest(toml=toml):
                r = run({"AGENTS.md": "ok\n"}, toml)
                self.assertEqual(r.returncode, 2, r.stdout)
                self.assertIn("disable", r.stderr)


if __name__ == "__main__":
    unittest.main()
