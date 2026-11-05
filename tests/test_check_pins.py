import json
import unittest

import helpers

SHA_A = "a" * 40
SHA_B = "b" * 40
URL = "https://github.com/example/agentfile-lint"

PRECOMMIT = f"""repos:
  - repo: https://github.com/example/other-hook
    rev: v1.0.0
    hooks:
      - id: other
  - repo: {URL}
    rev: {{rev}}  # v0.2.0
    hooks:
      - id: agentfile-lint
        pass_filenames: false
"""
LEFTHOOK = f"""pre-commit:
  commands:
    agentfile-lint:
      run: uvx --from git+{URL}@{{sha}} agentfile-lint
"""
WORKFLOW = """jobs:
  lint:
    steps:
      - uses: actions/checkout@{c}
      - uses: example/agentfile-lint@{sha} # v0.2.0
"""


def check(files, *args):
    r = helpers.run_new(helpers.make_repo(files), "check-pins", *args)
    return r.returncode, r.stdout, r.stderr


class CheckPinsTest(unittest.TestCase):
    def test_same_sha_everywhere_passes(self):
        files = {
            ".pre-commit-config.yaml": PRECOMMIT.format(rev=SHA_A),
            "lefthook.yml": LEFTHOOK.format(sha=SHA_A),
            ".github/workflows/ci.yml": WORKFLOW.format(c="c" * 40, sha=SHA_A),
        }
        rc, out, err = check(files)
        self.assertEqual((rc, out), (0, ""))  # stdout holds findings only; the summary is on stderr
        self.assertIn(f"3 reference(s) to 'agentfile-lint', all pinned to {SHA_A}", err)

    def test_two_different_shas_fail_with_file_and_line(self):
        files = {
            ".pre-commit-config.yaml": PRECOMMIT.format(rev=SHA_A),
            ".github/workflows/ci.yml": WORKFLOW.format(c="c" * 40, sha=SHA_B),
        }
        rc, out, err = check(files)
        self.assertEqual((rc, err), (1, ""))
        self.assertEqual(
            out.splitlines(),
            [f".pre-commit-config.yaml:7: error: check-pins: pinned to {SHA_A}, but .github/workflows/ci.yml:5 pins {SHA_B}"],
        )

    def test_lefthook_and_workflow_mismatch_fails(self):
        files = {"lefthook.yml": LEFTHOOK.format(sha=SHA_A), ".github/workflows/ci.yml": WORKFLOW.format(c="c" * 40, sha=SHA_B)}
        self.assertEqual(check(files)[0], 1)

    def test_tag_branch_and_short_sha_are_rejected(self):
        for ref in ("v0.2.0", "main", "a" * 7, "A" * 40, "a" * 41):
            rc, out, _ = check({".pre-commit-config.yaml": PRECOMMIT.format(rev=ref)})
            self.assertEqual(rc, 1, ref)
            self.assertIn(".pre-commit-config.yaml:7: error: check-pins: reference is pinned to", out)

    def test_missing_rev_and_unpinned_references_fail(self):
        rc, out, _ = check({".pre-commit-config.yaml": f"repos:\n  - repo: {URL}\n    hooks: []\n"})
        self.assertEqual(rc, 1)
        self.assertIn(".pre-commit-config.yaml:2: error: check-pins: reference is pinned to '(none)'", out)
        rc, _, err = check({"lefthook.yml": f"run: uvx --from git+{URL} agentfile-lint\n"})
        self.assertEqual(rc, 1)

    def test_plain_mentions_are_not_references(self):
        files = {"lefthook.yml": "pre-commit:\n  commands:\n    agentfile-lint:\n      run: agentfile-lint\n"}
        rc, out, err = check(files)
        self.assertEqual((rc, out), (0, ""))
        self.assertIn("no reference", err)
        rc, out, err = check(files, "--require-refs")
        self.assertEqual((rc, out, err), (1, "check-pins: error: no reference to 'agentfile-lint' found\n", ""))

    def test_repo_string_is_configurable(self):
        files = {".pre-commit-config.yaml": PRECOMMIT.format(rev=SHA_A).replace("example/agentfile-lint", "acme/linter")}
        self.assertIn("no reference", check(files)[2])
        rc, _, err = check(files, "--repo", "acme/linter")
        self.assertEqual(rc, 0)
        self.assertIn("1 reference(s)", err)

    def test_repo_string_and_files_come_from_the_config(self):
        files = {
            ".agentfile-lint.toml": '[check_pins]\nrepo = "acme/linter"\nfiles = ["tools/*.yml"]\n',
            "tools/hooks.yml": f"run: uvx --from git+https://host/acme/linter@{SHA_A} x\n",
            "lefthook.yml": f"run: uvx --from git+https://host/acme/linter@{SHA_B} x\n",
        }
        rc, _, err = check(files)
        self.assertEqual(rc, 0)  # lefthook.yml is outside the configured files
        self.assertIn("1 reference(s)", err)

    def test_quoted_rev_is_read(self):
        rc, out, _ = check({".pre-commit-config.yaml": PRECOMMIT.format(rev=f"'{SHA_A}'")})
        self.assertEqual(rc, 0)

    def test_untracked_files_are_not_read(self):
        root = helpers.make_repo({"README.md": "x\n"})
        (root / "lefthook.yml").write_text(LEFTHOOK.format(sha="bad"))
        r = helpers.run_new(root, "check-pins")
        self.assertEqual(r.returncode, 0)


class ConfigJsonTest(unittest.TestCase):
    def run_config(self, files, *args):
        r = helpers.run_new(helpers.make_repo(files), "config", "--format", "json", "--today", "2026-06-01", *args)
        return r

    def test_output_is_valid_deterministic_json_with_sorted_keys(self):
        a = self.run_config({"AGENTS.md": "x\n"})
        b = self.run_config({"AGENTS.md": "x\n"})
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(a.stdout, b.stdout)
        data = json.loads(a.stdout)
        self.assertEqual(list(data), sorted(data))
        self.assertEqual(a.stdout, json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
        self.assertEqual(data["rules"]["R1c"]["limits"][0]["max_bytes"], 32768)
        self.assertEqual(data["rules"]["C1"]["mode"], "import-only")

    def test_reflects_the_repo_config_merge(self):
        toml = ('[rules.R2]\nlevel = "error"\n[[rules.R2.shapes]]\nglob = "m/*/AGENTS.md"\nsections = ["A", "B"]\n'
                '[[allowlist.entries]]\nrule = "R1c"\npath = "AGENTS.md"\ncount = 1\nreason = "r"\nexpires = 2026-07-01\n')
        r = self.run_config({"AGENTS.md": "x\n", ".agentfile-lint.toml": toml})
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["rules"]["R2"]["level"], "error")
        self.assertEqual(data["rules"]["R2"]["shapes"][0]["sections"], ["A", "B"])
        self.assertEqual(data["rules"]["R2"]["shapes"][0]["mode"], "exact")  # defaults are filled in
        self.assertEqual(data["allowlist"]["entries"][0]["expires"], "2026-07-01")

    def test_invalid_config_exits_2(self):
        r = self.run_config({"AGENTS.md": "x\n", ".agentfile-lint.toml": "bogus = 1\n"})
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
