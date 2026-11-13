"""SKILL.md rules (S1 to S14), grouped by reader (docs/adr/0007, docs/rules.md "S1 to S14 SKILL.md")."""
import json
import unittest

from helpers import make_repo, run_new

CC = ""                                          # the default: the Claude Code ids only
BOTH = 'extends = ["preset:agentskills"]\n'       # adds the ids for claude.ai upload and the Skills API
GOOD = "---\nname: pdf\ndescription: Use when reading PDFs.\n---\n# PDF\n"


def lint(files: dict[str, str], config: str = "", extra: str = "", *args: str):
    """Findings as (path, line, rule) triples from a JSON run, plus the completed process."""
    files = dict(files)
    if config or extra:
        files[".agentfile-lint.toml"] = config + extra
    root = make_repo(files)
    r = run_new(root, "--format", "json", "--today", "2026-11-06", *args)
    if r.returncode == 2:
        raise AssertionError(r.stderr)
    doc = json.loads(r.stdout)
    return [(f["file"], f["line"], f["rule"]) for f in doc["findings"]], r, doc


def rules_of(files, config="", extra=""):
    return sorted({rule for _, _, rule in lint(files, config, extra)[0]})


class ValidSkillTest(unittest.TestCase):
    def test_spec_examples_report_nothing_for_either_reader(self):
        files = {
            "skills/skill-name/SKILL.md": "---\nname: skill-name\ndescription: A description of what this skill does and when to use it.\n---\n",
            "skills/pdf-processing/SKILL.md": (
                "---\nname: pdf-processing\ndescription: Extract PDF text, fill forms, merge files. Use when handling PDFs.\n"
                "license: Apache-2.0\nmetadata:\n  author: example-org\n  version: \"1.0\"\n---\n"
            ),
        }
        self.assertEqual(rules_of(files, BOTH), [])

    def test_flow_sequences_are_valid_yaml(self):
        # strictyaml (the reference validator) rejects flow style; YAML and Claude Code accept it.
        files = {"s/pdf/SKILL.md": "---\nname: pdf\ndescription: Use for PDFs.\nallowed-tools: [Read, Grep]\n---\n"}
        self.assertEqual(rules_of(files, BOTH), [])

    def test_no_r_rule_runs_on_skill_files_even_in_strict(self):
        text = GOOD + "We currently use the 2024-01-05 build, see #1234.\n" + "x\n" * 300
        extra = ('extends = ["preset:strict"]\n[[rules.R1b.limits]]\nglob = "**/SKILL.md"\nmax_lines = 10\n'
                 '[[rules.R1a.limits]]\nglob = "**/SKILL.md"\nmax_bytes = 10\n')
        self.assertEqual(rules_of({"s/pdf/SKILL.md": text}, extra=extra), [])

    def test_r_and_c_rules_do_not_run_on_skill_files(self):
        # 300 lines would be an R1b finding in an instruction file; SKILL.md is another file family.
        text = GOOD + "line\n" * 300
        self.assertEqual(rules_of({"s/pdf/SKILL.md": text}, BOTH), [])


