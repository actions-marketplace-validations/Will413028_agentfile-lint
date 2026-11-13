"""Rule files in `.claude/rules/` (P1 to P5; docs/rules.md "P1 to P5 rule files")."""
import json
import unittest

from helpers import make_repo, run_new

RULE = ".claude/rules/api.md"


def lint(files: dict[str, str], config: str = "", *args: str):
    """Findings as (path, line, rule) triples from a JSON run, and their messages."""
    files = dict(files)
    if config:
        files[".agentfile-lint.toml"] = config
    r = run_new(make_repo(files), "--format", "json", "--today", "2026-11-06", *args)
    if r.returncode == 2:
        raise AssertionError(r.stderr)
    doc = json.loads(r.stdout)
    return [(f["file"], f["line"], f["rule"]) for f in doc["findings"]], [f["message"] for f in doc["findings"]], r


def rule(frontmatter: str, **files: str) -> dict[str, str]:
    return {RULE: f"---\n{frontmatter}---\n\n# API\n", "src/api/a.ts": "x\n", "src/deep/er/b.ts": "x\n",
            "README.md": "x\n", **files}


def ids(frontmatter: str, config: str = "") -> list[str]:
    return [found[2] for found in lint(rule(frontmatter), config)[0]]


class QuietTest(unittest.TestCase):
    def test_rule_without_frontmatter_or_without_paths_reports_nothing(self):
        self.assertEqual(lint({RULE: "# API\n\n- validate input\n"})[0], [])
        self.assertEqual(ids("description: API rules\n"), [])

    def test_documented_forms_of_paths_report_nothing(self):
        for frontmatter in (
            'paths:\n  - "src/api/**/*.ts"\n',
            'paths: ["src/**/*.ts", "README.md"]\n',
            'paths: "docs/**, src/**/*.ts"\n'.replace("docs/**", "src/api/**"),
            'paths: "README.md, src/**/*.{js,ts}"\n',
            "paths: src/**/*.ts\n",
        ):
            with self.subTest(frontmatter=frontmatter):
                self.assertEqual(ids(frontmatter), [])

    def test_files_outside_a_rules_directory_are_not_checked(self):
        files = {"AGENTS.md": "---\nglobs: x\npaths: 5\n---\n\nRules.\n", ".claude/CLAUDE.md": "---\npaths: 5\n---\n\nRules.\n"}
        self.assertEqual(lint(files)[0], [])

    def test_rules_do_not_fail_the_run_by_default(self):
        found, _, r = lint(rule("paths: 5\n"))
        self.assertEqual((found, r.returncode), ([(RULE, 2, "P2")], 0))


class YamlTest(unittest.TestCase):
    """P1: Claude Code ignores a frontmatter that does not parse and loads the rule in every session."""

    def test_invalid_yaml_is_reported_at_the_error(self):
        found, messages, _ = lint(rule('description: d\npaths: [unclosed\n  - "src/**/*.ts"\n'))
        self.assertEqual([(f[0], f[2]) for f in found], [(RULE, "P1")])
        self.assertGreater(found[0][1], 1)
        self.assertIn("loads the rule without a path scope", messages[0])

    def test_values_claude_code_quotes_on_its_second_parse_are_not_errors(self):
        # Invalid YAML as written (`*` starts an alias, `{` a flow mapping), read by Claude Code all the same.
        for frontmatter in ("paths: **/*.ts\n", "paths: *.ts\n", "paths: {src,lib}/**\n",
                            'description: [unclosed\npaths:\n  - "src/**"\n', "description: a: b\npaths: src\n"):
            with self.subTest(frontmatter=frontmatter):
                self.assertEqual(ids(frontmatter), [])
        self.assertEqual(ids("paths: {lib}/**, *.go\n"), ["P3", "P3"])

    def test_second_parse_leaves_a_fully_quoted_value_alone(self):
        # Quoted at both ends: untouched (quoting it again would break it). Quoted at one end: quoted whole.
        self.assertEqual(ids('description: "a [b"\npaths: **/*.ts\n'), [])
        self.assertEqual(ids("paths: 'lib/*.go', *.ts\n"), ["P3"])
        self.assertEqual(ids('description: "ok" [\npaths: *.ts\n'), [])

    def test_second_parse_does_not_reach_list_items(self):
        found, _, _ = lint(rule("paths:\n  - **/*.ts\n"))
        self.assertEqual(found, [(RULE, 3, "P1")])

    def test_frontmatter_without_a_closing_line(self):
        found, _, _ = lint({RULE: '---\npaths:\n  - "src/**/*.ts"\n\n# API\n', "src/a.ts": "x\n"})
        self.assertEqual(found, [(RULE, 1, "P1")])


