"""R1a to R1d (docs/adr/0005): per-file bytes and lines by path glob (first match wins), combined
bytes on a path, line length; one level per id; removed keys and ids; preset values."""
import unittest

import helpers

CFG = ".agentfile-lint.toml"


def limits(rule_id, *entries):
    return "".join(
        f"[[rules.{rule_id}.limits]]\n" + "".join(f"{k} = {v!r}\n".replace("'", '"') for k, v in e.items()) for e in entries
    )


def level(rule_id, value="error", extra=""):
    return f'[rules.{rule_id}]\nlevel = "{value}"\n{extra}'


def run(files, toml):
    return helpers.run_new(helpers.make_repo({**files, CFG: toml}))


def ids(r, rule_id):
    return [x for x in r.stdout.splitlines() if f": {rule_id}: " in x]


class SizeLimitsTest(unittest.TestCase):
    def test_first_match_wins_in_order(self):
        toml = limits("R1a", {"glob": "**/AGENTS.md", "max_bytes": 50}, {"glob": "sub/AGENTS.md", "max_bytes": 1000})
        r = run({"sub/AGENTS.md": "x\n" * 60}, toml)  # 120 bytes; the first (tight) entry matches
        self.assertEqual(r.returncode, 1)
        self.assertIn("sub/AGENTS.md: error: R1a: file is 120 bytes, limit 50", r.stdout)
        swapped = limits("R1a", {"glob": "sub/AGENTS.md", "max_bytes": 1000}, {"glob": "**/AGENTS.md", "max_bytes": 50})
        self.assertEqual(run({"sub/AGENTS.md": "x\n" * 60}, swapped).returncode, 0)

    def test_star_does_not_cross_slash(self):
        toml = limits("R1a", {"glob": "*/AGENTS.md", "max_bytes": 10})
        self.assertEqual(run({"a/b/AGENTS.md": "x\n" * 60}, toml).returncode, 0)
        self.assertEqual(run({"a/AGENTS.md": "x\n" * 60}, toml).returncode, 1)

    def test_max_lines(self):
        toml = level("R1b") + limits("R1b", {"glob": "AGENTS.md", "max_lines": 3})
        r = run({"AGENTS.md": "a\nb\nc\nd\n"}, toml)
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGENTS.md: error: R1b: file is 4 lines, limit 3", r.stdout)
        self.assertEqual(run({"AGENTS.md": "a\nb\nc\n"}, toml).returncode, 0)  # equal passes

    def test_both_limits_report_both(self):
        toml = level("R1b") + limits("R1a", {"glob": "AGENTS.md", "max_bytes": 5}) + limits("R1b", {"glob": "AGENTS.md", "max_lines": 1})
        out = run({"AGENTS.md": "aaaa\nbbbb\n"}, toml).stdout
        self.assertIn("AGENTS.md: error: R1a: file is 10 bytes, limit 5", out)
        self.assertIn("AGENTS.md: error: R1b: file is 2 lines, limit 1", out)

    def test_each_id_takes_the_first_match_of_its_own_list(self):
        # R1b's first entry matches every AGENTS.md; R1a's list has no such entry, so its tighter
        # sub/ entry still applies.
        toml = (level("R1b") + limits("R1a", {"glob": "sub/AGENTS.md", "max_bytes": 5})
                + limits("R1b", {"glob": "**/AGENTS.md", "max_lines": 100}, {"glob": "sub/AGENTS.md", "max_lines": 1}))
        r = run({"sub/AGENTS.md": "aaaa\nbbbb\n"}, toml)
        self.assertEqual(ids(r, "R1a"), ["sub/AGENTS.md: error: R1a: file is 10 bytes, limit 5"])
        self.assertEqual(ids(r, "R1b"), [])

    def test_excluded_blocks_apply_before_both_measures(self):
        toml = (level("R1b") + limits("R1a", {"glob": "AGENTS.md", "max_bytes": 10}) + limits("R1b", {"glob": "AGENTS.md", "max_lines": 2})
                + '[shared.size]\nexcluded_blocks = [{ begin = "<!-- B -->", end = "<!-- E -->" }]\n')
        text = "a\n<!-- B -->\n" + "zzzz\n" * 30 + "<!-- E -->\nb\n"
        self.assertEqual(run({"AGENTS.md": text}, toml).returncode, 0)

    def test_no_matching_entry_means_no_size_limit(self):
        toml = level("R1b") + limits("R1a", {"glob": "other/AGENTS.md", "max_bytes": 5}) + limits("R1b", {"glob": "other/AGENTS.md", "max_lines": 1})
        self.assertEqual(run({"AGENTS.md": "x\n" * 5000}, toml).returncode, 0)

    def test_empty_limits_means_no_size_limit(self):
        self.assertEqual(run({"AGENTS.md": "x\n" * 5000}, level("R1b", extra="limits = []\n")).returncode, 0)

    def test_old_max_bytes_key_fails_with_migration_hint(self):
        r = run({"AGENTS.md": "ok\n"}, "[rules.R1a.max_bytes]\nroot = 100\n")
        self.assertEqual(r.returncode, 2)
        self.assertIn("rules.R1a.max_bytes", r.stderr)
        self.assertIn("[[rules.<id>.limits]]", r.stderr)

    def test_entry_validation(self):
        for bad in (
            '[[rules.R1a.limits]]\nglob = "AGENTS.md"\n',                       # no limit
            '[[rules.R1a.limits]]\nmax_bytes = 5\n',                            # no glob
            '[[rules.R1a.limits]]\nglob = "A"\nmax_bytes = 5\nmax_line = 3\n',  # typo
            '[[rules.R1a.limits]]\nglob = "A"\nmax_lines = 3\n',                # the other id's key
            '[[rules.R1b.limits]]\nglob = "A"\nmax_bytes = 3\n',                # the other id's key
            '[[rules.R1b.limits]]\nglob = "A"\nmax_lines = 0\n',                # not positive
        ):
            self.assertEqual(run({"AGENTS.md": "ok\n"}, bad).returncode, 2, bad)

    def test_preset_values(self):
        rules = _preset()["rules"]
        self.assertEqual(rules["R1a"], {"level": "error", "limits": []})
        self.assertEqual(rules["R1b"], {"level": "warn", "limits": [
            {"glob": "**/AGENTS.md", "max_lines": 200},
            {"glob": "**/CLAUDE.md", "max_lines": 200},
        ]})
        self.assertEqual(rules["R1c"], {"level": "error", "limits": [{"glob": "**/AGENTS.md", "max_bytes": 32768}]})
        self.assertEqual(rules["R1d"], {"level": "off"})
        self.assertEqual(rules["R1e"], {"level": "warn", "limits": [
            {"glob": ".claude/CLAUDE.md"},
            {"glob": ".claude/rules/**/*.md", "max_chars": 40000, "frontmatter_key": "paths"},
            {"glob": ".claude/rules/**/*.md"},
            {"glob": "*/**/CLAUDE.md", "max_chars": 40000},
            {"glob": "*/**/CLAUDE.local.md", "max_chars": 40000},
            {"glob": "*/**/.claude/rules/**/*.md", "max_chars": 40000},
        ]})
        self.assertEqual(_preset()["shared"]["size"], {"excluded_blocks": []})

    def test_default_r1b_covers_agents_and_claude_md(self):
        files = {"AGENTS.md": "x\n" * 201, "CLAUDE.md": "x\n" * 201, "sub/CLAUDE.md": "x\n" * 201, "a/b/AGENTS.md": "x\n" * 201}
        r = helpers.run_new(helpers.make_repo(files))
        self.assertEqual((r.returncode, r.stderr), (0, ""))  # 200 lines is guidance, not a hard limit: warn
        for p in files:
            self.assertIn(f"{p}: warning: R1b: file is 201 lines, limit 200", r.stdout)


