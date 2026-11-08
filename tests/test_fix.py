"""Fixes: `--fix`, `--unsafe-fixes`, `--diff` and the fix field of JSON and SARIF (docs/design.md, Fixes).

Every fix edits only what the tool itself put the user up to (per-line directives, allowlist entries);
two safety nets keep a fix from writing anything else: a TOML edit must change only its target when
re-parsed, and the run after the fixes may suppress only fewer findings, never others.
"""
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import helpers

TODAY = "2026-06-01"
BIG = "x" * 600 + "\n"  # an R1d finding under R1_LINE
R1_LINE = "[rules.R1d]\nlevel = \"error\"\nmax_chars = 500\n"
CONFIG = ".agentfile-lint.toml"


def directive(body="R1d -- generated table, wrapped upstream"):
    return f"<!-- agentfile-lint-disable-next-line {body} -->\n"


def entry(path="AGENTS.md", rule="R1d", count=1, reason='"cleanup tracked elsewhere"', expires="2026-06-30"):
    return f'[[allowlist.entries]]\nrule = "{rule}"\npath = "{path}"\ncount = {count}\nreason = {reason}\nexpires = {expires}\n'


def repo(files, toml=""):
    return helpers.make_repo({**files, CONFIG: R1_LINE + toml})


def run(root, *args):
    return helpers.run_new(root, "--today", TODAY, *args)


def read(root, name):
    return (root / name).read_bytes().decode("utf-8")


class DirectiveFixTest(unittest.TestCase):
    def test_unused_directive_line_is_removed(self):
        text = "# T\n" + directive() + "short\n"
        root = repo({"AGENTS.md": text})
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(root, "AGENTS.md"), "# T\nshort\n")
        self.assertEqual(r.stdout, "")
        self.assertIn("applied 1 fix in 1 file", r.stderr)

    def test_crlf_and_last_line_without_newline(self):
        root = repo({"AGENTS.md": "# T\r\n" + directive().rstrip("\n") + "\r\nshort\r\n",
                     "sub/AGENTS.md": "# S\n" + directive().rstrip("\n")})
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(root, "AGENTS.md"), "# T\r\nshort\r\n")
        self.assertEqual(read(root, "sub/AGENTS.md"), "# S")  # still no final newline

    def test_partly_used_directive_is_an_unsafe_fix(self):
        dup = "Run make check before every push to the remote.\n"
        text = directive("R5a, R1d -- copied on purpose") + dup
        root = repo({"AGENTS.md": dup, "sub/AGENTS.md": text})
        r = run(root, "--fix")
        self.assertEqual(read(root, "sub/AGENTS.md"), text)  # --fix leaves unsafe fixes alone
        self.assertIn("1 more fix available with --unsafe-fixes", r.stderr)
        self.assertIn("sub/AGENTS.md:1: warning: disable: directive for R1d suppresses nothing", r.stdout)
        r = run(root, "--fix", "--unsafe-fixes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(root, "sub/AGENTS.md"), directive("R5a -- copied on purpose") + dup)
        self.assertEqual(r.stdout, "")

    def test_alias_spelling_is_kept(self):
        dup = "Run make check before every push to the remote.\n"
        text = directive("ancestor-duplicates line-length -- copied on purpose") + dup
        root = repo({"AGENTS.md": dup, "sub/AGENTS.md": text})
        run(root, "--fix", "--unsafe-fixes")
        self.assertEqual(read(root, "sub/AGENTS.md"), directive("ancestor-duplicates -- copied on purpose") + dup)

    def test_used_and_malformed_directives_are_untouched(self):
        text = "# T\n" + directive() + BIG + directive("R1d") + "short\n"
        root = repo({"AGENTS.md": text})
        r = run(root, "--fix", "--unsafe-fixes")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(read(root, "AGENTS.md"), text)
        self.assertIn("AGENTS.md:4: error: disable: directive needs a reason", r.stdout)

    def test_suppressed_findings_below_a_removed_line_move_with_it(self):
        # The R1d finding suppressed on line 4 is on line 3 after the fix: the same suppression.
        text = "# T\n" + directive("R5a -- copied") + "\n" + directive() + BIG
        root = repo({"AGENTS.md": text})
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(root, "AGENTS.md"), "# T\n\n" + directive() + BIG)

    def test_fixes_that_uncover_fixes_are_applied_in_one_run(self):
        # Line 2 is stacked on the unused line 3; once line 3 goes, line 2 suppresses nothing either.
        text = "# T\n" + directive() + directive("R5a -- copied") + "short\n"
        root = repo({"AGENTS.md": text})
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(root, "AGENTS.md"), "# T\nshort\n")
        self.assertEqual(run(root, "--diff").stdout, "")

    def test_blocked_batch_names_lines_as_on_disk(self):
        # Two passes remove lines 4 and 3; the third directive then covers the R1d finding on line 5.
        text = "# T\n" + directive() + directive("R5a -- copied") + directive("R5a -- copied") + BIG
        root = repo({"AGENTS.md": text})
        r = run(root, "--fix")
        self.assertEqual(read(root, "AGENTS.md"), text)
        self.assertIn("(AGENTS.md:5 R1d)", r.stderr)

    def test_newly_uncovered_directive_blocks_the_batch(self):
        # Line 2 is stacked on line 3 (an error, covers nothing); removing the unused line 3 would
        # make line 2 a directive that suppresses the R1d finding on line 4: safety net 2.
        text = "# T\n" + directive() + directive("R5a -- copied") + BIG
        root = repo({"AGENTS.md": text, "sub/AGENTS.md": "# S\n" + directive() + "short\n"})
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(read(root, "AGENTS.md"), text)
        self.assertEqual(read(root, "sub/AGENTS.md"), "# S\n" + directive() + "short\n")  # whole batch
        self.assertIn("no fix applied", r.stderr)
        self.assertIn("AGENTS.md:4 R1d", r.stderr)


