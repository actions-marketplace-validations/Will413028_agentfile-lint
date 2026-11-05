"""Rules R2 to R6 and C1: at least one passing and one violating fixture each (mutation-checked)."""
import unittest

import helpers


def lint(files, config="", *args):
    """Run the tool in a temp git repo; returns (exit code, warning lines, error lines). The error
    lines end with stderr (usage and config problems); findings come only from stdout."""
    files = dict(files)
    if config:
        files[".agentfile-lint.toml"] = config
    r = helpers.run_new(helpers.make_repo(files), "--today", "2026-06-01", *args)
    warnings, errors = helpers.by_severity(r)
    return r.returncode, warnings, errors + r.stderr.splitlines()


def only(rule, lines):
    return [line for line in lines if f": {rule}: " in line]


class ShapeTest(unittest.TestCase):  # R2
    CFG = """
[rules.R2]
level = "error"
[[rules.R2.shapes]]
glob = "mod/*/AGENTS.md"
sections = ["Purpose", "Data", "Invariants"]
title = true
purpose = true
bullets_only = ["Invariants"]
must_match = ['docs/spec']
"""
    GOOD = "# mod\n\nWhat it does.\n\n## Purpose\n\nx\n\n## Data\n\ny\nSee docs/spec/a.md\n\n## Invariants\n\n- one\n  continued\n- two\n"

    def run_one(self, text, cfg=None):
        return lint({"mod/a/AGENTS.md": text}, cfg or self.CFG)

    def test_passes_on_the_fixed_shape(self):
        rc, out, err = self.run_one(self.GOOD)
        self.assertEqual((rc, only("R2", out + err)), (0, []))

    def test_other_paths_are_not_checked(self):
        rc, out, err = lint({"AGENTS.md": "no sections at all\n"}, self.CFG)
        self.assertEqual((rc, only("R2", out + err)), (0, []))

    def test_missing_section(self):
        rc, _, err = self.run_one(self.GOOD.replace("## Data\n\ny\n", ""))
        self.assertEqual(rc, 1)
        self.assertIn('mod/a/AGENTS.md: error: R2: missing section "Data"', err)

    def test_unexpected_section(self):
        rc, _, err = self.run_one(self.GOOD.replace("## Data", "## Data\n\ny\n\n## Extra"))
        self.assertEqual(rc, 1)
        self.assertTrue(any('unexpected section "Extra"' in line for line in err), err)

    def test_out_of_order(self):
        text = "# mod\n\nWhat.\n\n## Data\n\ny\n\n## Purpose\n\nx\n\n## Invariants\n\n- a\n\ndocs/spec\n"
        rc, _, err = self.run_one(text)
        self.assertEqual(rc, 1)
        self.assertTrue(any("sections out of order" in line for line in err), err)

    def test_duplicate_section(self):
        rc, _, err = self.run_one(self.GOOD + "\n## Data\n\nagain\n")
        self.assertEqual(rc, 1)
        self.assertTrue(any('duplicate section "Data"' in line for line in err), err)

    def test_headings_in_code_fences_and_comments_do_not_count(self):
        text = self.GOOD + "\n```\n## Fake\n```\n<!--\n## Hidden\n-->\n"
        rc, out, err = self.run_one(text)
        self.assertEqual((rc, only("R2", out + err)), (0, []))

    def test_title_purpose_bullets_and_must_match(self):
        rc, _, err = self.run_one(self.GOOD.replace("# mod\n\nWhat it does.\n\n", "What it does.\n\n"))
        self.assertTrue(any("level-1 title" in line for line in err), err)
        rc, _, err = self.run_one(self.GOOD.replace("What it does.\n", "- a list\n"))
        self.assertTrue(any("one-line purpose" in line for line in err), err)
        rc, _, err = self.run_one(self.GOOD.replace("What it does.\n", "What it does.\nsecond line\n"))
        self.assertTrue(any("single line" in line for line in err), err)
        rc, _, err = self.run_one(self.GOOD.replace("- two\n", "- two\nprose here\n"))
        self.assertTrue(any("only contain bullet items" in line for line in err), err)
        rc, _, err = self.run_one(self.GOOD.replace("docs/spec", "elsewhere"))
        self.assertTrue(any("required pattern" in line for line in err), err)

    def test_ordered_mode_allows_extra_sections(self):
        cfg = self.CFG.replace('title = true', 'mode = "ordered"\ntitle = true')
        rc, out, err = self.run_one(self.GOOD.replace("## Data", "## Extra\n\nz\n\n## Data"), cfg)
        self.assertEqual((rc, only("R2", out + err)), (0, []))

    def test_invalid_shape_config_fails(self):
        rc, _, err = lint({"AGENTS.md": "x\n"}, '[[rules.R2.shapes]]\nglob = "a"\n')
        self.assertEqual(rc, 2)
        self.assertTrue(any("missing key sections" in line for line in err), err)