class PathsTypeTest(unittest.TestCase):
    """P2: a `paths` without a usable pattern scopes nothing."""

    def test_values_that_hold_no_pattern(self):
        for frontmatter in ("paths: 123\n", "paths: true\n", "paths:\n", 'paths: ""\n', "paths: []\n",
                            "paths:\n  - 5\n  - 6\n", 'paths:\n  a: "src/**/*.ts"\n', "paths: ~\n"):
            with self.subTest(frontmatter=frontmatter):
                found, messages, _ = lint(rule("description: d\n" + frontmatter))
                self.assertEqual(found, [(RULE, 3, "P2")])
                self.assertIn("loads the rule without a path scope", messages[0])

    def test_quoted_number_and_yaml_1_1_booleans_are_patterns(self):
        # Claude Code reads YAML 1.2: `yes` is the pattern "yes" (P3: it matches nothing), not a boolean.
        self.assertEqual(ids("paths: yes\n"), ["P3"])
        self.assertEqual(ids('paths: "123"\n'), ["P3"])
        self.assertEqual(ids("paths: '0o17'\n"), ["P3"])
        self.assertEqual(ids('paths:\n  - "5"\n  - on\n'), ["P3", "P3"])

    def test_numbers_only_yaml_1_2_reads_as_numbers(self):
        # PyYAML's YAML 1.1 loader keeps these as strings; Claude Code's reader does not.
        for value in ("1e3", "0o17", "0x1F", ".5", "-.inf"):
            with self.subTest(value=value):
                self.assertEqual(ids(f"paths: {value}\n"), ["P2"])

    def test_another_key_that_a_typed_loader_cannot_convert_changes_nothing(self):
        self.assertEqual(ids("paths: 123\nversion: 2026-02-30\n"), ["P2"])


class PathsItemTest(unittest.TestCase):
    """P5: an item that is not a string is ignored; the other patterns work."""

    def test_item_that_is_not_a_string(self):
        found, messages, _ = lint(rule('paths:\n  - 5\n  - "src/**/*.ts"\n'))
        self.assertEqual(found, [(RULE, 2, "P5")])
        self.assertIn("an item that is not a string", messages[0])
        found, messages, _ = lint(rule('paths: [5, {a: b}, "lib/**"]\n'))
        self.assertEqual(found, [(RULE, 2, "P3"), (RULE, 2, "P5")])
        self.assertIn("2 items", messages[1])

    def test_level_is_its_own(self):
        self.assertEqual(ids('paths:\n  - 5\n  - "src/**"\n', '[rules.P5]\nlevel = "off"\n'), [])
        self.assertEqual(ids("paths: 5\n", '[rules.P5]\nlevel = "off"\n'), ["P2"])


class PathsMatchTest(unittest.TestCase):
    """P3: a pattern that matches no tracked file never loads the rule."""

    def matching(self, pattern: str, **files: str) -> bool:
        found, _, _ = lint(rule(f"paths:\n  - '{pattern}'\n", **files))
        self.assertLessEqual({f[2] for f in found}, {"P3"})
        return not found

    def test_patterns_read_as_claude_code_reads_them(self):
        for pattern, expected in (
            ("src/**/*.ts", True), ("src/**/*", True), ("**/*.ts", True),
            ("*.ts", True),            # no slash: at any depth
            ("/*.ts", False),          # anchored: the base directory only
            ("/README.md", True),
            ("src/*.ts", False),       # `*` stays in one directory
            ("src", True), ("src/", True), ("api", True),   # a directory matches what it holds
            ("README.md/", False), ("a.ts/", False),        # a trailing slash names a directory
            ("SRC/**", True), ("**/*.TS", True), ("readme.md", True),   # letter case is ignored
            ("s**ts", False), ("src/a**/*.ts", True),       # `**` beside other characters is a `*`
            ("**", True), ("src/**", True), ("**/api/**", True), ("lib/**", False),
            ("./src/**/*.ts", False),
            ("src/**/*.{js,ts}", True), ("src/**/*.{js,py}", False), ("{lib,src}/{api,web}/*.{js,ts}", True),
            ("src/ap[hi]/*.ts", True), ("src/ap[!i]/*.ts", False), ("src/api/[a.ts", False), ("src[", False),
            ("src/api/?.ts", True), ("src/api/??.ts", False),
            ("lib/**/*.ts", False), ("nowhere/**", False),
        ):
            with self.subTest(pattern=pattern):
                self.assertEqual(self.matching(pattern), expected)

    def test_untracked_file_does_not_count(self):
        root = make_repo(rule('paths:\n  - "gen/**"\n'))
        (root / "gen").mkdir()
        (root / "gen/out.ts").write_text("x\n")
        doc = json.loads(run_new(root, "--format", "json").stdout)
        self.assertEqual([f["rule"] for f in doc["findings"]], ["P3"])

    def test_each_dead_pattern_is_reported_with_its_text(self):
        found, messages, _ = lint(rule('paths:\n  - "lib/**"\n  - "src/**"\n  - "old/*.go"\n'))
        self.assertEqual(found, [(RULE, 2, "P3")] * 2)
        self.assertEqual([("'lib/**'" in m, "'old/*.go'" in m) for m in messages], [(True, False), (False, True)])

    def test_patterns_are_relative_to_the_directory_holding_dot_claude(self):
        nested = "pkg/.claude/rules/api.md"
        files = {nested: '---\npaths:\n  - "src/*.ts"\n---\n\n# API\n', "pkg/src/a.ts": "x\n"}
        self.assertEqual(lint(files)[0], [])
        files = {nested: '---\npaths:\n  - "src/*.ts"\n---\n\n# API\n', "src/a.ts": "x\n", "pkg/b.ts": "x\n"}
        found, messages, _ = lint(files)
        self.assertEqual(found, [(nested, 2, "P3")])
        self.assertIn("under pkg/", messages[0])

    def test_syntax_this_tool_does_not_read_is_not_reported(self):
        for pattern in ("!src/**", "src/@(a|b)/*.ts", "lib/!(x)/*.ts", "[[:alpha:]]ib/**", "lib/[a--b].ts"):
            with self.subTest(pattern=pattern):
                self.assertTrue(self.matching(pattern))

    def test_brace_expansion_over_the_budget_is_used_unexpanded(self):
        groups = "".join("{a,b}" for _ in range(11))   # 2048 patterns
        self.assertFalse(self.matching(f"src/{groups}/*.ts"))

    def test_expansion_budget_is_shared_by_the_list(self):
        groups = "".join("{a,b}" for _ in range(9))    # 512 patterns each; the second passes 1,000
        wide = f"src/{{api,{groups}}}/*.ts"
        found, messages, _ = lint(rule(f"paths:\n  - '{wide}'\n  - '{wide}'\n  - 'src/{{api,x}}/*.ts'\n"))
        self.assertEqual(found, [(RULE, 2, "P3")])
        found, _, _ = lint(rule(f"paths:\n  - '{wide}'\n  - 'src/{{api,x}}/*.ts'\n  - '{wide}'\n"))
        self.assertEqual(found, [(RULE, 2, "P3")])

    def test_off_p3_keeps_p5(self):
        config = '[rules.P3]\nlevel = "off"\n'
        self.assertEqual(ids('paths:\n  - 5\n  - "lib/**"\n', config), ["P5"])