class ClaudeCodeGroupTest(unittest.TestCase):
    def test_invalid_yaml_is_reported_at_the_error_line(self):
        found, _, doc = lint({"s/pdf/SKILL.md": "---\nname: pdf\ndescription: a: b\n---\n"})
        self.assertEqual(found, [("s/pdf/SKILL.md", 3, "S1")])
        self.assertIn("Claude Code loads the skill with no fields set", doc["findings"][0]["message"])

    def test_unterminated_and_non_mapping_frontmatter(self):
        self.assertEqual(rules_of({"s/a/SKILL.md": "---\nname: a\n"}), ["S1"])
        self.assertEqual(rules_of({"s/a/SKILL.md": "---\n- a\n- b\n---\n"}), ["S1"])

    def test_empty_frontmatter_is_no_fields_not_an_error(self):
        self.assertEqual(rules_of({"s/a/SKILL.md": "---\n---\n# A\n"}), [])

    def test_listing_text_limit_counts_description_and_when_to_use(self):
        at = "---\nname: a\ndescription: " + "d" * 1000 + "\nwhen_to_use: " + "w" * 536 + "\n---\n"
        over = "---\nname: a\ndescription: " + "d" * 1000 + "\nwhen_to_use: " + "w" * 537 + "\n---\n"
        self.assertEqual(rules_of({"s/a/SKILL.md": at}), [])
        found, _, doc = lint({"s/a/SKILL.md": over})
        self.assertEqual(found, [("s/a/SKILL.md", 3, "S3")])
        self.assertIn("1537", doc["findings"][0]["message"])

    def test_listing_limit_is_s3_max_chars(self):
        # Claude Code's `skillListingMaxDescChars` changes the limit; S3 follows with `max_chars`.
        over = "---\nname: a\ndescription: " + "d" * 1537 + "\n---\n"
        raised = '[rules.S3]\nlevel = "warn"\nmax_chars = 2000\n'
        self.assertEqual(rules_of({"s/a/SKILL.md": over}, extra=raised), [])
        found, _, doc = lint({"s/a/SKILL.md": over}, extra='[rules.S3]\nlevel = "warn"\nmax_chars = 100\n')
        self.assertEqual(found, [("s/a/SKILL.md", 3, "S3")])
        self.assertIn("at 100", doc["findings"][0]["message"])
        for bad in ("0", '"1536"', "true"):
            with self.subTest(max_chars=bad):
                r = run_new(make_repo({".agentfile-lint.toml": f'[rules.S3]\nlevel = "warn"\nmax_chars = {bad}\n'}))
                self.assertEqual(r.returncode, 2, r.stdout)
                self.assertIn("rules.S3.max_chars", r.stderr)

    def test_listing_limit_counts_characters_not_bytes(self):
        text = "---\nname: a\ndescription: " + "é" * 1536 + "\n---\n"
        self.assertEqual(rules_of({"s/a/SKILL.md": text}), [])

    def test_metadata_must_be_a_map(self):
        self.assertEqual(rules_of({"s/a/SKILL.md": "---\nname: a\nmetadata: [x, y]\n---\n"}), ["S4"])
        # Values of any type are not checked (D22b).
        self.assertEqual(rules_of({"s/a/SKILL.md": "---\nname: a\ndescription: d\nmetadata:\n  hermes:\n    tags: [a]\n---\n"}, BOTH), [])

    def test_file_of_500_lines_or_more(self):
        # "Keep SKILL.md under 500 lines": 499 is fine, 500 is not.
        head = "---\nname: a\ndescription: d\n---\n"
        under = head + "x\n" * (499 - 4)
        self.assertEqual(rules_of({"s/a/SKILL.md": under}), [])
        found, _, doc = lint({"s/a/SKILL.md": under + "x\n"})
        self.assertEqual(found, [("s/a/SKILL.md", None, "S2")])
        self.assertIn("500 lines; keep it under 500", doc["findings"][0]["message"])

    def test_yaml_1_1_types_are_not_applied(self):
        # PyYAML's YAML 1.1 resolution would fail on the date and turn `yes` into a boolean; the
        # readers see strings.
        text = "---\nname: a\ndescription: yes\nversion: 2026-02-30\n---\n"
        self.assertEqual(rules_of({"s/a/SKILL.md": text}, BOTH), ["S11"])

    def test_default_reports_no_agentskills_rule(self):
        files = {
            "SKILL.md": "# no frontmatter\n",
            "s/Bad--Name-/SKILL.md": "---\nname: Bad--Name-\nargument-hint: x\ncompatibility: ''\n---\n",
        }
        self.assertEqual(rules_of(files), [])


