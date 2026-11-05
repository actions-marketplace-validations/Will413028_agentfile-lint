import subprocess
import unittest

import helpers
from agentfile_lint import discover

GLOBS = ["AGENTS.md", "**/AGENTS.md", "CLAUDE.md", "**/CLAUDE.md"]
BIG = "x" * 600 + "\n"
R1_LINE = {".agentfile-lint.toml": "[rules.R1d]\nlevel = \"error\"\nmax_chars = 500\n"}  # BIG violates it, if analyzed


class DiscoverTest(unittest.TestCase):
    def test_ignores_local_md_files_even_when_tracked(self):
        root = helpers.make_repo({"AGENTS.md": "ok\n", "NOTES.local.md": BIG, "sub/CLAUDE.local.md": BIG, **R1_LINE})
        self.assertEqual(discover.matching_files(root, GLOBS, discover.list_files(root)), ["AGENTS.md"])
        self.assertEqual(helpers.run_new(root).returncode, 0)

    def test_ignores_untracked_files(self):
        root = helpers.make_repo({"AGENTS.md": "ok\n", **R1_LINE})
        (root / "sub").mkdir()
        (root / "sub" / "AGENTS.md").write_text(BIG)  # not added to git
        self.assertEqual(discover.matching_files(root, GLOBS, discover.list_files(root)), ["AGENTS.md"])
        self.assertEqual(helpers.run_new(root).returncode, 0)

    def test_finds_nested_agents_and_claude_files(self):
        root = helpers.make_repo({"AGENTS.md": "a", "a/b/AGENTS.md": "a", "CLAUDE.md": "@AGENTS.md\n", "x/CLAUDE.md": "c", "notes.md": "n"})
        self.assertEqual(
            discover.matching_files(root, GLOBS, discover.list_files(root)),
            ["AGENTS.md", "CLAUDE.md", "a/b/AGENTS.md", "x/CLAUDE.md"],
        )

    def test_skips_tracked_but_deleted_files(self):
        root = helpers.make_repo({"AGENTS.md": "ok\n", "sub/AGENTS.md": "ok\n"})
        (root / "sub" / "AGENTS.md").unlink()
        self.assertEqual(helpers.run_new(root).returncode, 0)

    def test_glob_semantics(self):
        self.assertTrue(discover.matches("AGENTS.md", ["AGENTS.md"]))
        self.assertFalse(discover.matches("sub/AGENTS.md", ["AGENTS.md"]))
        self.assertTrue(discover.matches("a/b/AGENTS.md", ["**/AGENTS.md"]))
        self.assertTrue(discover.matches("AGENTS.md", ["**/AGENTS.md"]))
        self.assertFalse(discover.matches("a/MYAGENTS.md", ["**/AGENTS.md"]))
        self.assertFalse(discover.matches("NOTES.local.md", ["*.md"]))

    def test_argv_names_only_decide_whether_to_run(self):
        # sub/AGENTS.md violates; passing only the clean root file still analyzes the full set.
        root = helpers.make_repo({"AGENTS.md": "ok\n", "sub/AGENTS.md": BIG, "README.md": "r\n", **R1_LINE})
        r = helpers.run_new(root, "AGENTS.md")
        self.assertEqual(r.returncode, 1)
        self.assertIn("sub/AGENTS.md:1: error: R1d", r.stdout)
        # An irrelevant file name skips the run entirely.
        self.assertEqual(helpers.run_new(root, "README.md").returncode, 0)

    def test_not_a_git_repo_is_a_usage_error(self):
        import tempfile, pathlib
        d = pathlib.Path(tempfile.mkdtemp(prefix="il-nogit-"))
        r = helpers.run_new(d)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