class PathsKeyTest(unittest.TestCase):
    """P4: Claude Code reads only `paths`; a key that looks like it scopes nothing."""

    def test_lookalike_key_without_paths(self):
        for key in ("globs", "glob", "path", "Paths", "PATHS"):
            with self.subTest(key=key):
                found, messages, _ = lint(rule(f'description: d\n{key}:\n  - "src/**/*.ts"\n'))
                self.assertEqual(found, [(RULE, 3, "P4")])
                self.assertIn(repr(key), messages[0])
                self.assertIn("loads the rule without a path scope", messages[0])

    def test_lookalike_key_beside_paths_and_other_keys_are_fine(self):
        self.assertEqual(ids('globs: "src/**"\npaths: "src/**"\n'), [])
        self.assertEqual(ids("description: d\nalwaysApply: true\n"), [])

    def test_keys_are_configuration(self):
        config = '[rules.P4]\nkeys = ["applyTo"]\n'
        self.assertEqual(ids('applyTo: "src/**"\n', config), ["P4"])
        self.assertEqual(ids('globs: "src/**"\n', config), [])
        self.assertEqual(ids('Paths: "src/**"\n', '[rules.P4]\nkeys = []\n'), ["P4"])

    def test_unknown_key_in_the_rule_table_fails(self):
        files = rule("paths: src\n")
        files[".agentfile-lint.toml"] = '[rules.P4]\nkey = ["x"]\n'
        r = run_new(make_repo(files))
        self.assertEqual(r.returncode, 2)
        self.assertIn("rules.P4", r.stderr)


class IntegrationTest(unittest.TestCase):
    def test_per_line_directive_cannot_name_a_p_rule(self):
        files = rule("paths: lib\n")
        files[RULE] += "\n<!-- agentfile-lint-disable-next-line P3 -- generated files -->\ntext\n"
        r = run_new(make_repo(files))
        self.assertEqual(r.returncode, 1)
        self.assertIn("P3", r.stdout)
        self.assertIn("disable", r.stdout)

    def test_alias_and_level_work(self):
        self.assertEqual(ids("paths: 5\n", '[rules.rule-paths-type]\nlevel = "off"\n'), [])
        found, _, r = lint(rule("paths: 5\n"), '[rules.P2]\nlevel = "error"\n')
        self.assertEqual((found, r.returncode), ([(RULE, 2, "P2")], 1))

    def test_symlinked_rule_file_is_read_through_the_link(self):
        root = make_repo({"guides/api.md": '---\npaths:\n  - "lib/**"\n---\n\n# API\n', "src/a.ts": "x\n"},
                         symlinks={RULE: "../../guides/api.md"})
        doc = json.loads(run_new(root, "--format", "json").stdout)
        self.assertEqual([(f["file"], f["rule"]) for f in doc["findings"]], [(RULE, "P3")])


if __name__ == "__main__":
    unittest.main()