class RefusedNameCharactersTest(unittest.TestCase):
    """S12: characters Claude Code refuses in a skill's name or directory name."""

    def test_refused_characters_in_the_name(self):
        for name in ("a\u200bb", "a<b", "a>b", "a  b", " a", "a ", "a\u00a0b", "a\ue000b", "a\u202eb", "a\tb"):
            with self.subTest(name=repr(name)):
                text = "---\nname: " + json.dumps(name) + "\ndescription: d\n---\n"
                found, _, doc = lint({"s/a/SKILL.md": text})
                self.assertEqual(found, [("s/a/SKILL.md", 2, "S12")])
                self.assertIn("Claude Code refuses", doc["findings"][0]["message"])

    def test_more_refused_characters(self):
        for name in ("a\u0378b", "a\u2028b", "a b  "):   # unassigned, line separator, two trailing spaces
            with self.subTest(name=repr(name)):
                text = "---\nname: " + json.dumps(name) + "\ndescription: d\n---\n"
                self.assertEqual(rules_of({"s/a/SKILL.md": text}), ["S12"])

    def test_a_block_scalar_name_ends_in_yaml_syntax_not_a_character(self):
        self.assertEqual(rules_of({"s/foo/SKILL.md": "---\nname: |\n  foo\ndescription: d\n---\n"}, BOTH), [])

    def test_the_line_is_the_parsed_key_not_a_look_alike_in_a_string(self):
        text = '---\ndescription: "first\nname: x"\nname: "a<b"\n---\n'
        self.assertEqual(lint({"s/a/SKILL.md": text})[0], [("s/a/SKILL.md", 4, "S12")])

    def test_refused_directory_without_frontmatter(self):
        self.assertEqual(rules_of({"s/bad\u00a0dir/SKILL.md": "# no frontmatter\n"}), ["S12"])

    def test_accepted_names(self):
        for name in ("my skill", "pdf-tools", "données", "n8n:deploy", "Deploy_Staging"):
            with self.subTest(name=name):
                self.assertEqual(rules_of({"s/a/SKILL.md": "---\nname: " + json.dumps(name) + "\ndescription: d\n---\n"}), [])

    def test_refused_characters_in_the_directory_name(self):
        found, _, doc = lint({"s/bad\u00a0dir/SKILL.md": "---\ndescription: d\n---\n"})
        self.assertEqual(found, [("s/bad\u00a0dir/SKILL.md", None, "S12")])
        self.assertIn("directory", doc["findings"][0]["message"])

    def test_preset_agentskills_keeps_the_claude_code_ids(self):
        self.assertIn("S12", rules_of({"s/a/SKILL.md": '---\nname: "a<b"\ndescription: d\n---\n'}, BOTH))