class TestNamesTest(unittest.TestCase):  # R3a
    CFG = '[rules.R3a]\nlevel = "error"\n'
    FILES = {
        "pkg/a_test.go": "package pkg\n\nfunc TestAlpha(t *testing.T) {}\nfunc (s *Suite) TestBeta(t *testing.T) {}\n",
        "tests/test_x.py": "def test_gamma():\n    pass\n",
    }

    def test_defined_names_pass(self):
        files = dict(self.FILES, **{"AGENTS.md": "Guards: `TestAlpha`, `TestBeta()`, `test_gamma`.\n"})
        rc, out, err = lint(files, self.CFG)
        self.assertEqual((rc, only("R3a", out + err)), (0, []))

    def test_missing_go_and_python_names_fail(self):
        files = dict(self.FILES, **{"AGENTS.md": "ok\nGuard: `TestMissing`.\nAlso `test_nope`.\n"})
        rc, _, err = lint(files, self.CFG)
        self.assertEqual(rc, 1)
        self.assertIn("AGENTS.md:2: error: R3a: test `TestMissing` is not defined in any searched test file", err)
        self.assertIn("AGENTS.md:3: error: R3a: test `test_nope` is not defined in any searched test file", err)

    def test_other_words_in_backticks_and_code_fences_are_ignored(self):
        text = "Use `Testing` and `TestFoo/sub`.\n```\n`TestFenced`\n```\n"
        rc, out, err = lint(dict(self.FILES, **{"AGENTS.md": text}), self.CFG)
        self.assertEqual((rc, only("R3a", out + err)), (0, []))

    def test_language_without_test_files_is_skipped(self):
        rc, out, err = lint({"AGENTS.md": "`TestAnything` `test_anything`\n"}, self.CFG)
        self.assertEqual((rc, only("R3a", out + err)), (0, []))


class PathRefsTest(unittest.TestCase):  # R3b
    CFG = """
[rules.R3b]
level = "error"
base_dirs = ["backend", "packages/*"]
source_roots = ["src"]
resolve_extensions = [".ts"]
ignore_negated_words = ["no longer"]
"""
    FILES = {
        "docs/guide.md": "x\n",
        "sub/lib/util.go": "x\n",
        "backend/db/schema.sql": "x\n",
        "packages/ui/src/components/Button.ts": "x\n",
    }

    def run_one(self, text, cfg=None):
        return lint(dict(self.FILES, **{"sub/AGENTS.md": text}), cfg or self.CFG)

    def test_resolves_from_dir_ancestors_root_bases_source_roots_and_extensions(self):
        text = "`lib/util.go` `docs/guide.md` `db/schema.sql` `components/Button` `docs/` `./lib/util.go:12`\n"
        rc, out, err = self.run_one(text)
        self.assertEqual((rc, only("R3b", out + err)), (0, []))

    def test_missing_path_fails(self):
        rc, _, err = self.run_one("see `lib/gone.go` here\n")
        self.assertEqual(rc, 1)
        self.assertTrue(any(line.startswith("sub/AGENTS.md:1: error: R3b: path `lib/gone.go` not found") for line in err), err)

    def test_skips_non_paths_urls_placeholders_and_ignored_lines(self):
        text = ("`https://x.example/a/b` `src/<name>/x.go` `a/*.go` `cmd --flag/x` `node_modules/p/x.js` `.env.local`\n"
                "`lib/gone.go` is no longer here\n```\n`lib/fenced.go`\n```\n")
        rc, out, err = self.run_one(text)
        self.assertEqual((rc, only("R3b", out + err)), (0, []))

    def test_bare_file_names_are_not_checked_by_default(self):
        rc, out, err = self.run_one("`schema.gone.sql`\n")
        self.assertEqual((rc, only("R3b", out + err)), (0, []))
        rc, _, err = self.run_one("`schema.gone.sql`\n", self.CFG + "check_bare_names = true\n")
        self.assertEqual(rc, 1)

    def test_off_by_default_and_warn_in_strict(self):
        rc, out, err = lint({"AGENTS.md": "`gone/file.go`\n"})
        self.assertEqual((rc, only("R3b", out + err)), (0, []))
        rc, out, err = lint({"AGENTS.md": "`gone/file.go`\n"}, 'extends = ["preset:strict"]\n')
        self.assertEqual(rc, 0)
        self.assertEqual(len(only("R3b", out)), 1)


