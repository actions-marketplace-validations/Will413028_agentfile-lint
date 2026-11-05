"""Rule aliases: a rule's name is accepted wherever a rule id is, resolved per file before merging."""
import json
import re
import unittest

import helpers
from agentfile_lint.rules import NAMES, RETIRED, RULES


def config_json(toml, *files):
    root = helpers.make_repo({"AGENTS.md": "ok\n", ".agentfile-lint.toml": toml, **dict(files)})
    return helpers.run_new(root, "config", "--today", "2026-06-01")


ENTRY = "[[allowlist.entries]]\nrule = '{rule}'\npath = 'AGENTS.md'\ncount = 1\nreason = 'r'\nexpires = 2026-07-01\n"


class AliasTest(unittest.TestCase):
    def test_alias_and_id_give_the_same_effective_config(self):
        by_id = config_json("[rules.R1a]\nlevel = 'warn'\n" + ENTRY.format(rule="R5a"))
        by_alias = config_json("[rules.file-bytes]\nlevel = 'warn'\n" + ENTRY.format(rule="ancestor-duplicates"))
        self.assertEqual((by_id.returncode, by_alias.returncode), (0, 0), by_alias.stderr)
        self.assertEqual(json.loads(by_alias.stdout), json.loads(by_id.stdout))
        self.assertEqual(json.loads(by_alias.stdout)["rules"]["R1a"]["level"], "warn")

    def test_every_rule_alias_is_accepted(self):
        for rule_id, name in NAMES.items():
            r = config_json(f"[rules.{name}]\nlevel = 'off'\n")
            self.assertEqual(r.returncode, 0, (name, r.stderr))
            self.assertEqual(json.loads(r.stdout)["rules"][rule_id]["level"], "off")

    def test_repo_alias_overrides_preset_id(self):
        # The preset writes [rules.R1a]; the repo's [rules.file-bytes] must win, not conflict.
        root = helpers.make_repo({
            "AGENTS.md": "x\n" * 60,
            ".agentfile-lint.toml": '[[rules.file-bytes.limits]]\nglob = "AGENTS.md"\nmax_bytes = 100\n[rules.file-bytes]\nlevel = "off"\n',
        })
        r = helpers.run_new(root)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_alias_across_extends_is_not_a_conflict(self):
        r = config_json("extends = ['base.toml']\n[rules.file-bytes]\nlevel = 'off'\n",
                        ("base.toml", "[rules.R1a]\nlevel = 'warn'\n"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["rules"]["R1a"]["level"], "off")

    def test_id_and_alias_in_one_file_fail(self):
        r = config_json("[rules.R1a]\nlevel = 'warn'\n[rules.file-bytes]\nlevel = 'off'\n")
        self.assertEqual(r.returncode, 2)
        self.assertIn("R1a", r.stderr)
        self.assertIn("file-bytes", r.stderr)

    def test_allowlist_id_and_alias_for_same_path_fail(self):
        r = config_json(ENTRY.format(rule="R1a") + ENTRY.format(rule="file-bytes"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("duplicate entry for R1a AGENTS.md", r.stderr)

    def test_alias_before_id_names_both_keys(self):
        r = config_json("[rules.file-bytes]\nlevel = 'warn'\n[rules.R1a]\nlevel = 'off'\n")
        self.assertEqual(r.returncode, 2)
        self.assertIn("rules.file-bytes and rules.R1a", r.stderr)

    def test_non_string_allowlist_rule_is_a_config_error(self):
        r = config_json("[[allowlist.entries]]\nrule = ['file-bytes']\npath = 'AGENTS.md'\ncount = 1\nreason = 'r'\nexpires = 2026-07-01\n")
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)

    def test_unknown_key_hint_lists_aliases(self):
        r = config_json("[rules.file-byte]\nlevel = 'off'\n")
        self.assertEqual(r.returncode, 2)
        self.assertIn("file-bytes", r.stderr)

    def test_unknown_alias_still_fails(self):
        self.assertEqual(config_json("[rules.file-byte]\nlevel = 'off'\n").returncode, 2)
        self.assertEqual(config_json(ENTRY.format(rule="file-byte")).returncode, 2)

    def test_list_rules_prints_id_and_alias(self):
        root = helpers.make_repo({"AGENTS.md": "ok\n"})
        r = helpers.run_new(root, "--list-rules")
        self.assertEqual(r.returncode, 0)
        self.assertEqual([x.split()[0] for x in r.stdout.splitlines()][:len(RULES)], list(RULES))
        for rule_id in ("R1a", "R1b", "R1c", "R1d", "R4a", "R4b", "R5a", "R5b"):
            self.assertRegex(r.stdout, rf"(?m)^{rule_id}  \w+ +{re.escape(NAMES[rule_id])}: \S")
        for rule_id, name in NAMES.items():
            self.assertRegex(r.stdout, rf"(?m)^{rule_id}  \w+ +{re.escape(name)}:")

    def test_aliases_are_unique_and_distinct_from_ids(self):
        names = list(NAMES.values())
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse(set(names) & set(RULES))

    def test_rules_doc_lists_every_alias(self):
        doc = (helpers.REPO / "docs" / "rules.md").read_text(encoding="utf-8")
        for rule_id, name in NAMES.items():
            self.assertRegex(doc, rf"(?m)^\| \[{rule_id}\]\([^)]+\) \| `{re.escape(name)}` \|")


class RetiredIdTest(unittest.TestCase):
    """docs/adr/0005: the ids split in 0.7.0 fail wherever an id is accepted; never an alias for the group."""

    SPLIT = {"R1": ("R1a", "R1b", "R1c", "R1d"), "size": ("R1a", "R1b", "R1c", "R1d"),
             "R4": ("R4a", "R4b"), "rot": ("R4a", "R4b"), "R5": ("R5a", "R5b"), "duplicates": ("R5a", "R5b")}
    OVERRIDE = "[[overrides]]\npaths = ['AGENTS.md']\nrules = {{ {rule} = 'off' }}\nreason = 'r'\n"

    def test_every_retired_id_and_alias_fails_with_the_new_ids(self):
        self.assertEqual(set(RETIRED), set(self.SPLIT))
        for old, new in self.SPLIT.items():
            for toml, where in (
                (f"[rules.{old}]\nlevel = 'off'\n", f"rules.{old}"),
                (ENTRY.format(rule=old), "allowlist.entries[0].rule"),
                (self.OVERRIDE.format(rule=old), f"overrides[0].rules.{old}"),
            ):
                r = config_json(toml)
                self.assertEqual(r.returncode, 2, toml)
                self.assertIn(where, r.stderr)
                for rule_id in new:
                    self.assertIn(rule_id, r.stderr, toml)

    def test_a_retired_id_in_an_extended_file_fails_too(self):
        r = config_json("extends = ['base.toml']\n", ("base.toml", "[rules.R5]\nlevel = 'off'\n"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("base.toml: rules.R5", r.stderr)


if __name__ == "__main__":
    unittest.main()