class AgentSkillsGroupTest(unittest.TestCase):
    def test_missing_frontmatter(self):
        found, _, _ = lint({"s/a/SKILL.md": "# A\n"}, BOTH)
        self.assertEqual(found, [("s/a/SKILL.md", None, "S5")])

    def test_name_length(self):
        n64, n65 = "a" * 64, "a" * 65
        self.assertEqual(rules_of({f"s/{n64}/SKILL.md": f"---\nname: {n64}\ndescription: d\n---\n"}, BOTH), [])
        self.assertEqual(rules_of({f"s/{n65}/SKILL.md": f"---\nname: {n65}\ndescription: d\n---\n"}, BOTH), ["S6"])
        self.assertEqual(rules_of({"s/a/SKILL.md": "---\ndescription: d\n---\n"}, BOTH), ["S6"])
        self.assertEqual(rules_of({"s/a/SKILL.md": "---\nname: ''\ndescription: d\n---\n"}, BOTH), ["S6"])
        self.assertEqual(rules_of({"s/a/SKILL.md": "---\nname: [a]\ndescription: d\n---\n"}, BOTH), ["S6"])
        # Scalars are their text: `12` is the name "12", as strictyaml reads it.
        self.assertEqual(rules_of({"s/12/SKILL.md": "---\nname: 12\ndescription: d\n---\n"}, BOTH), [])

    def test_name_characters(self):
        for name in ("bad--name", "-bad", "bad-", "Bad", "bad_name", "n8n:bad"):
            with self.subTest(name=name):
                files = {f"s/{name}/SKILL.md": f"---\nname: '{name}'\ndescription: d\n---\n"}
                self.assertEqual(rules_of(files, BOTH), ["S7"])
        # The reference validator takes Unicode lowercase letters after NFKC.
        self.assertEqual(rules_of({"s/données/SKILL.md": "---\nname: données\ndescription: d\n---\n"}, BOTH), [])

    def test_root_skill_md_has_no_directory_to_compare(self):
        self.assertEqual(rules_of({"SKILL.md": "---\nname: sk\ndescription: d\n---\n"}, BOTH), [])

    def test_name_must_equal_the_directory(self):
        found, _, doc = lint({"s/pdf-tools/SKILL.md": "---\nname: pdf\ndescription: d\n---\n"}, BOTH)
        self.assertEqual(found, [("s/pdf-tools/SKILL.md", 2, "S8")])
        self.assertIn("pdf-tools", doc["findings"][0]["message"])
        # Claude Code takes a name that differs from its directory.
        self.assertEqual(rules_of({"s/pdf-tools/SKILL.md": "---\nname: pdf\ndescription: d\n---\n"}, CC), [])

    def test_description_length(self):
        ok = "---\nname: a\ndescription: " + "d" * 1024 + "\n---\n"
        over = "---\nname: a\ndescription: " + "d" * 1025 + "\n---\n"
        self.assertEqual(rules_of({"s/a/SKILL.md": ok}, BOTH), [])
        self.assertEqual(rules_of({"s/a/SKILL.md": over}, BOTH), ["S9"])
        self.assertEqual(rules_of({"s/a/SKILL.md": "---\nname: a\n---\n"}, BOTH), ["S9"])
        self.assertEqual(rules_of({"s/a/SKILL.md": "---\nname: a\ndescription: '  '\n---\n"}, BOTH), ["S9"])

    def test_compatibility(self):
        head = "---\nname: a\ndescription: d\ncompatibility: "
        self.assertEqual(rules_of({"s/a/SKILL.md": head + "x" * 500 + "\n---\n"}, BOTH), [])
        self.assertEqual(rules_of({"s/a/SKILL.md": head + "x" * 501 + "\n---\n"}, BOTH), ["S10"])
        self.assertEqual(rules_of({"s/a/SKILL.md": head + "''\n---\n"}, BOTH), ["S10"])
        self.assertEqual(rules_of({"s/a/SKILL.md": head + "\n  requires: [x]\n---\n"}, BOTH), ["S10"])

    def test_keys_outside_the_six_of_the_spec(self):
        text = "---\nname: a\ndescription: d\nargument-hint: x\nversion: 1\n---\n"
        found, _, doc = lint({"s/a/SKILL.md": text}, BOTH)
        self.assertEqual(found, [("s/a/SKILL.md", 4, "S11")])
        self.assertIn("argument-hint, version", doc["findings"][0]["message"])

    def test_duplicate_and_non_string_keys_are_s1(self):
        found, _, doc = lint({"s/a/SKILL.md": "---\nname: a\nname: b\n---\n"})
        self.assertEqual(found, [("s/a/SKILL.md", 3, "S1")])
        self.assertIn("Claude Code loads the skill with no fields set", doc["findings"][0]["message"])
        found, _, doc = lint({"s/a/SKILL.md": "---\n[a, b]: 1\n---\n"})
        self.assertEqual(found, [("s/a/SKILL.md", 2, "S1")])
        self.assertIn("YAML readers differ on such a key", doc["findings"][0]["message"])
        self.assertNotIn("Claude Code loads", doc["findings"][0]["message"])

    def test_invalid_yaml_is_reported_for_agentskills_alone_too(self):
        self.assertEqual(rules_of({"s/a/SKILL.md": "---\nname: a\ndescription: a: b\n---\n"}, BOTH), ["S1"])