class SpecRefsTest(unittest.TestCase):  # R3c
    CFG = """
[rules.R3c]
level = "error"
[[rules.R3c.specs]]
glob = "mod/*/AGENTS.md"
spec = "docs/{1}.md"
"""
    SPEC = "# Spec\n\n## 1. Scope\n\n## 2. Lifecycle\n\n### 2.1 Creation\n\n## 3. Limits\n"

    def run_one(self, text, spec=SPEC):
        files = {"mod/a/AGENTS.md": text, "mod/b/AGENTS.md": "ok\n"}
        if spec is not None:
            files["docs/a.md"] = spec
        return lint(files, self.CFG)

    def test_existing_sections_pass(self):
        rc, out, err = self.run_one("Rules: §1, §2.1 and §2 (spec §3).\nother-doc §99 is elsewhere.\n")
        self.assertEqual((rc, only("R3c", out + err)), (0, []))

    def test_ignore_before_skips_references_to_other_documents(self):
        files = {"mod/a/AGENTS.md": "the 49 號設計書 §9\n", "docs/a.md": self.SPEC}
        cfg = self.CFG.replace('level = "error"\n', 'level = "error"\nignore_before = [\'設計書\\s*$\']\n')
        rc, out, err = lint(files, cfg)
        self.assertEqual((rc, only("R3c", out + err)), (0, []))
        self.assertEqual(lint(files, self.CFG)[0], 1)

    def test_missing_section_fails(self):
        rc, _, err = self.run_one("ok\nSee §9.\n")
        self.assertEqual(rc, 1)
        self.assertIn("mod/a/AGENTS.md:2: error: R3c: §9 has no matching heading in docs/a.md", err)

    def test_missing_spec_file_is_reported_once_per_file(self):
        rc, _, err = self.run_one("§1 §2\n", spec=None)
        self.assertEqual(rc, 1)
        self.assertEqual(len(only("R3c", err)), 1)

    def test_inactive_without_specs(self):
        rc, out, err = lint({"AGENTS.md": "§9\n"}, '[rules.R3c]\nlevel = "error"\n')
        self.assertEqual((rc, only("R3c", out + err)), (0, []))


