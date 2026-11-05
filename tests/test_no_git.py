"""`--no-git` (docs/design.md, File discovery; docs/adr/0006): walk the directory instead of
`git ls-files`, same globs, a fixed list of skipped directories, no `.gitignore`."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers

LINE = "Run the full check before every push and keep the output in the PR body"  # >= 40 chars: R5a
FILES = {
    "AGENTS.md": LINE + "\n" + "Read `docs/missing.md` first.\n",
    "sub/AGENTS.md": LINE + "\n",
    "docs/present.md": "x\n",
    "sub/CLAUDE.md": "@AGENTS.md\n",
    # R3b reads the whole file set (`docs/present.md` must be found, `docs/missing.md` not); C1 sees CLAUDE.md.
    ".agentfile-lint.toml": '[rules.R3b]\nlevel = "error"\n[rules.C1]\nlevel = "warn"\n',
}


def plain_dir(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp(prefix="il-nogit-"))
    for name, content in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(content, encoding="utf-8")
    return root


class NoGitTest(unittest.TestCase):
    def test_same_findings_as_the_same_content_in_a_git_repo(self):
        tracked = helpers.run_new(helpers.make_repo(FILES), "--today", "2026-06-01")
        walked = helpers.run_new(plain_dir(FILES), "--no-git", "--today", "2026-06-01")
        self.assertEqual(tracked.stderr, "")
        self.assertIn("R3b", tracked.stdout)  # the comparison means something only with findings
        self.assertIn("R5a", tracked.stdout)
        self.assertNotIn("present.md", tracked.stdout)
        self.assertEqual((walked.returncode, walked.stdout, walked.stderr), (tracked.returncode, tracked.stdout, tracked.stderr))

    def test_skipped_directories_are_never_entered(self):
        files = {"AGENTS.md": "# ok\n", "node_modules/pkg/AGENTS.md": "y" * 50000 + "\n",
                 ".git/AGENTS.md": "y" * 50000 + "\n", "vendor/AGENTS.md": "# found\n" + "y" * 50000 + "\n"}
        r = helpers.run_new(plain_dir(files), "--no-git", "--format", "json")
        reported = {f["file"] for f in json.loads(r.stdout)["findings"]}
        self.assertEqual(reported, {"vendor/AGENTS.md"})  # only the fixed list is skipped

    def test_gitignore_is_not_read(self):
        root = plain_dir({"AGENTS.md": "# ok\n", ".gitignore": "build/\n", "build/AGENTS.md": "y" * 50000 + "\n"})
        r = helpers.run_new(root, "--no-git", "--format", "json")
        self.assertIn("build/AGENTS.md", {f["file"] for f in json.loads(r.stdout)["findings"]})

    def test_directory_symlinks_are_not_followed(self):
        root = plain_dir({"AGENTS.md": "# ok\n"})
        outside = plain_dir({"AGENTS.md": "y" * 50000 + "\n"})
        (root / "linked").symlink_to(outside, target_is_directory=True)
        (root / "loop").symlink_to(root, target_is_directory=True)
        r = helpers.run_new(root, "--no-git")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_untracked_files_count_with_no_git_inside_a_repo(self):
        root = helpers.make_repo({"AGENTS.md": "# ok\n"})
        (root / "new").mkdir()
        (root / "new" / "AGENTS.md").write_text("y" * 50000 + "\n", encoding="utf-8")
        self.assertEqual(helpers.run_new(root).returncode, 0)  # default: tracked only
        self.assertEqual(helpers.run_new(root, "--no-git").returncode, 1)

    @unittest.skipIf(helpers.os.geteuid() == 0, "root reads mode-000 directories")
    def test_unreadable_directory_is_exit_2_not_a_partial_set(self):
        root = plain_dir({"AGENTS.md": "# ok\n", "locked/AGENTS.md": "# hidden\n"})
        (root / "locked").chmod(0)
        try:
            r = helpers.run_new(root, "--no-git")
        finally:
            (root / "locked").chmod(0o755)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("cannot read", r.stderr)

    def test_outside_git_without_the_flag_is_still_exit_2(self):
        root = plain_dir({"AGENTS.md": "# ok\n"})
        r = helpers.run_new(root)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not inside a git repository", r.stderr)

    @classmethod
    def tearDownClass(cls):
        for p in Path(tempfile.gettempdir()).glob("il-nogit-*"):
            shutil.rmtree(p, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