class DiscoveryAndConfigTest(unittest.TestCase):
    def test_skill_globs_replace_and_extend(self):
        files = {"a/x/SKILL.md": "---\n- a\n---\n", "b/y/SKILL.md": "---\n- a\n---\n"}
        self.assertEqual({p for p, _, _ in lint(files, extra='[discover]\nskill_globs = ["a/**/SKILL.md"]\n')[0]},
                         {"a/x/SKILL.md"})
        extend = '[discover]\nskill_globs = ["a/**/SKILL.md"]\nextend_skill_globs = ["b/**/SKILL.md"]\n'
        self.assertEqual({p for p, _, _ in lint(files, extra=extend)[0]}, {"a/x/SKILL.md", "b/y/SKILL.md"})

    def test_a_file_both_glob_lists_match_gets_both_families(self):
        # Each family's rules see only its own files; listing SKILL.md in `globs` too adds the R rules.
        files = {"s/a/SKILL.md": "---\n- x\n---\n" + "x\n" * 300}
        both = '[discover]\nextend_globs = ["**/SKILL.md"]\n[[rules.R1b.limits]]\nglob = "**/SKILL.md"\nmax_lines = 200\n'
        self.assertEqual({rule for _, _, rule in lint(files, extra=both)[0]}, {"R1b", "S1"})
        only_limit = '[[rules.R1b.limits]]\nglob = "**/SKILL.md"\nmax_lines = 200\n'
        self.assertEqual({rule for _, _, rule in lint(files, extra=only_limit)[0]}, {"S1"})

    def test_skills_table_is_not_a_config_key(self):
        # Readers are chosen with presets and levels (docs/adr/0007), not a `[skills]` table.
        r = run_new(make_repo({"s/a/SKILL.md": GOOD, ".agentfile-lint.toml": '[skills]\ntargets = ["agentskills"]\n'}))
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("config: unknown key(s) skills", r.stderr)

    def test_empty_skill_globs_turn_the_family_off(self):
        files = {"s/a/SKILL.md": "---\n- x\n---\n"}
        self.assertEqual(rules_of(files, extra="[discover]\nskill_globs = []\n"), [])

    def test_a_level_alone_turns_an_agentskills_id_on(self):
        text = "---\nname: a\ndescription: d\nversion: 1\n---\n"
        self.assertEqual(rules_of({"s/a/SKILL.md": text}), [])
        self.assertEqual(rules_of({"s/a/SKILL.md": text}, extra='[rules.S11]\nlevel = "warn"\n'), ["S11"])
        # and a preset id can be turned off again
        self.assertEqual(rules_of({"s/a/SKILL.md": text}, BOTH, '[rules.S11]\nlevel = "off"\n'), [])

    def test_an_override_can_raise_an_agentskills_id(self):
        extra = '[[overrides]]\npaths = ["s/**"]\nrules = { S11 = "warn" }\nraise = true\nreason = "uploaded"\n'
        text = "---\nname: a\ndescription: d\nversion: 1\n---\n"
        self.assertEqual(lint({"s/a/SKILL.md": text}, "", extra)[0], [("s/a/SKILL.md", 4, "S11")])

    def test_preset_agentskills_combines_with_strict(self):
        text = "---\nname: a\ndescription: d\nversion: 1\n---\n"
        both = 'extends = ["preset:strict", "preset:agentskills"]\n'
        self.assertEqual(rules_of({"s/a/SKILL.md": text}, both), ["S11"])
        root = make_repo({".agentfile-lint.toml": both})
        doc = json.loads(run_new(root, "config", "--format", "json").stdout)
        self.assertEqual(doc["rules"]["S11"]["level"], "warn")
        self.assertEqual(doc["rules"]["R4b"]["level"], "warn")   # from preset:strict

    def test_a_skill_file_named_on_the_command_line_triggers_the_run(self):
        # argv names decide whether to run at all; a SKILL.md name is relevant (0.9.0 fix, step 3).
        root = make_repo({"AGENTS.md": "ok\n", "s/a/SKILL.md": "---\n- x\n---\n"})
        r = run_new(root, "--format", "json", "s/a/SKILL.md")
        self.assertEqual([f["rule"] for f in json.loads(r.stdout)["findings"]], ["S1"])

    def test_effective_config_shows_the_skill_ids(self):
        root = make_repo({})
        r = run_new(root, "config", "--format", "json")
        doc = json.loads(r.stdout)
        self.assertNotIn("skills", doc)
        self.assertEqual(doc["rules"]["S3"], {"level": "warn", "max_chars": 1536})
        self.assertEqual([doc["rules"][f"S{i}"]["level"] for i in range(5, 12)], ["off"] * 7)
        self.assertEqual(doc["discover"]["skill_globs"], ["**/SKILL.md"])
        self.assertEqual(doc["discover"]["extend_skill_globs"], [])

    def test_non_utf8_skill_file_is_e0(self):
        root = make_repo({"s/a/SKILL.md": b"---\nname: \xff\n---\n"})
        r = run_new(root, "--format", "json", "--today", "2026-11-06")
        self.assertEqual([(f["file"], f["rule"]) for f in json.loads(r.stdout)["findings"]], [("s/a/SKILL.md", "E0")])

    def test_directive_naming_an_s_rule_is_rejected(self):
        files = {"AGENTS.md": "# A\n<!-- agentfile-lint-disable-next-line S7 -- no -->\ntext\n"}
        found, _, doc = lint(files)
        self.assertEqual([f["rule"] for f in doc["findings"]], ["disable"])
        self.assertIn("SKILL.md", doc["findings"][0]["message"])

    def test_allowlist_entry_for_a_skill_file(self):
        extra = (
            '[[allowlist.entries]]\nrule = "S4"\npath = "s/a/SKILL.md"\ncount = 1\n'
            'reason = "client metadata"\nexpires = 2026-12-01\n'
        )
        found, _, _ = lint({"s/a/SKILL.md": "---\nmetadata: [x]\n---\n"}, "", extra)
        self.assertEqual(found, [])

    def test_two_names_for_one_skill_file_in_a_directory_are_analyzed_once(self):
        root = make_repo({
            "s/a/SKILL.md": "---\n- x\n---\n",
            ".agentfile-lint.toml": '[discover]\nextend_skill_globs = ["**/LINK.md"]\n',
        }, symlinks={"s/a/LINK.md": "SKILL.md"})
        r = run_new(root, "--format", "json", "--today", "2026-11-06")
        self.assertEqual([f["file"] for f in json.loads(r.stdout)["findings"]], ["s/a/SKILL.md"])

    def test_symlinked_skill_file_is_analyzed_once_per_location(self):
        root = make_repo({"s/a/SKILL.md": "---\n- x\n---\n"}, symlinks={"t/a/SKILL.md": "../../s/a/SKILL.md"})
        r = run_new(root, "--format", "json", "--today", "2026-11-06")
        self.assertEqual(sorted(f["file"] for f in json.loads(r.stdout)["findings"]), ["s/a/SKILL.md", "t/a/SKILL.md"])