class RotTest(unittest.TestCase):  # R4a, R4b
    CFG = '[rules.R4a]\nlevel = "error"\n[rules.R4b]\nlevel = "warn"\n'

    def test_clean_text_passes(self):
        text = "Keep rules short.\nDecision in `docs/adr/2026-09-15-choice.md` and docs/plans/2026-10-01-x.md.\nVersion 1.2.3.\n"
        rc, out, err = lint({"AGENTS.md": text}, self.CFG)
        self.assertEqual((rc, only("R4a", out + err), only("R4b", out + err)), (0, [], []))

    def test_dates_and_issue_numbers_are_errors(self):
        text = "ok\nChanged on 2026-10-31 for this.\nFixes #123.\nSee issue 45 and PR 7.\n"
        rc, _, err = lint({"AGENTS.md": text}, self.CFG)
        self.assertEqual(rc, 1)
        got = only("R4a", err)
        self.assertTrue(any(line.startswith("AGENTS.md:2: error: R4a: date '2026-10-31'") for line in got), got)
        self.assertTrue(any(line.startswith("AGENTS.md:3: error: R4a: issue reference '#123'") for line in got), got)
        self.assertTrue(any("'issue 45'" in line for line in got), got)
        self.assertTrue(any("'PR 7'" in line for line in got), got)

    def test_date_prefixed_slug_is_a_name_not_a_date(self):
        rc, out, err = lint({"AGENTS.md": "See ADR 2026-09-25-codemeta-retirement D3.\n"}, self.CFG)
        self.assertEqual((rc, only("R4a", out + err)), (0, []))

    def test_narrative_words_follow_r4b(self):
        rc, out, err = lint({"AGENTS.md": "Currently the cache is off.\nTemporarily skip it.\n"}, self.CFG)
        self.assertEqual(rc, 0)
        self.assertEqual(len(only("R4b", out)), 2)
        self.assertEqual(err, [])
        rc, _, err = lint({"AGENTS.md": "Currently x.\n"}, '[rules.R4b]\nlevel = "error"\n')
        self.assertEqual((rc, len(only("R4b", err))), (1, 1))

    def test_each_id_turns_off_alone(self):
        text = "Currently x.\nDone 2026-10-31.\n"
        rc, out, err = lint({"AGENTS.md": text}, '[rules.R4a]\nlevel = "error"\n[rules.R4b]\nlevel = "off"\n')
        self.assertEqual((rc, out, [x.split(": R4a: ")[0] for x in err]), (1, [], ["AGENTS.md:2: error"]))
        rc, out, err = lint({"AGENTS.md": text}, '[rules.R4a]\nlevel = "off"\n[rules.R4b]\nlevel = "warn"\n')
        self.assertEqual((rc, [x.split(": R4b: ")[0] for x in out], err), (0, ["AGENTS.md:1: warning"], []))

    def test_r4a_at_warn_reports_warnings(self):
        rc, out, err = lint({"AGENTS.md": "Done 2026-10-31.\n"}, '[rules.R4a]\nlevel = "warn"\n')
        self.assertEqual(rc, 0)
        self.assertEqual(len(only("R4a", out)), 1)

    def test_keys_live_with_their_id(self):
        for cfg, where, hint in (
            ('[rules.R4a]\nnarrative_level = "off"\n', "rules.R4a.narrative_level", "R4b"),
            ('[rules.R4a]\nnarrative_words = []\n', "rules.R4a.narrative_words", "R4b"),
            ('[rules.R4b]\ndate_patterns = []\n', "rules.R4b.date_patterns", "R4a"),
        ):
            rc, _, err = lint({"AGENTS.md": "ok\n"}, cfg)
            self.assertEqual(rc, 2, cfg)
            self.assertTrue(any(where in x and hint in x.split(where, 1)[1] for x in err), err)

    def test_code_fences_and_comments_are_skipped(self):
        rc, out, err = lint({"AGENTS.md": "```\n2026-10-31 #12\n```\n<!-- 2026-10-31 -->\n"}, self.CFG)
        self.assertEqual((rc, out, err), (0, [], []))


def dup(shared="", r5a="error", r5b="off"):
    return f'[shared.duplicates]\n{shared}[rules.R5a]\nlevel = "{r5a}"\n[rules.R5b]\nlevel = "{r5b}"\n'


