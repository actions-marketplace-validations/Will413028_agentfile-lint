import unittest
from pathlib import Path

import helpers
from agentfile_lint import config
import datetime

TODAY = datetime.date(2026, 6, 1)


def run(toml, *extra):
    root = helpers.make_repo({"AGENTS.md": "ok\n", ".agentfile-lint.toml": toml})
    return helpers.run_new(root, "--today", "2026-06-01", *extra)


LIMIT_100 = '[[rules.R1a.limits]]\nglob = "AGENTS.md"\nmax_bytes = 100\n'


class ConfigTest(unittest.TestCase):
    def test_no_config_uses_preset(self):
        root = helpers.make_repo({"AGENTS.md": "ok\n"})
        self.assertEqual(helpers.run_new(root).returncode, 0)

    def test_unknown_top_level_key_fails(self):
        r = run("bogus = 1\n")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown key(s) bogus", r.stderr)

    def test_unknown_rule_key_fails(self):
        r = run("[rules.R1d]\nmax_char = 400\n")  # typo
        self.assertEqual(r.returncode, 2)
        self.assertIn("max_char", r.stderr)

    def test_unknown_rule_id_fails(self):
        r = run("[rules.R99]\nlevel = 'error'\n")
        self.assertEqual(r.returncode, 2)
        self.assertIn("R99", r.stderr)

    def test_unknown_tier_key_fails(self):
        r = run("[rules.R1a.max_bytes]\nroots = 5\n")
        self.assertEqual(r.returncode, 2)

    def test_unknown_allowlist_key_fails(self):
        r = run("[allowlist]\nmax_day = 5\n")
        self.assertEqual(r.returncode, 2)

    def test_bad_level_fails(self):
        r = run("[rules.R1a]\nlevel = 'fatal'\n")
        self.assertEqual(r.returncode, 2)

    def test_invalid_toml_fails(self):
        r = run("this is = = not toml")
        self.assertEqual(r.returncode, 2)

    def test_repo_override_changes_a_single_limit(self):
        root = helpers.make_repo({"AGENTS.md": "x\n" * 60, ".agentfile-lint.toml": LIMIT_100})
        r = helpers.run_new(root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGENTS.md: error: R1a: file is 120 bytes, limit 100", r.stdout)

    def test_levels_warn_and_off(self):
        files = {"AGENTS.md": "y" * 600 + "\n"}
        warn = helpers.make_repo({**files, ".agentfile-lint.toml": "[rules.R1d]\nlevel = 'warn'\nmax_chars = 500\n"})
        r = helpers.run_new(warn)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn("AGENTS.md:1: warning: R1d: line is 600 characters, limit 500", r.stdout)
        off = helpers.make_repo({**files, ".agentfile-lint.toml": "[rules.R1d]\nlevel = 'off'\nmax_chars = 500\n"})
        r = helpers.run_new(off)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_extends_relative_file_and_cycle(self):
        root = helpers.make_repo({
            "AGENTS.md": "x\n" * 60,
            "base.toml": LIMIT_100,
            ".agentfile-lint.toml": "extends = ['preset:default', 'base.toml']\n",
        })
        self.assertEqual(helpers.run_new(root).returncode, 1)
        cyc = helpers.make_repo({"AGENTS.md": "ok\n", "a.toml": "extends = ['b.toml']\n", "b.toml": "extends = ['a.toml']\n"})
        r = helpers.run_new(cyc, "--config", "a.toml")
        self.assertEqual(r.returncode, 2)
        self.assertIn("cycle", r.stderr)

    def test_unknown_preset_fails(self):
        r = run("extends = ['preset:nope']\n")
        self.assertEqual(r.returncode, 2)

    def test_list_rules_shows_effective_levels(self):
        root = helpers.make_repo({"AGENTS.md": "ok\n", ".agentfile-lint.toml": "[rules.R1c]\nlevel = 'warn'\n"})
        r = helpers.run_new(root, "--list-rules")
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"(?m)^R1c  warn +path-bytes:")
        self.assertRegex(r.stdout, r"(?m)^R1a  error +file-bytes:")

    def test_legacy_config_name_fails_with_rename_hint(self):
        root = helpers.make_repo({"AGENTS.md": "ok\n", ".instruction-lint.toml": "[rules.R1]\nlevel = 'warn'\n"})
        for args in ((), ("--list-rules",), ("config",), ("check-pins",)):
            r = helpers.run_new(root, *args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("rename it to .agentfile-lint.toml", r.stderr)

    def test_new_name_wins_over_legacy_name(self):
        root = helpers.make_repo({"AGENTS.md": "ok\n", ".instruction-lint.toml": "x = 1\n", ".agentfile-lint.toml": ""})
        self.assertEqual(helpers.run_new(root).returncode, 0)

    def test_bad_today_is_usage_error(self):
        root = helpers.make_repo({"AGENTS.md": "ok\n"})
        self.assertEqual(helpers.run_new(root, "--today", "yesterday").returncode, 2)

    def test_config_load_api(self):
        cfg = config.load(None, TODAY)
        self.assertEqual(cfg.rules["R1d"], {"level": "off"})  # no max_chars in the default: no line-length check
        self.assertEqual(cfg.rules["R1c"]["limits"][0]["max_bytes"], 32768)
        self.assertEqual(cfg.shared["duplicates"]["ancestor_pairs"], "same-name")

    def test_config_json_has_shared_and_every_id(self):
        import json
        r = helpers.run_new(helpers.make_repo({"AGENTS.md": "ok\n"}), "config", "--format", "json")
        doc = json.loads(r.stdout)
        self.assertEqual(doc["shared"], {
            "size": {"excluded_blocks": []},
            "duplicates": {"ancestor_pairs": "same-name", "min_chars": 40, "ignore_headings": True, "ignore_patterns": [], "exclude": []},
        })
        self.assertEqual(list(doc["rules"]), sorted(["R1a", "R1b", "R1c", "R1d", "R2", "R3a", "R3b", "R3c", "R4a", "R4b", "R5a", "R5b", "R6", "C1"]
                                                    + [f"S{i}" for i in range(1, 13)] + [f"H{i}" for i in range(1, 7)]
                                                    + [f"M{i}" for i in range(1, 5)]))
        self.assertEqual(doc["rules"]["R5b"], {"level": "off"})

    def test_shared_merges_key_by_key_through_extends(self):
        root = helpers.make_repo({
            "AGENTS.md": "ok\n", "base.toml": "extends = []\n[shared.duplicates]\nmin_chars = 10\n",
            ".agentfile-lint.toml": "extends = ['preset:strict', 'base.toml']\n",
        })
        import json
        doc = json.loads(helpers.run_new(root, "config").stdout)
        self.assertEqual((doc["shared"]["duplicates"]["min_chars"], doc["shared"]["duplicates"]["ancestor_pairs"]), (10, "any"))


if __name__ == "__main__":
    unittest.main()