class LinksTest(unittest.TestCase):
    """S14: a relative Markdown link in the body points to a tracked file or directory."""

    SKILL = "skills/pdf/SKILL.md"

    def found(self, body: str, **files: str):
        files = {self.SKILL: GOOD + body, "skills/pdf/references/forms.md": "x\n", "skills/merge/SKILL.md":
                 GOOD.replace("pdf", "merge"), "docs/My Guide.md": "x\n", **files}
        return [(f, line) for f, line, rule in lint(files)[0] if rule == "S14"]

    def test_links_to_tracked_files_and_directories_are_fine(self):
        body = ("See [forms](references/forms.md), [the folder](references/), [merge](../merge/SKILL.md#usage),\n"
                "[guide](../../docs/My%20Guide.md), [same](./references/forms.md?plain=1) and [here](.).\n")
        self.assertEqual(self.found(body), [])

    def test_missing_target_is_reported_on_its_line(self):
        found, r, doc = lint({self.SKILL: GOOD + "\nRead [the rules](../../rules/react.md) and [a](references/gone.md).\n"})
        self.assertEqual((found, r.returncode), ([(self.SKILL, 7, "S14")] * 2, 0))
        self.assertIn("looked for rules/react.md", doc["findings"][0]["message"])

    def test_missing_directory_and_wrong_case_are_reported(self):
        self.assertEqual(self.found("[d](../absent/)\n[c](References/forms.md)\n"), [(self.SKILL, 6), (self.SKILL, 7)])

    def test_file_named_as_a_directory_is_reported(self):
        self.assertEqual(self.found("[d](references/forms.md/)\n"), [(self.SKILL, 6)])

    def test_target_with_parentheses(self):
        files = {"skills/pdf/references/api(v2).md": "x\n"}
        self.assertEqual(self.found("[a](references/api(v2).md)\n[b](references/gone(v2).md)\n", **files), [(self.SKILL, 7)])

    def test_below_a_tracked_symlink_or_a_skipped_directory_is_not_judged(self):
        root = make_repo({self.SKILL: GOOD + "[a](shared/forms.md)\n[b](node_modules/x/README.md)\n[c](gone/x.md)\n[d](shared/)\n",
                          "lib/forms.md": "x\n"}, symlinks={"skills/pdf/shared": "../../lib"})
        doc = json.loads(run_new(root, "--format", "json").stdout)
        self.assertEqual([(f["line"], f["rule"]) for f in doc["findings"]], [(8, "S14")])

    def test_untracked_file_is_reported(self):
        root = make_repo({self.SKILL: GOOD + "[notes](notes.md)\n"})
        (root / "skills/pdf/notes.md").write_text("x\n")
        self.assertIn("S14", run_new(root).stdout)

    def test_what_is_not_a_repository_path_is_skipped(self):
        body = ("[a](https://example.com/x.md) [b](mailto:a@example.com) [c](#usage) [d](/docs/x.md)\n"
                "[e](url) [f]({baseDir}/x.md) [g](<path>/x.md) [h]($HOME/x.md) [i](../../../outside/x.md)\n"
                "![image](missing.png) [![badge](missing.png)](https://example.com) \\[esc](gone.md)\n"
                "[t]`c`(gone.md)\n")
        self.assertEqual(self.found(body), [])

    def test_code_and_frontmatter_are_not_read(self):
        text = ("---\nname: pdf\ndescription: See [x](gone.md).\n---\n"
                "Write `[text](gone.md)` like this:\n\n```md\n[text](gone.md)\n```\n<!-- [old](gone.md) -->\n")
        self.assertEqual([r for _, _, r in lint({self.SKILL: text})[0]], [])

    def test_fence_or_comment_opened_in_the_frontmatter_does_not_hide_the_body(self):
        for opener in ("```", "use <!-- when"):
            with self.subTest(opener=opener):
                text = f"---\nname: pdf\ndescription: |\n  {opener}\n---\n[x](gone.md)\n"
                self.assertEqual(lint({self.SKILL: text})[0], [(self.SKILL, 6, "S14")])

    def test_link_with_a_title_and_two_links_on_a_line(self):
        self.assertEqual(self.found('[a](gone.md "Title") and [b](references/forms.md) and [c](also/gone.md)\n'),
                         [(self.SKILL, 6)] * 2)

    def test_instruction_files_are_not_checked(self):
        self.assertEqual(lint({"AGENTS.md": "See [x](gone.md).\n"})[0], [])

    def test_level_and_alias(self):
        files = {self.SKILL: GOOD + "[a](gone.md)\n"}
        self.assertEqual(rules_of(files, '[rules.skill-links]\nlevel = "off"\n'), [])
        self.assertEqual(lint(files, '[rules.S14]\nlevel = "error"\n')[1].returncode, 1)


