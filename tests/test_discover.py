import subprocess
import unittest

import helpers
from agentfile_lint import discover

GLOBS = ["AGENTS.md", "**/AGENTS.md", "CLAUDE.md", "**/CLAUDE.md"]
DEFAULT_EXTRA = ["**/CLAUDE.local.md", "**/.claude/rules/**/*.md"]  # in the default since 0.9.0
BIG = "x" * 600 + "\n"
R1_LINE = {".agentfile-lint.toml": "[rules.R1d]\nlevel = \"error\"\nmax_chars = 500\n"}  # BIG violates it, if analyzed


class DiscoverTest(unittest.TestCase):
    def test_local_md_files_only_through_a_glob_that_names_them(self):
        # A `.local.md` file is analyzed only when a glob that itself ends in `.local.md` matches it;
        # the default names CLAUDE.local.md, which Claude Code loads like CLAUDE.md (docs/design.md).
        files = {"AGENTS.md": "ok\n", "NOTES.local.md": BIG, "GEMINI.local.md": BIG, "sub/CLAUDE.local.md": BIG,
                 "CLAUDE.local.md": "ok\n"}
        root = helpers.make_repo({**files, **R1_LINE})
        default = GLOBS + DEFAULT_EXTRA
        self.assertEqual(discover.matching_files(root, default, discover.list_files(root)),
                         ["AGENTS.md", "CLAUDE.local.md", "sub/CLAUDE.local.md"])
        self.assertEqual(discover.matching_files(root, ["**/*.md"], discover.list_files(root)), ["AGENTS.md"])
        self.assertEqual(discover.matching_files(root, ["**/*.local.md"], discover.list_files(root)),
                         ["CLAUDE.local.md", "GEMINI.local.md", "NOTES.local.md", "sub/CLAUDE.local.md"])
        r = helpers.run_new(root)
        self.assertEqual(r.returncode, 1)
        self.assertEqual([x.split(":")[0] for x in r.stdout.splitlines() if ": R1d: " in x], ["sub/CLAUDE.local.md"])

    def test_default_globs_include_claude_rules_and_local_files(self):
        root = helpers.make_repo({
            ".claude/rules/a.md": "a\n", ".claude/rules/x/b.md": "b\n", "sub/.claude/rules/c.md": "c\n",
            ".claude/rules/notes.txt": "n\n", ".claude/CLAUDE.md": "d\n", "CLAUDE.local.md": "e\n",
            ".claude/settings.json": "{}\n",
        })
        import json
        doc = json.loads(helpers.run_new(root, "config", "--format", "json").stdout)
        self.assertEqual(doc["discover"]["globs"], GLOBS + DEFAULT_EXTRA)
        self.assertEqual(discover.matching_files(root, doc["discover"]["globs"], discover.list_files(root)),
                         [".claude/CLAUDE.md", ".claude/rules/a.md", ".claude/rules/x/b.md", "CLAUDE.local.md",
                          "sub/.claude/rules/c.md"])

    def test_an_override_reaches_a_local_file(self):
        # Overrides and other path filters are plain globs: the `.local.md` rule is discovery's alone.
        toml = ('[rules.R1d]\nlevel = "error"\nmax_chars = 500\n'
                '[[overrides]]\npaths = ["sub/**"]\nrules = { R1d = "off" }\nreason = "generated"\n')
        root = helpers.make_repo({"AGENTS.md": "ok\n", "sub/CLAUDE.local.md": BIG, ".agentfile-lint.toml": toml})
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
        self.assertFalse(discover.discovered("NOTES.local.md", ["*.md"]))
        self.assertTrue(discover.discovered("NOTES.local.md", ["*.local.md"]))
        self.assertTrue(discover.matches("NOTES.local.md", ["*.md"]))  # a plain glob match

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
