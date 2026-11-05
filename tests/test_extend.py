"""0.8.0 config keys: `discover.extend_globs` and `[shared.duplicates] exclude` (docs/adr/0006)."""
import json
import unittest

import helpers

CFG = ".agentfile-lint.toml"
LINE = "- run the full test suite before every single commit, no exceptions\n"


def run(files, *args):
    return helpers.run_new(helpers.make_repo(files), "--today", "2026-06-01", *args)


class ExtendGlobsTest(unittest.TestCase):
    FILES = {"AGENTS.md": b"\xff\n", "GEMINI.md": b"\xff\n"}  # E0 is always on: it shows which files are read
    E0 = "{}: error: E0: file is not valid UTF-8\n"

    def test_adds_to_the_preset_globs(self):
        self.assertEqual(run(self.FILES).stdout, self.E0.format("AGENTS.md"))
        r = run({**self.FILES, CFG: '[discover]\nextend_globs = ["GEMINI.md"]\n'})
        self.assertEqual(r.stdout, self.E0.format("AGENTS.md") + self.E0.format("GEMINI.md"), r.stderr)

    def test_concatenates_along_extends_and_survives_a_child_globs(self):
        root = helpers.make_repo({
            "AGENTS.md": "ok\n", "base.toml": '[discover]\nextend_globs = ["A.md"]\n',
            CFG: 'extends = ["base.toml"]\n[discover]\nglobs = ["AGENTS.md"]\nextend_globs = ["B.md"]\n',
        })
        doc = json.loads(helpers.run_new(root, "config").stdout)
        self.assertEqual(doc["discover"], {"globs": ["AGENTS.md"], "extend_globs": ["A.md", "B.md"]})

    def test_type_error_fails(self):
        for value in ('"GEMINI.md"', "[1]"):
            r = run({"AGENTS.md": "ok\n", CFG: f"[discover]\nextend_globs = {value}\n"})
            self.assertEqual(r.returncode, 2, value)
            self.assertIn("discover.extend_globs", r.stderr)


class ExcludeTest(unittest.TestCase):
    FILES = {"AGENTS.md": LINE, "pkg/AGENTS.md": LINE, "pkg/sub/AGENTS.md": LINE}

    def r5a(self, r):
        return [line for line in r.stdout.splitlines() if ": R5a: " in line]

    def test_baseline(self):
        found = self.r5a(run(self.FILES))
        self.assertEqual([f.split(":")[0] for f in found], ["pkg/AGENTS.md", "pkg/sub/AGENTS.md"])
        self.assertIn("line repeats pkg/AGENTS.md:1", found[1])

    def test_excluded_file_is_neither_reported_nor_an_ancestor(self):
        r = run({**self.FILES, CFG: '[shared.duplicates]\nexclude = ["pkg/AGENTS.md"]\n'})
        found = self.r5a(r)
        self.assertEqual(len(found), 1, r.stdout)
        self.assertTrue(found[0].startswith("pkg/sub/AGENTS.md:1: warning: R5a: line repeats AGENTS.md:1"), found)

    def test_type_error_fails(self):
        r = run({"AGENTS.md": "ok\n", CFG: '[shared.duplicates]\nexclude = "pkg/**"\n'})
        self.assertEqual(r.returncode, 2)
        self.assertIn("shared.duplicates.exclude", r.stderr)

    def test_not_a_rule_key(self):
        r = run({"AGENTS.md": "ok\n", CFG: '[rules.R5a]\nlevel = "error"\nexclude = []\n'})
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown key(s) exclude", r.stderr)


if __name__ == "__main__":
    unittest.main()