class CompactionTest(unittest.TestCase):
    """S13: Claude Code keeps the first `max_tokens` tokens of an invoked skill after compaction."""

    STRICT = 'extends = ["preset:strict"]\n'

    def skill(self, body: str) -> dict[str, str]:
        return {"s/pdf/SKILL.md": GOOD + body}

    def test_off_by_default_and_a_warning_in_strict(self):
        files = self.skill("word " * 5000)                       # 25,000 ASCII characters: about 6,250 tokens
        self.assertEqual(rules_of(files), [])
        found, r, doc = lint(files, self.STRICT)
        self.assertEqual((found, r.returncode), ([("s/pdf/SKILL.md", None, "S13")], 0))
        self.assertIn("about 6252 tokens", doc["findings"][0]["message"])
        self.assertIn("first 5000 tokens", doc["findings"][0]["message"])

    def test_estimate_counts_four_ascii_or_one_other_character_per_token(self):
        from agentfile_lint.rules.skill import estimated_tokens
        self.assertEqual([estimated_tokens(s) for s in ("", "a", "abcd", "abcde", "\u6587\u5b57", "ab\u6587")], [0, 1, 1, 2, 2, 2])

    def test_limit_is_on_the_body_without_the_frontmatter(self):
        config = self.STRICT + "[rules.S13]\nmax_tokens = 10\n"
        long_description = "---\nname: pdf\ndescription: " + "d" * 400 + "\n---\n"
        self.assertEqual(rules_of({"s/pdf/SKILL.md": long_description + "x" * 40 + "\n"}, config), [])
        self.assertEqual(rules_of({"s/pdf/SKILL.md": long_description + "x" * 41 + "\n"}, config), ["S13"])
        self.assertEqual(rules_of({"s/pdf/SKILL.md": "\u6587" * 10}, config), [])
        self.assertEqual(rules_of({"s/pdf/SKILL.md": "\u6587" * 11}, config), ["S13"])

    def test_max_tokens_must_be_a_positive_integer(self):
        root = make_repo({"s/pdf/SKILL.md": GOOD, ".agentfile-lint.toml": "[rules.S13]\nmax_tokens = 0\n"})
        r = run_new(root)
        self.assertEqual(r.returncode, 2)
        self.assertIn("rules.S13.max_tokens", r.stderr)


if __name__ == "__main__":
    unittest.main()