class AllowlistFixTest(unittest.TestCase):
    def test_count_is_lowered_and_nothing_else_changes(self):
        toml = "# exceptions\n" + entry(count=3).replace("count = 3", "count = 3  # was five") + "\n[rules.R2]\nlevel = \"warn\"\n"
        root = repo({"AGENTS.md": BIG}, toml)
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(root, CONFIG), R1_LINE + toml.replace("count = 3", "count = 1"))

    def test_entry_of_a_fixed_file_is_removed(self):
        first = entry(rule="R1d", path="AGENTS.md")
        second = entry(rule="R1d", path="sub/AGENTS.md")
        toml = first + "\n# second exception\n" + second
        root = repo({"AGENTS.md": "short\n", "sub/AGENTS.md": BIG}, toml)
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(root, CONFIG), R1_LINE + "# second exception\n" + second)

    def test_neighbouring_entries_are_removed_in_one_run(self):
        toml = entry(path="a/AGENTS.md") + "\n" + entry(path="b/AGENTS.md")
        root = repo({"AGENTS.md": "short\n", "a/AGENTS.md": "short\n", "b/AGENTS.md": "short\n"}, toml)
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(root, CONFIG), R1_LINE)

    def test_entry_of_a_file_that_is_not_utf8_is_kept(self):
        # No rule ran on the file (E0), so n = 0 does not mean it was fixed.
        root = repo({"AGENTS.md": b"\xff" + BIG.encode()}, entry(rule="R1d") + entry(rule="E0"))
        before = read(root, CONFIG)
        r = run(root, "--fix")
        self.assertEqual(read(root, CONFIG), before)
        self.assertIn("entry for R1d is no longer needed", r.stdout)

    def test_last_own_entry_is_kept_when_removing_it_brings_back_inherited_ones(self):
        files = {"AGENTS.md": "short\n", "sub/AGENTS.md": BIG, "base.toml": R1_LINE + entry(path="sub/AGENTS.md")}
        own = 'extends = ["base.toml"]\n' + entry(path="AGENTS.md")
        root = helpers.make_repo({**files, CONFIG: own})
        r = run(root, "--fix")
        self.assertEqual(read(root, CONFIG), own)
        self.assertIn("sub/AGENTS.md:1: error: R1d", r.stdout)  # the inherited entry is not in force
        self.assertNotIn("no fix applied", r.stderr)  # no fix offered, not one that safety net 2 stops
        # With a second own entry left, removing the first changes nothing inherited.
        own2 = own + entry(path="sub/AGENTS.md")
        root = helpers.make_repo({**files, CONFIG: own2})
        r = run(root, "--fix")
        self.assertEqual((r.returncode, read(root, CONFIG)), (0, 'extends = ["base.toml"]\n' + entry(path="sub/AGENTS.md")))

    def test_removing_every_own_entry_at_once_keeps_one(self):
        # Both own entries are no longer needed; removing both would bring back base.toml's entry,
        # which would suppress the R1d finding in sub/AGENTS.md.
        files = {"AGENTS.md": "short\n", "CLAUDE.md": "short\n", "sub/AGENTS.md": BIG,
                 "base.toml": R1_LINE + entry(path="sub/AGENTS.md")}
        own = 'extends = ["base.toml"]\n\n' + entry(path="AGENTS.md") + "\n" + entry(path="CLAUDE.md")
        root = helpers.make_repo({**files, CONFIG: own})
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(read(root, CONFIG), 'extends = ["base.toml"]\n\n' + entry(path="CLAUDE.md"))  # the last stays
        self.assertNotIn("no fix applied", r.stderr)
        self.assertIn("sub/AGENTS.md:1: error: R1d", r.stdout)
        self.assertIn("entry for R1d is no longer needed", r.stdout)

    def test_edited_config_may_not_allow_more_exceptions(self):
        # The second guard on its own: with the first one fooled (no inherited entries known), the
        # re-run sees base.toml's entry come back and nothing is written.
        from unittest import mock
        from agentfile_lint import cli, config
        files = {"AGENTS.md": "short\n", "sub/AGENTS.md": "short\n", "base.toml": R1_LINE + entry(path="sub/AGENTS.md")}
        own = 'extends = ["base.toml"]\n' + entry(path="AGENTS.md")
        root = helpers.make_repo({**files, CONFIG: own})
        real = config._source
        cwd = os.getcwd()
        err = io.StringIO()
        try:
            os.chdir(root)
            with mock.patch.object(config, "_source", lambda path, text, inherits: real(path, text, False)), \
                    mock.patch("sys.stderr", err), mock.patch("sys.stdout", io.StringIO()):
                code = cli.main(["--today", TODAY, "--fix"])
        finally:
            os.chdir(cwd)
        self.assertEqual(read(root, CONFIG), own)
        self.assertIn("would allow more exceptions (R1d sub/AGENTS.md)", err.getvalue())
        self.assertEqual(code, 1)

    def test_last_entries_removed_together_leave_no_blank_line(self):
        toml = "\n\n" + entry(path="a/AGENTS.md") + "\n" + entry(path="b/AGENTS.md")
        root = repo({"AGENTS.md": "short\n", "a/AGENTS.md": "short\n", "b/AGENTS.md": "short\n"}, toml)
        run(root, "--fix")
        self.assertEqual(read(root, CONFIG), R1_LINE)

    def test_touching_removals_at_the_end_leave_no_blank_line(self):
        toml = entry(path="AGENTS.md", count=2) + "\n" + entry(path="a/AGENTS.md") + entry(path="b/AGENTS.md")
        root = repo({"AGENTS.md": BIG, "a/AGENTS.md": "short\n", "b/AGENTS.md": "short\n"}, toml)
        run(root, "--fix")
        self.assertEqual(read(root, CONFIG), R1_LINE + entry(path="AGENTS.md", count=1))
        md = "# T\n\n" + directive() + "\n" + directive()
        root = repo({"AGENTS.md": md})
        run(root, "--fix")
        self.assertEqual(read(root, "AGENTS.md"), "# T\n")

    def test_config_named_by_absolute_path_is_named_relative_in_fixes(self):
        root = repo({"AGENTS.md": BIG}, entry(count=2))
        doc = json.loads(run(root, "--config", str(root / CONFIG), "--format", "json").stdout)
        self.assertEqual([e["file"] for f in doc["findings"] if f["fix"] for e in f["fix"]["edits"]], [CONFIG])

    def test_crlf_config_keeps_its_line_endings(self):
        toml = (entry(count=2) + "\n" + entry(path="sub/AGENTS.md")).replace("\n", "\r\n")
        root = repo({"AGENTS.md": BIG, "sub/AGENTS.md": "short\n"}, toml)
        run(root, "--fix")
        want = R1_LINE + entry(count=1).replace("\n", "\r\n")
        self.assertEqual(read(root, CONFIG), want)

    def test_only_suggestions_for_entries_a_fix_must_not_touch(self):
        cases = {
            "more findings than count": ({"AGENTS.md": BIG + BIG}, entry(count=1)),
            "file not analyzed": ({"AGENTS.md": "short\n"}, entry(path="docs/gone.md")),
            "expired": ({"AGENTS.md": BIG}, entry(expires="2026-05-01")),
        }
        for name, (files, toml) in cases.items():
            with self.subTest(name):
                root = repo(files, toml)
                before = read(root, CONFIG)
                r = run(root, "--fix", "--unsafe-fixes")
                self.assertEqual(r.returncode, 1)
                self.assertEqual(read(root, CONFIG), before)
                self.assertIn("allowlist", r.stdout)
                # No fix offered at all (safety net 2 would also stop a widening one).
                j = json.loads(run(root, "--format", "json").stdout)
                self.assertEqual([f["fix"] for f in j["findings"] if f["rule"] == "allowlist"],
                                 [None] * len([f for f in j["findings"] if f["rule"] == "allowlist"]))
                self.assertNotIn("no fix applied", r.stderr)

    def test_inherited_entries_are_not_edited(self):
        # `allowlist.entries` replaces as a whole along `extends` (config._merge): with none of its own,
        # the run's config takes the parent's list, and the parent is not the file this run loads.
        files = {"AGENTS.md": BIG, "base.toml": R1_LINE + entry(count=3)}
        root = helpers.make_repo({**files, CONFIG: 'extends = ["base.toml"]\n'})
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(read(root, "base.toml"), R1_LINE + entry(count=3))
        self.assertIn("lower count to 1", r.stdout)

    def test_inherited_entries_are_not_edited_even_when_the_own_file_looks_like_it_has_one(self):
        own = ('extends = ["base.toml"]\n[[overrides]]\npaths = ["x/*.md"]\nrules = { R2 = "off" }\n'
               "reason = '''\n[[allowlist.entries]]\ncount = 3\n'''\n")
        root = helpers.make_repo({"AGENTS.md": BIG, "x/a.md": "x\n", "base.toml": R1_LINE + entry(count=3), CONFIG: own})
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual((read(root, CONFIG), read(root, "base.toml")), (own, R1_LINE + entry(count=3)))
        self.assertIn("lower count to 1", r.stdout)

    def test_own_entries_replace_inherited_ones(self):
        files = {"AGENTS.md": BIG, "base.toml": R1_LINE + entry(path="other.md")}
        root = helpers.make_repo({**files, CONFIG: 'extends = ["base.toml"]\n' + entry(count=2)})
        r = run(root, "--fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)  # base.toml's entry is not in force
        self.assertEqual(read(root, CONFIG), 'extends = ["base.toml"]\n' + entry(count=1))
        self.assertEqual(read(root, "base.toml"), R1_LINE + entry(path="other.md"))

    def test_config_named_by_option(self):
        root = helpers.make_repo({"AGENTS.md": BIG, "lint/my.toml": R1_LINE + entry(count=2)})
        r = run(root, "--config", "lint/my.toml", "--fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(read(root, "lint/my.toml"), R1_LINE + entry(count=1))

    def test_unusual_toml_falls_back_to_a_suggestion(self):
        head = '[[allowlist.entries]]\nrule = "R1d"\npath = "AGENTS.md"\nexpires = 2026-06-30\n'
        cases = {
            # A line in a multi-line string, before the real key, that looks like the count: the edit
            # lands in the string, and safety net 1 sees the reason change.
            "multi-line reason": head + 'reason = """\ncount = 3\nsee the ticket"""\ncount = 3\n',
            # A line in a string that looks like a table header ends the located block before `count`.
            "header in a string": head + "reason = '''\n[rules.R2]\n'''\ncount = 3\n",
            "inline table": ('[allowlist]\nentries = [{rule = "R1d", path = "AGENTS.md", count = 3, '
                             'reason = "x", expires = 2026-06-30}]\n'),
            "hex count": head + 'reason = "x"\ncount = 0x3\n',
        }
        for name, toml in cases.items():
            with self.subTest(name):
                root = repo({"AGENTS.md": BIG}, toml)
                before = read(root, CONFIG)
                r = run(root, "--fix")
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertEqual(read(root, CONFIG), before)
                self.assertIn("lower count to 1", r.stdout)
                j = json.loads(run(root, "--format", "json").stdout)
                self.assertEqual([f["fix"] for f in j["findings"] if f["rule"] == "allowlist"], [None])

    def test_removal_that_would_cut_an_entry_falls_back_to_a_suggestion(self):
        cases = {
            # The string's header-like line ends the located block inside the string: safety net 1.
            "header in a string": entry(reason="'''\n[rules.R2]\n'''"),
            # One header too many: the locator gives up.
            "entry header in a string": entry(reason="'''\n[[allowlist.entries]]\n'''"),
        }
        for name, first in cases.items():
            with self.subTest(name):
                root = repo({"AGENTS.md": "short\n", "sub/AGENTS.md": BIG}, first + entry(path="sub/AGENTS.md"))
                before = read(root, CONFIG)
                r = run(root, "--fix")
                self.assertEqual(read(root, CONFIG), before)
                self.assertIn("no longer needed (file no longer violates R1d); remove it", r.stdout)


class ModeTest(unittest.TestCase):
    def setUp(self):
        self.text = "# T\n" + directive() + "short\n"
        self.root = repo({"AGENTS.md": self.text})

    def test_without_fix_nothing_is_written(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts}
        for args in ([], ["--format", "json"], ["--format", "sarif"], ["--warn-as-error"]):
            run(self.root, *args)
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts}
        self.assertEqual(before, after)

    def test_diff_prints_and_does_not_write(self):
        r = run(self.root, "--diff")
        self.assertEqual(r.returncode, 0, r.stderr)  # the exit code is the findings' (docs/adr/0004)
        self.assertEqual(read(self.root, "AGENTS.md"), self.text)
        self.assertEqual(r.stdout, (
            "--- a/AGENTS.md\n+++ b/AGENTS.md\n@@ -1,3 +1,2 @@\n # T\n"
            "-<!-- agentfile-lint-disable-next-line R1d -- generated table, wrapped upstream -->\n short\n"
        ))

    def test_diff_with_nothing_to_fix(self):
        root = repo({"AGENTS.md": "short\n"})
        r = run(root, "--diff")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_diff_exit_code_is_the_findings(self):
        root = repo({"AGENTS.md": "# T\n" + directive() + "short\n" + BIG})
        r = run(root, "--diff")
        self.assertEqual(r.returncode, 1)  # the R1d error, which no fix touches
        self.assertIn("-<!-- agentfile-lint-disable-next-line", r.stdout)

    def test_diff_applies_with_git(self):
        # Lines are split as the rules split them: U+2028 and lone CR do not cut a line in the diff.
        text = "# T\nSee a\u2028b here.\n" + directive() + "short\rend\n"
        root = repo({"AGENTS.md": text})
        env = dict(os.environ, PYTHONPATH=str(helpers.REPO))
        r = subprocess.run([sys.executable, "-m", "agentfile_lint", "--today", TODAY, "--diff"],
                           cwd=root, env=env, capture_output=True)  # bytes: text mode would turn CR into LF
        patch = root / "fix.patch"
        patch.write_bytes(r.stdout)
        check = subprocess.run(["git", "-C", str(root), "apply", str(patch)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr + r.stdout.decode())
        self.assertEqual(read(root, "AGENTS.md"), "# T\nSee a\u2028b here.\nshort\rend\n")

    def test_unwritable_file_writes_nothing(self):
        root = repo({"AGENTS.md": "# T\n" + directive() + "short\n", "z/AGENTS.md": "# Z\n" + directive() + "short\n"})
        (root / "z/AGENTS.md").chmod(0o444)
        try:
            r = run(root, "--fix")
        finally:
            (root / "z/AGENTS.md").chmod(0o644)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no file was changed", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(read(root, "AGENTS.md"), "# T\n" + directive() + "short\n")

    def test_fix_is_idempotent(self):
        dup = "Run make check before every push to the remote.\n"
        root = repo({"AGENTS.md": dup + BIG, "sub/AGENTS.md": directive("R5a, R1d -- copied") + dup + directive() + "short\n"},
                    entry(count=3))
        run(root, "--fix", "--unsafe-fixes")
        first = {n: read(root, n) for n in ("AGENTS.md", "sub/AGENTS.md", CONFIG)}
        r = run(root, "--fix", "--unsafe-fixes")
        self.assertEqual({n: read(root, n) for n in first}, first)
        self.assertNotIn("fixed", r.stderr)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_usage_errors(self):
        for args in (["--unsafe-fixes"], ["--diff", "--fix"], ["--diff", "--format", "json"]):
            with self.subTest(args):
                r = run(self.root, *args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(read(self.root, "AGENTS.md"), self.text)

    def test_fix_output_in_other_formats_lists_the_rest(self):
        root = repo({"AGENTS.md": "# T\n" + directive() + "short\n" + BIG})
        r = run(root, "--fix", "--format", "json")
        self.assertEqual(r.returncode, 1)
        self.assertEqual([f["rule"] for f in json.loads(r.stdout)["findings"]], ["R1d"])


class OutputTest(unittest.TestCase):
    def test_json_carries_the_fix(self):
        root = repo({"AGENTS.md": "# T\n" + directive() + "short\n" + BIG})
        doc = json.loads(run(root, "--format", "json").stdout)
        fixes = {f["rule"]: f["fix"] for f in doc["findings"]}
        self.assertIsNone(fixes["R1d"])
        self.assertEqual(fixes["disable"], {
            "applicability": "safe",
            "description": "remove the directive",
            "edits": [{"file": "AGENTS.md", "start": {"line": 2, "column": 1}, "end": {"line": 3, "column": 1}, "text": ""}],
        })

    def test_json_allowlist_fix_names_the_config_file(self):
        root = repo({"AGENTS.md": BIG}, entry(count=3))
        doc = json.loads(run(root, "--format", "json").stdout)
        (fix,) = [f["fix"] for f in doc["findings"]]
        count_line = (R1_LINE + entry(count=3)).splitlines().index("count = 3") + 1
        self.assertEqual(fix["edits"], [{"file": CONFIG, "start": {"line": count_line, "column": 9},
                                         "end": {"line": count_line, "column": 10}, "text": "1"}])
        self.assertEqual(fix["applicability"], "safe")

    def test_sarif_fixes(self):
        dup = "Run make check before every push to the remote.\n"
        root = repo({"AGENTS.md": dup, "sub/AGENTS.md": directive("R5a, R1d -- copied") + dup + BIG})
        log = json.loads(run(root, "--format", "sarif").stdout)
        run_ = log["runs"][0]
        self.assertEqual(run_["columnKind"], "unicodeCodePoints")
        (result,) = [r for r in run_["results"] if r["ruleId"] == "disable"]
        self.assertEqual(result["fixes"], [{
            "description": {"text": "remove R1d from the directive (unsafe: the reason may be about R1d)"},
            "artifactChanges": [{
                "artifactLocation": {"uri": "sub/AGENTS.md"},
                "replacements": [{
                    "deletedRegion": {"startLine": 1, "startColumn": 39, "endLine": 1, "endColumn": 47},
                    "insertedContent": {"text": "R5a"},
                }],
            }],
        }])
        self.assertNotIn("fixes", [r for r in run_["results"] if r["ruleId"] == "R1d"][0])


if __name__ == "__main__":
    unittest.main()