class LevelsTest(unittest.TestCase):
    """Each id has its own level (docs/adr/0005); the removed sub-level keys fail with a hint."""

    def test_default_r1b_warns_on_stdout_and_exits_0(self):
        r = run({"AGENTS.md": "a\nb\nc\n"}, limits("R1b", {"glob": "AGENTS.md", "max_lines": 2}))
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn("AGENTS.md: warning: R1b: file is 3 lines, limit 2", r.stdout)

    def test_levels_are_per_id(self):
        toml = limits("R1a", {"glob": "AGENTS.md", "max_bytes": 5}) + limits("R1b", {"glob": "AGENTS.md", "max_lines": 1})
        r = run({"AGENTS.md": "aaaa\nbbbb\n"}, toml)
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGENTS.md: error: R1a: file is 10 bytes, limit 5", r.stdout)
        self.assertIn("AGENTS.md: warning: R1b: file is 2 lines, limit 1", r.stdout)

    def test_r1a_at_warn(self):
        r = run({"AGENTS.md": "aaaa\nbbbb\n"}, level("R1a", "warn") + limits("R1a", {"glob": "AGENTS.md", "max_bytes": 5}))
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn("AGENTS.md: warning: R1a: file is 10 bytes, limit 5", r.stdout)

    def test_off_skips_that_id(self):
        toml = (level("R1a", "off") + level("R1b", "off")
                + limits("R1a", {"glob": "AGENTS.md", "max_bytes": 5}) + limits("R1b", {"glob": "AGENTS.md", "max_lines": 1}))
        r = run({"AGENTS.md": "aaaa\nbbbb\n"}, toml)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_r1c_level_is_its_own(self):
        # R1c at warn while R1b is raised to error: each finding follows its own id.
        files = {"AGENTS.md": kb(20000), "a/AGENTS.md": kb(20000) + "x\n" * 300}
        r = run(files, level("R1b") + level("R1c", "warn"))
        self.assertIn("a/AGENTS.md: error: R1b: file is 500 lines, limit 200", r.stdout)
        self.assertIn("a/AGENTS.md: warning: R1c: file and its ancestors (AGENTS.md) total 40600 bytes, limit 32768", r.stdout)

    def test_removed_keys_name_their_replacement(self):
        cases = {
            limits("R1a", {"glob": "A", "max_bytes": 5, "bytes_level": "warn"}): ("rules.R1a.limits[0].bytes_level", "R1a"),
            limits("R1b", {"glob": "A", "max_lines": 5, "lines_level": "warn"}): ("rules.R1b.limits[0].lines_level", "R1b"),
            limits("R1c", {"glob": "A", "max_bytes": 5, "level": "warn"}): ("rules.R1c.limits[0].level", "[rules.<id>]"),
            level("R1a", extra="path_limits = []\n"): ("rules.R1a.path_limits", "R1c"),
            level("R1a", extra="max_line_chars = 5\n"): ("rules.R1a.max_line_chars", "R1d"),
            level("R1d", extra="max_line_chars = 5\n"): ("rules.R1d.max_line_chars", "max_chars"),
            level("R1a", extra="excluded_blocks = []\n"): ("rules.R1a.excluded_blocks", "[shared.size]"),
            limits("R1a", {"glob": "A", "max_bytes": 5, "max_lines": 3}): ("rules.R1a.limits[0].max_lines", "R1b"),
            limits("R1b", {"glob": "A", "max_lines": 5, "max_bytes": 3}): ("rules.R1b.limits[0].max_bytes", "R1a"),
            level("R1a", extra="max_lines = 3\n"): ("rules.R1a.max_lines", "R1b"),
        }
        for toml, (where, replacement) in cases.items():
            r = run({"AGENTS.md": "ok\n"}, toml)
            self.assertEqual(r.returncode, 2, toml)
            self.assertIn(f"{where}: ", r.stderr)
            self.assertIn(replacement, r.stderr.split(where, 1)[1])

    def test_r1d_off_checks_no_line_length(self):
        r = run({"AGENTS.md": "y" * 5000 + "\n"}, "")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_r1d_needs_max_chars_once_on(self):
        r = run({"AGENTS.md": "ok\n"}, level("R1d"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("rules.R1d: missing key max_chars", r.stderr)

    def test_r1d_reports_long_lines(self):
        r = run({"AGENTS.md": "y" * 600 + "\n"}, level("R1d", extra="max_chars = 500\n"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGENTS.md:1: error: R1d: line is 600 characters, limit 500", r.stdout)


class DefaultLimitsTest(unittest.TestCase):
    """The default preset uses only limits with an external source (Codex 32 KiB, Claude Code 200 lines)."""

    def test_agents_md_over_32_kib_is_an_error_at_any_depth(self):
        big = "x" * 99 + "\n"
        for path in ("AGENTS.md", "a/b/AGENTS.md"):
            r = helpers.run_new(helpers.make_repo({path: big * 328}))  # 32800 bytes
            self.assertEqual(r.returncode, 1, path)
            self.assertIn(f"{path}: error: R1c: file is 32800 bytes, limit 32768", r.stdout)
        self.assertEqual(helpers.run_new(helpers.make_repo({"AGENTS.md": "x" * 32767 + "\n"})).returncode, 0)

    def test_claude_md_has_no_byte_limit(self):
        r = helpers.run_new(helpers.make_repo({"CLAUDE.md": ("x" * 99 + "\n") * 199 + "y" * 40000 + "\n"}))
        self.assertEqual(r.returncode, 0)
        self.assertNotIn(": R1", r.stdout + r.stderr)  # neither a byte limit nor a line-length limit

    def test_an_r1b_exception_does_not_hide_the_r1c_error(self):
        # The 0.6.0 defect behind docs/adr/0005: one allowlist entry for the 200-line warning also hid
        # the 32 KiB error on the same file, and the run exited 0.
        toml = ('[[allowlist.entries]]\nrule = "R1b"\npath = "AGENTS.md"\ncount = 1\nreason = "split in progress"\n'
                "expires = 2026-07-01\n")
        root = helpers.make_repo({"AGENTS.md": ("x" * 99 + "\n") * 400, CFG: toml})
        r = helpers.run_new(root, "--today", "2026-06-01")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(ids(r, "R1b"), [])
        self.assertEqual(ids(r, "R1c"), ["AGENTS.md: error: R1c: file is 40000 bytes, limit 32768"])


def kb(n):
    """A file of exactly n bytes, in 100-byte lines."""
    return ("x" * 99 + "\n") * (n // 100) + "y" * (n % 100)


PATH_32K = '[[rules.R1c.limits]]\nglob = "**/AGENTS.md"\nmax_bytes = 32768\n'
NO_LINES = "[rules.R1b]\nlimits = []\n"


class CharLimitTest(unittest.TestCase):
    """R1e (`file-chars`): Claude Code's per-file character limit on the files it loads on demand
    (https://code.claude.com/docs/en/memory, "Claude ignores the end of my subdirectory CLAUDE.md"):
    characters as `wc -m` counts them, after the frontmatter and block-level HTML comments are removed
    and surrounding whitespace is trimmed; `excluded_blocks` does not apply."""

    SUB = "sub/CLAUDE.md"

    def r1e(self, files, toml=""):
        r = run(files, toml)
        self.assertEqual(r.stderr, "")
        return r, ids(r, "R1e")

    def test_boundary_at_40000(self):
        for n, reported in ((39_999, False), (40_000, False), (40_001, True)):
            r, found = self.r1e({self.SUB: "x" * n + "\n"})
            self.assertEqual(r.returncode, 0, n)  # a warning
            self.assertEqual(found, [f"{self.SUB}: warning: R1e: file is {n} characters, limit 40000"] if reported else [], n)

    def test_counts_characters_not_bytes(self):
        _, found = self.r1e({self.SUB: "中" * 40_000})  # 120000 bytes, 40000 characters
        self.assertEqual(found, [])
        _, found = self.r1e({self.SUB: "中" * 39_999 + "😀😀"})  # one code point each, as `wc -m` counts
        self.assertEqual(found, [f"{self.SUB}: warning: R1e: file is 40001 characters, limit 40000"])

    def test_a_carriage_return_is_a_character(self):
        # 39998 + CR + LF + 1: `wc -m` counts 40001; the same text with LF only is 40000.
        _, found = self.r1e({self.SUB: "x" * 39_998 + "\r\n" + "y"})
        self.assertEqual(found, [f"{self.SUB}: warning: R1e: file is 40001 characters, limit 40000"])
        self.assertEqual(self.r1e({self.SUB: "x" * 39_998 + "\n" + "y"})[1], [])

    def test_surrounding_whitespace_is_trimmed(self):
        self.assertEqual(self.r1e({self.SUB: "﻿\n\n  \t" + "x" * 40_000 + "\n\n \r\n"})[1], [])

    def test_frontmatter_is_not_counted(self):
        head = "---\npaths:\n  - \"src/**\"\n---\n"
        self.assertEqual(self.r1e({self.SUB: head + "x" * 40_000})[1], [])
        self.assertEqual(self.r1e({self.SUB: head.replace("\n", "\r\n") + "x" * 40_000})[1], [])
        _, found = self.r1e({self.SUB: head + "x" * 40_001})
        self.assertEqual(found, [f"{self.SUB}: warning: R1e: file is 40001 characters, limit 40000"])
        # An unterminated block is not frontmatter: every character counts.
        _, found = self.r1e({self.SUB: "---\n" + "x" * 39_997})
        self.assertEqual(found, [f"{self.SUB}: warning: R1e: file is 40001 characters, limit 40000"])

    def test_block_html_comments_are_not_counted(self):
        comment = "<!-- " + "c" * 500 + "\nmore -->\n\n\n"
        self.assertEqual(self.r1e({self.SUB: "x" * 20_000 + "\n\n" + comment + "x" * 19_998})[1], [])
        self.assertEqual(self.r1e({self.SUB: "   " + comment + "x" * 40_000})[1], [])  # up to 3 spaces of indent

    def test_comments_that_stay(self):
        # Hand-counted (after the trim): text after a comment on its line stays, the comment goes; an
        # inline comment, one in a fenced code block, an indented one (code) and an unterminated one count.
        cases = {
            "<!-- c --> kept\n" + "x" * 39_996: 40_001,       # "kept\n" 5 + 39996
            "x <!-- c -->\n" + "x" * 39_988: 40_001,          # inline in a paragraph: 13 + 39988
            "```\n<!-- c -->\n```\n" + "x" * 39_982: 40_001,  # in a fence: 19 + 39982
            "    <!-- c -->\n" + "x" * 39_990: 40_001,        # indented code, leading spaces trimmed: 11 + 39990
            "<!-- " + "x" * 39_996: 40_001,                    # never closed: 5 + 39996
        }
        for text, n in cases.items():
            self.assertEqual(self.r1e({self.SUB: text})[1], [f"{self.SUB}: warning: R1e: file is {n} characters, limit 40000"], text[:16])
        # A comment block may interrupt a paragraph: "x\n" stays, the comment line goes.
        self.assertEqual(self.r1e({self.SUB: "x\n<!-- c -->\n" + "y" * 39_998})[1], [])

    def test_excluded_blocks_do_not_apply(self):
        toml = '[shared.size]\nexcluded_blocks = [{ begin = "BEGIN", end = "END" }]\n'
        _, found = self.r1e({self.SUB: "BEGIN\n" + "x" * 40_000 + "\nEND"}, toml)
        self.assertEqual(found, [f"{self.SUB}: warning: R1e: file is 40010 characters, limit 40000"])

    def test_which_files_the_default_checks(self):
        big = "x" * 40_001
        scoped = "---\npaths: [\"src/**\"]\n---\n" + big
        files = {
            "CLAUDE.md": big, ".claude/CLAUDE.md": big, "CLAUDE.local.md": big,      # load at launch
            ".claude/rules/always.md": big,                                           # no `paths`: at launch
            ".claude/rules/broken.md": "---\npaths: [\n---\n" + big,                  # bad YAML: as if no `paths`
            ".claude/rules/x/CLAUDE.md": big,                                         # a root rule, not a subdirectory CLAUDE.md
            ".claude/rules/y/CLAUDE.md": scoped,
            "AGENTS.md": "ok\n", "sub/AGENTS.md": "ok\n",
            "sub/CLAUDE.md": big, "a/b/CLAUDE.local.md": big,                         # subdirectories: on demand
            "sub/.claude/rules/x.md": big, ".claude/rules/deep/scoped.md": scoped,    # on demand
        }
        r, found = self.r1e(files)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(sorted(line.split(":")[0] for line in found),
                         [".claude/rules/deep/scoped.md", ".claude/rules/y/CLAUDE.md", "a/b/CLAUDE.local.md",
                          "sub/.claude/rules/x.md", "sub/CLAUDE.md"])

    def test_limits_are_configurable(self):
        toml = limits("R1e", {"glob": "sub/**", "max_chars": 150_000}, {"glob": "**", "max_chars": 10})
        _, found = self.r1e({self.SUB: "x" * 40_001, "CLAUDE.md": "x" * 11}, toml)
        self.assertEqual(found, ["CLAUDE.md: warning: R1e: file is 11 characters, limit 10"])
        # An entry without max_chars sets no limit, and later entries are not tried (first match wins).
        toml = limits("R1e", {"glob": "CLAUDE.md"}, {"glob": "**", "max_chars": 10})
        self.assertEqual(self.r1e({"CLAUDE.md": "x" * 11}, toml)[1], [])
        # frontmatter_key: the entry applies only when the frontmatter has that top-level key.
        toml = limits("R1e", {"glob": "**", "max_chars": 10, "frontmatter_key": "owner"})
        self.assertEqual(self.r1e({"CLAUDE.md": "x" * 11}, toml)[1], [])
        _, found = self.r1e({"CLAUDE.md": "---\nowner: me\n---\n" + "x" * 11}, toml)
        self.assertEqual(found, ["CLAUDE.md: warning: R1e: file is 11 characters, limit 10"])

    def test_level_and_validation(self):
        r, found = self.r1e({self.SUB: "x" * 40_001}, level("R1e"))
        self.assertEqual((r.returncode, len(found)), (1, 1))
        self.assertEqual(self.r1e({self.SUB: "x" * 40_001}, level("R1e", "off"))[1], [])
        self.assertEqual(self.r1e({self.SUB: "x" * 40_001}, '[rules.file-chars]\nlevel = "off"\n')[1], [])
        for bad in (limits("R1e", {"glob": "**", "max_bytes": 1}), limits("R1e", {"max_chars": 1}),
                    limits("R1e", {"glob": "**", "max_chars": "1"}), limits("R1e", {"glob": "**", "frontmatter_key": 1}),
                    '[rules.R1e]\nmax_chars = 10\n'):
            self.assertEqual(run({"AGENTS.md": "ok\n"}, bad).returncode, 2, bad)

    def test_a_directive_cannot_name_it(self):
        r = run({self.SUB: "<!-- agentfile-lint-disable-next-line R1e -- too long -->\n" + "x" * 10}, "")
        self.assertEqual(r.returncode, 1)
        self.assertIn("R1e is a whole-file rule", r.stdout)


class PathLimitsTest(unittest.TestCase):
    """R1c: a file plus the files matching the same glob in its ancestor directories (Codex reads
    AGENTS.md from the root down to the working directory and stops at 32 KiB in total)."""

    def run_files(self, files, toml=PATH_32K):
        return run(files, NO_LINES + toml)

    def test_combined_overflow_is_reported_where_it_starts(self):
        r = self.run_files({"AGENTS.md": kb(20000), "a/AGENTS.md": kb(10000), "a/b/AGENTS.md": kb(5000), "a/b/c/AGENTS.md": kb(10)})
        self.assertEqual(r.returncode, 1)
        self.assertEqual([x for x in r.stdout.splitlines() if ": R1" in x],
                         ["a/b/AGENTS.md: error: R1c: file and its ancestors (AGENTS.md, a/AGENTS.md) total 35000 bytes, limit 32768"])

    def test_under_the_combined_limit_passes(self):
        r = self.run_files({"AGENTS.md": kb(20000), "a/AGENTS.md": kb(12768), "b/AGENTS.md": kb(12768)})
        self.assertEqual((r.returncode, r.stderr), (0, ""))  # siblings are separate paths; equal passes

    def test_a_single_file_over_the_limit(self):
        r = self.run_files({"AGENTS.md": kb(40000), "a/AGENTS.md": kb(10)})
        self.assertEqual([x for x in r.stdout.splitlines() if ": R1" in x],
                         ["AGENTS.md: error: R1c: file is 40000 bytes, limit 32768"])

    def test_only_files_matching_the_glob_count(self):
        r = self.run_files({"AGENTS.md": kb(20000), "a/CLAUDE.md": kb(20000), "a/AGENTS.md": kb(100)})
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_level_and_empty_list(self):
        files = {"AGENTS.md": kb(20000), "a/AGENTS.md": kb(20000)}
        r = self.run_files(files, level("R1c", "warn") + PATH_32K)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertIn("a/AGENTS.md: warning: R1c: file and its ancestors (AGENTS.md) total 40000 bytes, limit 32768", r.stdout)
        self.assertEqual(run(files, NO_LINES + "[rules.R1c]\nlimits = []\n").returncode, 0)

    def test_combined_size_counts_raw_bytes(self):
        # Codex counts the file as stored: neither excluded_blocks nor CRLF -> LF lower the total.
        block = '[shared.size]\nexcluded_blocks = [{ begin = "<!-- B -->", end = "<!-- E -->" }]\n'
        files = {"AGENTS.md": "<!-- B -->\n" + kb(20000) + "<!-- E -->\n", "a/AGENTS.md": kb(13000)}
        r = self.run_files(files, PATH_32K + block)
        self.assertIn("a/AGENTS.md: error: R1c: file and its ancestors (AGENTS.md) total 33022 bytes, limit 32768", r.stdout)
        crlf = {"AGENTS.md": ("x" * 98 + "\r\n") * 200, "a/AGENTS.md": ("y" * 98 + "\r\n") * 128}
        r = self.run_files(crlf)
        self.assertIn("a/AGENTS.md: error: R1c: file and its ancestors (AGENTS.md) total 32800 bytes, limit 32768", r.stdout)

    def test_entry_validation(self):
        for bad in (
            '[[rules.R1c.limits]]\nglob = "**/AGENTS.md"\n',                          # no max_bytes
            '[[rules.R1c.limits]]\nmax_bytes = 5\n',                                  # no glob
            '[[rules.R1c.limits]]\nglob = "A"\nmax_bytes = 5\nmax_lines = 3\n',      # unknown key
        ):
            self.assertEqual(run({"AGENTS.md": "ok\n"}, bad).returncode, 2, bad)

    def test_default_checks_the_combined_size(self):
        r = helpers.run_new(helpers.make_repo({"AGENTS.md": kb(20000), "pkg/AGENTS.md": kb(15000)}))
        self.assertEqual(r.returncode, 1)
        self.assertIn("pkg/AGENTS.md: error: R1c: file and its ancestors (AGENTS.md) total 35000 bytes, limit 32768", r.stdout)


BLOCK = '[shared.size]\nexcluded_blocks = [{ begin = "<!-- B -->", end = "<!-- E -->" }]\n'


def r1d(max_chars):
    return BLOCK + level("R1d", extra=f"max_chars = {max_chars}\n")


def wc_c(root, path):
    return (root / path).stat().st_size


class RawBytesTest(unittest.TestCase):
    """docs/adr/0004: single-file bytes and line numbers are those on disk; excluded blocks still drop out."""

    def run_files(self, files, toml):
        root = helpers.make_repo({**files, CFG: toml})
        return root, helpers.run_new(root)

    def test_crlf_bytes_equal_wc_c(self):
        data = b"ab\r\n" * 10  # 40 bytes on disk, 30 in text mode
        root, r = self.run_files({"AGENTS.md": data}, BLOCK + limits("R1a", {"glob": "AGENTS.md", "max_bytes": 39}))
        self.assertIn(f"AGENTS.md: error: R1a: file is {wc_c(root, 'AGENTS.md')} bytes, limit 39", r.stdout)
        self.assertEqual(wc_c(root, "AGENTS.md"), 40)

    def test_crlf_block_removes_its_raw_bytes(self):
        blk = b"<!-- B -->\r\nzzzz\r\n<!-- E -->\r\n"
        data = b"ab\r\n" + blk + b"cd\r\n"
        root, r = self.run_files({"AGENTS.md": data}, BLOCK + limits("R1a", {"glob": "AGENTS.md", "max_bytes": 1}))
        self.assertIn(f"file is {wc_c(root, 'AGENTS.md') - len(blk)} bytes", r.stdout)
        self.assertIn("file is 8 bytes", r.stdout)

    def test_line_after_block_uses_disk_line_number(self):
        text = "one\n<!-- B -->\na\n<!-- E -->\n" + "w" * 11 + "\n"
        _, r = self.run_files({"AGENTS.md": text}, r1d(10))
        self.assertEqual(text.split("\n").index("w" * 11) + 1, 5)  # what `grep -n` reports
        self.assertIn("AGENTS.md:5: error: R1d: line is 11 characters, limit 10", r.stdout)

    def test_only_line_endings_split_lines(self):
        text = "a\x0cb c\n" + "w" * 11 + "\n"  # form feed and U+2028 are characters, not line breaks
        _, r = self.run_files({"AGENTS.md": text}, r1d(10))
        self.assertEqual(r.stdout.count(": R1d:"), 1, r.stdout)
        self.assertIn("AGENTS.md:2: error: R1d: line is 11 characters", r.stdout)

    def test_lone_cr_after_block_end_is_removed(self):
        data = b"ab\r<!-- B -->\rzz\r<!-- E -->\rcd\r"
        _, r = self.run_files({"AGENTS.md": data}, BLOCK + limits("R1a", {"glob": "AGENTS.md", "max_bytes": 1}))
        self.assertIn("file is 6 bytes", r.stdout)

    def test_long_line_inside_block_not_reported(self):
        text = "one\n<!-- B -->\n" + "w" * 50 + "\n<!-- E -->\r\nok\n"
        _, r = self.run_files({"AGENTS.md": text}, r1d(10))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_lines_still_exclude_the_block(self):
        text = "a\r\n<!-- B -->\r\nx\r\n<!-- E -->\r\nb\r\n"
        _, r = self.run_files({"AGENTS.md": text.encode()}, BLOCK + limits("R1b", {"glob": "AGENTS.md", "max_lines": 1}))
        self.assertIn("file is 2 lines, limit 1", r.stdout)

    def test_other_rules_see_normalized_newlines(self):
        # The engine reads each file once; R4a sees the CRLF file with LF line ends, so `$` anchors work.
        toml = level("R4a", "error") + "date_patterns = ['20\\d\\d-\\d\\d-\\d\\d$']\n"
        _, r = self.run_files({"AGENTS.md": b"since 2026-01-02\r\nok\r\n"}, toml)
        self.assertIn("AGENTS.md:1: error: R4a: date '2026-01-02'", r.stdout)


def _preset():
    from importlib import resources
    import tomllib
    text = (resources.files("agentfile_lint") / "presets" / "default.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


if __name__ == "__main__":
    unittest.main()
