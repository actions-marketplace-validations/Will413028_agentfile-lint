"""Symlinked instruction files (e.g. CLAUDE.md -> AGENTS.md) are aliases of their target, not copies."""
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers

LONG = "# Project\n\n" + "".join(f"- Rule {i} keeps the build reproducible on every machine we use.\n" for i in range(230))
ARGS = ("--today", "2026-06-01")


def lint(files, symlinks, config=""):
    files = dict(files)
    if config:
        files[".agentfile-lint.toml"] = config
    r = helpers.run_new(helpers.make_repo(files, symlinks=symlinks), *ARGS)
    return r.returncode, r.stdout.splitlines() + r.stderr.splitlines()


def on(path, lines):
    return [line for line in lines if line.startswith(f"{path}:")]


class SymlinkAliasTest(unittest.TestCase):
    def test_claude_md_symlink_to_agents_md_is_not_checked_again(self):
        _, lines = lint({"AGENTS.md": LONG}, {"CLAUDE.md": "AGENTS.md"}, '[rules.C1]\nlevel = "error"\n')
        self.assertEqual(on("CLAUDE.md", lines), [])                       # no R1b, R5a or C1 on the alias
        self.assertEqual(len([x for x in on("AGENTS.md", lines) if ": R1b: " in x]), 1)  # target still checked once (its line count)

    def test_nested_symlink_to_an_ancestor_file_is_checked_as_its_own_file(self):
        # An agent working in sub/ loads both files, so the repeated lines are real duplicates.
        _, lines = lint({"AGENTS.md": LONG}, {"sub/AGENTS.md": "../AGENTS.md"})
        self.assertTrue([x for x in on("sub/AGENTS.md", lines) if ": R5a: line repeats AGENTS.md:" in x])

    def test_symlinks_in_other_directories_are_separate_load_locations(self):
        files = {"docs/shared.md": LONG}
        _, lines = lint(files, {"z/AGENTS.md": "../docs/shared.md", "a/b/AGENTS.md": "../../docs/shared.md"})
        self.assertTrue([x for x in on("z/AGENTS.md", lines) if ": R1b: " in x])
        self.assertTrue([x for x in on("a/b/AGENTS.md", lines) if ": R1b: " in x])

    def test_two_symlinks_in_one_directory_to_an_ancestor_file_are_checked_once(self):
        _, lines = lint({"AGENTS.md": LONG}, {"sub/AGENTS.md": "../AGENTS.md", "sub/CLAUDE.md": "../AGENTS.md"}, '[rules.C1]\nlevel = "error"\n')
        self.assertEqual(on("sub/CLAUDE.md", lines), [])  # alias of sub/AGENTS.md; C1 accepts it
        self.assertTrue([x for x in on("sub/AGENTS.md", lines) if ": R5a: line repeats AGENTS.md:" in x])

    def test_c1_accepts_the_symlink_when_globs_leave_out_claude_md(self):
        cfg = '[discover]\nglobs = ["AGENTS.md", "**/AGENTS.md"]\n[rules.C1]\nlevel = "error"\n'
        rc, lines = lint({"AGENTS.md": "ok\n"}, {"CLAUDE.md": "AGENTS.md"}, cfg)
        self.assertEqual((rc, [x for x in lines if ": C1: " in x]), (0, []))

    def test_agents_md_symlink_to_claude_md_checks_claude_md_as_the_real_file(self):
        _, lines = lint({"CLAUDE.md": LONG}, {"AGENTS.md": "CLAUDE.md"}, '[rules.C1]\nlevel = "error"\n')
        self.assertEqual(on("AGENTS.md", lines), [])
        self.assertIn("CLAUDE.md: error: C1: CLAUDE.md must contain only the line '@AGENTS.md'", lines)

    def test_forbid_still_reports_a_symlinked_claude_md(self):
        _, lines = lint({"AGENTS.md": "ok\n"}, {"CLAUDE.md": "AGENTS.md"}, '[rules.C1]\nlevel = "error"\nmode = "forbid"\n')
        self.assertEqual([x for x in lines if ": C1: " in x], ["CLAUDE.md: error: C1: CLAUDE.md must not exist (mode forbid); keep the instructions in AGENTS.md"])

    def test_symlink_to_a_file_outside_the_repo_is_checked_as_its_own_file(self):
        tmp = Path(tempfile.mkdtemp(prefix="il-outside-"))
        self.addCleanup(shutil.rmtree, tmp)
        outside = tmp / "shared.md"
        outside.write_text(LONG, encoding="utf-8")
        _, lines = lint({}, {"AGENTS.md": str(outside)})
        self.assertEqual(len([x for x in on("AGENTS.md", lines) if ": R1b: " in x]), 1)

    def test_dangling_symlink_is_skipped(self):
        rc, lines = lint({"AGENTS.md": "ok\n"}, {"CLAUDE.md": "missing.md"})
        self.assertEqual((rc, on("CLAUDE.md", lines)), (0, []))

    def test_symlink_loop_next_to_claude_md_does_not_crash(self):
        rc, lines = lint({"real.md": "ok\n"}, {"CLAUDE.md": "real.md", "AGENTS.md": "AGENTS.md"}, '[rules.C1]\nlevel = "error"\n')
        self.assertNotIn("Traceback (most recent call last):", lines)
        self.assertEqual(rc, 1)
        self.assertIn("CLAUDE.md: error: C1: CLAUDE.md must contain only the line '@AGENTS.md'", lines)

    def test_link_name_in_other_case_is_never_checked_twice(self):
        # Case-insensitive file system: an alias of AGENTS.md. Case-sensitive: a dangling link, skipped.
        rc, lines = lint({"AGENTS.md": "ok\n"}, {"CLAUDE.md": "agents.md"}, '[rules.C1]\nlevel = "error"\n')
        self.assertEqual((rc, on("CLAUDE.md", lines)), (0, []))

    def test_allowlist_entry_for_an_alias_is_no_longer_needed(self):
        entry = '[[allowlist.entries]]\nrule = "R1b"\npath = "CLAUDE.md"\ncount = 1\nreason = "split later"\nexpires = 2026-06-30\n'
        rc, lines = lint({"AGENTS.md": LONG}, {"CLAUDE.md": "AGENTS.md"}, entry)
        self.assertEqual(rc, 1)
        self.assertIn("is no longer needed (file is not an analyzed instruction file)", "\n".join(on("CLAUDE.md", lines)))


if __name__ == "__main__":
    unittest.main()