class DuplicateTest(unittest.TestCase):  # R5a, R5b
    CFG = dup()
    LINE = "Always run the full test suite before you push a change to main.\n"

    def test_unique_short_and_heading_lines_pass(self):
        files = {"AGENTS.md": "# Title that is long enough to be counted by the rule\nshort line\n" + self.LINE,
                 "sub/AGENTS.md": "# Title that is long enough to be counted by the rule\nshort line\nOther text that differs from the root text entirely.\n"}
        rc, out, err = lint(files, dup(r5b="warn"))
        self.assertEqual((rc, only("R5a", out + err), only("R5b", out + err)), (0, [], []))

    def test_ancestor_descendant_duplicate_is_an_error_on_the_descendant(self):
        files = {"AGENTS.md": "x\n" + self.LINE, "sub/AGENTS.md": "y\nz\n- " + self.LINE}
        rc, out, err = lint(files, self.CFG)
        self.assertEqual(rc, 1)
        got = only("R5a", err)
        self.assertEqual(len(got), 1, got)
        self.assertTrue(got[0].startswith("sub/AGENTS.md:3: error: R5a: line repeats AGENTS.md:2"), got)
        self.assertEqual(out, [])

    def test_sibling_duplicate_is_a_warning_on_both(self):
        files = {"a/AGENTS.md": self.LINE, "b/AGENTS.md": "x\n" + self.LINE, "AGENTS.md": "root\n"}
        rc, out, err = lint(files, dup(r5b="warn"))
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(line.split(":")[0] for line in only("R5b", out)), ["a/AGENTS.md", "b/AGENTS.md"])

    def test_r5b_error_makes_them_errors(self):
        files = {"a/AGENTS.md": self.LINE, "b/AGENTS.md": self.LINE}
        rc, _, err = lint(files, dup(r5a="warn", r5b="error"))
        self.assertEqual(rc, 1)
        self.assertEqual(len(only("R5b", err)), 2, err)

    def test_r5b_level_does_not_reach_r5a(self):
        files = {"AGENTS.md": self.LINE, "sub/AGENTS.md": self.LINE}
        rc, out, err = lint(files, dup(r5a="warn", r5b="error"))
        self.assertEqual((rc, len(only("R5a", out)), err), (0, 1, []))

    def test_a_line_that_repeats_an_ancestor_is_never_a_sibling_duplicate(self):
        # Grouped once: with R5a off, sub/AGENTS.md's line is still not reported under R5b.
        files = {"AGENTS.md": self.LINE, "sub/AGENTS.md": self.LINE}
        rc, out, err = lint(files, dup(r5a="off", r5b="error"))
        self.assertEqual((rc, out, err), (0, [], []))

    def test_default_reports_only_same_name_ancestor_pairs(self):
        # An agent working in sub/ loads AGENTS.md and sub/AGENTS.md; the other pairs are read by
        # different agents (AGENTS.md vs CLAUDE.md) or by none together (siblings).
        files = {"AGENTS.md": self.LINE, "CLAUDE.md": self.LINE, "sub/AGENTS.md": self.LINE,
                 "docs/CLAUDE.md": self.LINE, "a/AGENTS.md": "a\n" + self.LINE}
        rc, out, err = lint(files)
        self.assertEqual(rc, 0)
        got = sorted(line.split(": warning: R5a: ")[0] + " " + line.split("line repeats ")[1].split(" ")[0]
                     for line in only("R5a", out))
        self.assertEqual(got, ["a/AGENTS.md:2 AGENTS.md:1", "docs/CLAUDE.md:1 CLAUDE.md:1", "sub/AGENTS.md:1 AGENTS.md:1"])
        self.assertEqual(only("R5b", out + err), [])

    def test_same_name_ancestors_leave_other_pairs_to_r5b(self):
        # With same-name pairs only, AGENTS.md + CLAUDE.md in one directory are compared as siblings.
        files = {"AGENTS.md": self.LINE, "CLAUDE.md": self.LINE}
        rc, out, err = lint(files, dup('ancestor_pairs = "same-name"\n', r5b="warn"))
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(x.split(":")[0] for x in only("R5b", out)), ["AGENTS.md", "CLAUDE.md"])
        self.assertTrue(all("sibling file(s)" in x for x in only("R5b", out)))

    def test_any_pairs_keep_the_0_4_behavior(self):
        files = {"AGENTS.md": self.LINE, "CLAUDE.md": self.LINE, "sub/CLAUDE.md": self.LINE}
        rc, _, err = lint(files, dup('ancestor_pairs = "any"\n'))
        self.assertEqual(rc, 1)
        self.assertEqual(sorted(x.split(": error: R5a: ")[0] for x in only("R5a", err)), ["CLAUDE.md:1", "sub/CLAUDE.md:1"])

    def test_strict_compares_any_pairs(self):
        files = {"AGENTS.md": self.LINE, "CLAUDE.md": self.LINE}
        rc, out, _ = lint(files, 'extends = ["preset:strict"]\n')
        self.assertTrue([x for x in only("R5a", out) if x.startswith("CLAUDE.md:1: warning: R5a: line repeats AGENTS.md:1")], out)

    def test_bad_ancestor_pairs_fails(self):
        rc, _, err = lint({"AGENTS.md": "ok\n"}, dup('ancestor_pairs = "same"\n'))
        self.assertEqual(rc, 2)
        self.assertIn("shared.duplicates.ancestor_pairs", "\n".join(err))

    def test_shared_keys_and_sibling_level_name_their_new_place(self):
        for cfg, where, hint in (
            ('[rules.R5a]\nmin_chars = 10\n', "rules.R5a.min_chars", "[shared.duplicates]"),
            ('[rules.R5b]\nancestor_pairs = "any"\n', "rules.R5b.ancestor_pairs", "[shared.duplicates]"),
            ('[rules.R5a]\nsibling_level = "warn"\n', "rules.R5a.sibling_level", "R5b"),
            ('[shared.duplicates]\nlevel = "warn"\n', "shared.duplicates", "unknown key"),
            ('[shared.dupes]\nmin_chars = 10\n', "shared", "unknown key"),
        ):
            rc, _, err = lint({"AGENTS.md": "ok\n"}, cfg)
            self.assertEqual(rc, 2, cfg)
            self.assertTrue(any(where in x and hint in x.split(where, 1)[1] for x in err), (cfg, err))

    def test_threshold_is_configurable(self):
        files = {"AGENTS.md": "short repeated line\n", "sub/AGENTS.md": "short repeated line\n"}
        self.assertEqual(lint(files, self.CFG)[0], 0)
        self.assertEqual(lint(files, dup("min_chars = 10\n"))[0], 1)

    def test_compares_the_full_set_even_when_a_file_is_named(self):
        files = {"AGENTS.md": self.LINE, "sub/AGENTS.md": self.LINE}
        rc, _, err = lint(files, self.CFG, "sub/AGENTS.md")
        self.assertEqual(rc, 1)


