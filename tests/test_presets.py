"""The default preset runs only objective checks; `preset:strict` adds the heuristic rules and C1."""
import unittest

import helpers

# One file set that trips R3b, R4a (a date), R4b (a narrative word), R5b (siblings), R6 and C1.
LINE = "Keep every generated client in sync with the schema before you open a pull request.\n"
FILES = {
    "AGENTS.md": "See `gone/file.go` for details.\nShipped on 2026-01-02, currently behind a flag.\n"
                 "Set `MAX_RETRIES = 5` in the client.\n",
    "CLAUDE.md": "Read AGENTS.md first.\n",
    "a/AGENTS.md": LINE,
    "b/AGENTS.md": LINE,
}
HEURISTIC = ("R3b", "R4a", "R4b", "R5b", "R6", "C1")


def rules_hit(config=None):
    files = dict(FILES)
    if config is not None:
        files[".agentfile-lint.toml"] = config
    r = helpers.run_new(helpers.make_repo(files), "--today", "2026-06-01")
    lines = r.stdout.splitlines() + r.stderr.splitlines()
    return r.returncode, {rule for rule in HEURISTIC if any(f": {rule}: " in x for x in lines)}, lines


class PresetsTest(unittest.TestCase):
    def test_default_runs_none_of_the_heuristic_rules(self):
        rc, hit, lines = rules_hit()
        self.assertEqual((rc, hit), (0, set()), lines)

    def test_strict_turns_them_all_on_as_warnings(self):
        rc, hit, lines = rules_hit('extends = ["preset:strict"]\n')
        self.assertEqual(hit, set(HEURISTIC), lines)
        self.assertEqual(rc, 0, lines)  # warnings only: strict adds no error

    def test_strict_extends_default_for_everything_else(self):
        root = helpers.make_repo({"AGENTS.md": "x" * 99 + "\n" * 1 + ("y" * 99 + "\n") * 330,
                                  ".agentfile-lint.toml": 'extends = ["preset:strict"]\n'})
        r = helpers.run_new(root)
        self.assertEqual(r.returncode, 1)  # the default R1c 32 KiB error still applies
        self.assertIn("AGENTS.md: error: R1c: file is 33100 bytes, limit 32768", r.stdout)

    def test_a_repo_config_overrides_strict(self):
        _, hit, lines = rules_hit('extends = ["preset:strict"]\n[rules.R4b]\nlevel = "off"\n')
        self.assertEqual(hit, set(HEURISTIC) - {"R4b"}, lines)

    def test_effective_levels_in_config_json(self):
        import json
        def levels(toml):
            files = {"AGENTS.md": "ok\n"} | ({".agentfile-lint.toml": toml} if toml else {})
            r = helpers.run_new(helpers.make_repo(files), "config", "--format", "json")
            self.assertEqual(r.returncode, 0, r.stderr)
            doc = json.loads(r.stdout)
            return {k: doc["rules"][k]["level"] for k in HEURISTIC + ("R5a",)}, doc["shared"]["duplicates"]["ancestor_pairs"]
        off = dict.fromkeys(HEURISTIC, "off")
        self.assertEqual(levels(""), ({**off, "R5a": "warn"}, "same-name"))
        self.assertEqual(levels('extends = ["preset:strict"]\n'), (dict.fromkeys(HEURISTIC + ("R5a",), "warn"), "any"))

    def test_vendored_copy_ships_strict(self):
        import subprocess, sys, tempfile
        from pathlib import Path
        out = Path(tempfile.mkdtemp(prefix="il-vendor-")) / "v"
        r = subprocess.run([sys.executable, "-m", "agentfile_lint", "vendor", "--to", str(out), "--ref-tag", "v9.9.9",
                            "--ref-commit", "a" * 40], cwd=helpers.REPO, capture_output=True, text=True,
                           env={**__import__("os").environ, "PYTHONPATH": str(helpers.REPO)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((out / "agentfile_lint" / "presets" / "strict.toml").is_file())


if __name__ == "__main__":
    unittest.main()
