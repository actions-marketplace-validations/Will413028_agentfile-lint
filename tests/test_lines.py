"""One line definition for every rule: only LF, CRLF and a lone CR end a line, as `grep -n` and
editors count them; form feed and U+2028 do not. R1b's count and every reported line number use it.
`config --format json` prints Config.rules, the one source of each id's effective table."""
import json
import unittest
from unittest import mock

import helpers

from agentfile_lint import config as config_mod
from agentfile_lint.rules import _text, rot

CFG = ".agentfile-lint.toml"
# Lines by LF / CRLF / CR: 1 "a\x0cb c", 2 "d", 3 "the long line ... ZZWORD", 4 "e"
# (str.splitlines would see 7 lines: it also breaks at \x0c and U+2028).
TEXT = "a\x0cb c\rd\r\n" + "x" * 30 + " ZZWORD\ne\n"
TOML = (
    '[rules.R1b]\nlevel = "error"\n[[rules.R1b.limits]]\nglob = "AGENTS.md"\nmax_lines = 1\n'
    '[rules.R1d]\nlevel = "error"\nmax_chars = 20\n'
    '[rules.R4b]\nlevel = "error"\nnarrative_words = ["ZZWORD"]\n'
)
SNAPSHOTS = helpers.FIXTURES / "config-json-0.7.0"


class LineDefinitionTest(unittest.TestCase):
    def test_split_lines(self):
        self.assertEqual(_text.split_lines("a\x0cb c\rd\r\ne\n"), ["a\x0cb c", "d", "e"])
        self.assertEqual(_text.split_lines("a\n\nb"), ["a", "", "b"])
        self.assertEqual(_text.split_lines(""), [])

    def test_count_and_line_numbers_by_lf_crlf_cr(self):
        r = helpers.run_new(helpers.make_repo({"AGENTS.md": TEXT.encode("utf-8"), CFG: TOML}))
        self.assertIn("AGENTS.md: error: R1b: file is 4 lines, limit 1", r.stdout)
        self.assertIn("AGENTS.md:3: error: R1d: line is 37 characters, limit 20", r.stdout)
        self.assertRegex(r.stdout, r"(?m)^AGENTS\.md:3: error: R4b: ")


class BlockJoinTest(unittest.TestCase):
    def test_lone_cr_before_a_block_and_lf_after_it_stay_two_lines(self):
        toml = (
            '[shared.size]\nexcluded_blocks = [{ begin = "<B>", end = "<E>" }]\n'
            '[rules.R1b]\nlevel = "error"\n[[rules.R1b.limits]]\nglob = "AGENTS.md"\nmax_lines = 1\n'
        )
        # Outside the block: "a", an empty line, "b" (the block eats one trailing LF).
        r = helpers.run_new(helpers.make_repo({"AGENTS.md": b"a\r<B>x<E>\n\nb", CFG: toml}))
        self.assertIn("AGENTS.md: error: R1b: file is 3 lines, limit 1", r.stdout)


class ConfigJsonTest(unittest.TestCase):
    def test_matches_the_0_7_0_snapshot(self):
        root = helpers.make_repo({})
        for preset in ("default", "strict"):
            with self.subTest(preset=preset):
                (root / "p.toml").write_text(f'extends = "preset:{preset}"\n')
                r = helpers.run_new(root, "config", "--format", "json", "--config", "p.toml")
                self.assertEqual(r.returncode, 0, r.stderr)
                # 0.8.0 and 0.9.0 add keys: with them removed (and the globs below restored), the output is the 0.7.0 snapshot verbatim.
                doc = json.loads(r.stdout)
                self.assertEqual(doc["discover"].pop("extend_globs"), [])
                self.assertEqual(doc["shared"]["duplicates"].pop("exclude"), [])
                self.assertEqual(doc["discover"].pop("skill_globs"), ["**/SKILL.md"])        # 0.9.0
                self.assertEqual(doc["discover"].pop("extend_skill_globs"), [])
                self.assertNotIn("skills", doc)
                self.assertEqual(doc["rules"].pop("S3"), {"level": "warn", "max_chars": 1536})
                self.assertEqual([doc["rules"].pop(f"S{i}")["level"] for i in (1, 2, 4, 12)], ["warn"] * 4)
                self.assertEqual([doc["rules"].pop(f"S{i}") for i in range(5, 12)], [{"level": "off"}] * 7)
                self.assertEqual(doc["discover"].pop("hooks_globs"), ["**/.claude/settings.json", "**/.claude/settings.local.json"])
                self.assertEqual(doc["discover"].pop("extend_hooks_globs"), [])
                self.assertEqual(doc["discover"].pop("mcp_globs"), [".mcp.json"])
                self.assertEqual(doc["discover"].pop("extend_mcp_globs"), [])
                self.assertEqual([doc["rules"].pop(f"H{i}") for i in range(1, 7)], [{"level": "warn"}] * 6)
                self.assertEqual([doc["rules"].pop(f"M{i}") for i in range(1, 5)], [{"level": "warn"}] * 4)
                self.assertEqual(doc["rules"].pop("R1e")["level"], "warn")
                # 0.9.0 also changes one value (Changed (breaking)): two more default globs.
                globs = doc["discover"]["globs"]
                self.assertEqual(globs[4:], ["**/CLAUDE.local.md", "**/.claude/rules/**/*.md"])
                del globs[4:]
                self.assertEqual(json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False) + "\n", (SNAPSHOTS / f"{preset}.json").read_text())

    def test_prints_the_effective_table_of_a_multi_id_module(self):
        # A defaulted key a module fills in shows up, though no config file writes it.
        real = rot.validate

        def with_default(shared, tables):
            params, effective = real(shared, tables)
            return params, {**effective, "R4a": {**effective["R4a"], "fake_default": 3}}

        with mock.patch.object(rot, "validate", with_default):
            cfg = config_mod.load(None, config_mod.datetime.date(2026, 1, 1))
        self.assertEqual(cfg.rules["R4a"]["fake_default"], 3)
        self.assertEqual(config_mod.to_jsonable(cfg)["rules"]["R4a"]["fake_default"], 3)


if __name__ == "__main__":
    unittest.main()