class ConstantsTest(unittest.TestCase):  # R6
    def test_candidates_are_warnings_even_at_error_level(self):
        text = "Limit is `MaxBatch = 100` here.\nRetry with MAX_RETRIES 5 times.\nTimeout of 30 seconds.\n"
        rc, out, err = lint({"AGENTS.md": text}, '[rules.R6]\nlevel = "error"\n')
        self.assertEqual(rc, 0)
        self.assertEqual(err, [])
        self.assertEqual(sorted(line.split(":")[1] for line in only("R6", out)), ["1", "2", "3"])

    def test_prose_without_values_passes(self):
        rc, out, err = lint({"AGENTS.md": "Use the batch limit from the code.\nSee `model.MaxBatch`.\n"})
        self.assertEqual((rc, only("R6", out + err)), (0, []))


class ClaudeMdTest(unittest.TestCase):  # C1
    def test_import_only_passes_with_agents_md_next_to_it(self):
        rc, out, err = lint({"AGENTS.md": "ok\n", "CLAUDE.md": "@AGENTS.md\n"}, '[rules.C1]\nlevel = "error"\n')
        self.assertEqual((rc, only("C1", out + err)), (0, []))

    def test_no_claude_md_passes_in_both_modes(self):
        for mode in ("import-only", "forbid"):
            rc, out, err = lint({"AGENTS.md": "ok\n"}, f'[rules.C1]\nlevel = "error"\nmode = "{mode}"\n')
            self.assertEqual((rc, only("C1", out + err)), (0, []), mode)

    def test_import_only_rejects_other_content(self):
        rc, _, err = lint({"AGENTS.md": "ok\n", "CLAUDE.md": "@AGENTS.md\nextra\n"}, '[rules.C1]\nlevel = "error"\n')
        self.assertEqual(rc, 1)
        self.assertIn("CLAUDE.md: error: C1: CLAUDE.md must contain only the line '@AGENTS.md'", err)

    def test_import_only_requires_the_sibling_agents_md(self):
        rc, _, err = lint({"AGENTS.md": "ok\n", "sub/CLAUDE.md": "@AGENTS.md\n"}, '[rules.C1]\nlevel = "error"\n')
        self.assertEqual(rc, 1)
        self.assertTrue(any("sub/AGENTS.md is not tracked" in line for line in err), err)

    def test_forbid_rejects_even_a_valid_import(self):
        rc, _, err = lint({"AGENTS.md": "ok\n", "CLAUDE.md": "@AGENTS.md\n"}, '[rules.C1]\nlevel = "error"\nmode = "forbid"\n')
        self.assertEqual(rc, 1)
        self.assertTrue(any("must not exist" in line for line in err), err)

    def test_forbid_sees_files_outside_discover_globs(self):
        cfg = '[discover]\nglobs = ["AGENTS.md"]\n[rules.C1]\nlevel = "error"\nmode = "forbid"\n'
        rc, _, err = lint({"AGENTS.md": "ok\n", "CLAUDE.md": "x\n"}, cfg)
        self.assertEqual(rc, 1)

    def test_unknown_mode_fails_the_config(self):
        rc, _, err = lint({"AGENTS.md": "ok\n"}, '[rules.C1]\nmode = "strict"\n')
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
