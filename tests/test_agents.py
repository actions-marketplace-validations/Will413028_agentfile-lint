"""Subagent files (A1 to A7; docs/rules.md "A1 to A7 subagent files"), measured on Claude Code 2.1.323 (A6: 2.1.325)."""
import json
import unittest

from helpers import make_repo, run_new

GOOD = "---\nname: reviewer\ndescription: Use to review a change.\n---\n\nYou review code.\n"
AGENT = ".claude/agents/reviewer.md"


def lint(files: dict[str, str], config: str = ""):
    files = dict(files)
    if config:
        files[".agentfile-lint.toml"] = config
    r = run_new(make_repo(files), "--format", "json")
    if r.returncode == 2:
        raise AssertionError(r.stderr)
    doc = json.loads(r.stdout)
    return [(f["file"], f["line"], f["rule"]) for f in doc["findings"]], [f["message"] for f in doc["findings"]], r


def agent(frontmatter: str) -> dict[str, str]:
    return {AGENT: f"---\n{frontmatter}---\n\nYou help.\n"}


def ids(files: dict[str, str], config: str = "") -> list[str]:
    return [rule for _, _, rule in lint(files, config)[0]]


class LoadedTest(unittest.TestCase):
    def test_forms_claude_code_loads_report_nothing(self):
        for frontmatter in (
            "name: reviewer\ndescription: Use to review a change.\ntools: Read, Grep\nmodel: sonnet\n",
            "name: Code Reviewer\ndescription: Use to review.\n",            # spaces and capitals are fine
            "name: REVIEWER\ndescription: Use to review.\n",
            "name: reviewer\ndescription: Use this agent when asked. Examples: user: hello\n",   # the second parse reads it
            'name: "123"\ndescription: |\n  Use to review.\n  Second line.\n',
        ):
            with self.subTest(frontmatter=frontmatter):
                self.assertEqual(ids(agent(frontmatter)), [])

    def test_subdirectories_are_subagents_too_and_other_files_are_not(self):
        files = {".claude/agents/team/deep/qa.md": "# no frontmatter\n", ".claude/agents/notes.txt": "x\n",
                 "docs/agents/guide.md": "# guide\n", "pkg/.claude/agents/dev.md": "---\nname: dev\n---\n"}
        self.assertEqual(lint(files)[0], [(".claude/agents/team/deep/qa.md", None, "A2"), ("pkg/.claude/agents/dev.md", 1, "A4")])

    def test_findings_are_warnings(self):
        self.assertEqual(lint({AGENT: "# plain\n"})[2].returncode, 0)


class NotLoadedTest(unittest.TestCase):
    def test_a1_yaml_that_the_second_parse_cannot_read(self):
        text = ("---\nname: dev\ndescription: Use this agent to implement a plan or\n\n  <example>\n"
                "  Context: there is a plan\n  </example>\n---\n\nYou implement.\n")
        found, messages, _ = lint({AGENT: text})
        self.assertEqual([(f[0], f[2]) for f in found], [(AGENT, "A1")])
        self.assertIn("does not load the subagent", messages[0])
        self.assertEqual(ids({AGENT: "---\nname: dev\ndescription: d\n"}), ["A1"])   # no closing line
        self.assertEqual(ids({AGENT: "---\n- a\n- b\n---\n"}), ["A1"])                # not a mapping

    def test_a2_no_frontmatter_except_ignored_files(self):
        files = {AGENT: "# Reviewer\n\nYou review.\n", ".claude/agents/README.md": "# About these agents\n",
                 ".claude/agents/team/README.md": "# Team\n"}
        self.assertEqual(lint(files)[0], [(AGENT, None, "A2")])
        self.assertEqual(ids(files, '[rules.A2]\nignore = []\n'), ["A2"] * 3)
        self.assertEqual(ids(files, '[rules.A2]\nignore = ["**/*.md"]\n'), [])

    def test_readme_with_frontmatter_is_a_subagent(self):
        self.assertEqual(ids({".claude/agents/README.md": "---\nname: readme\n---\n"}), ["A4"])

    def test_a3_and_a4_missing_empty_or_not_a_string(self):
        for frontmatter, expected in (
            ("description: Use to review.\n", [(1, "A3")]),
            ("name: reviewer\n", [(1, "A4")]),
            ('name: reviewer\ndescription: ""\n', [(3, "A4")]),
            ("name: reviewer\ndescription: 123\n", [(3, "A4")]),
            ("name: 123\ndescription: Use to review.\n", [(2, "A3")]),
            ("name:\ndescription: [a, b]\n", [(2, "A3"), (3, "A4")]),
            ("", [(1, "A3"), (1, "A4")]),
            ("name: -reviewer\ndescription: d\n", [(2, "A3")]),
            ('name: "team:reviewer"\ndescription: d\n', [(2, "A3")]),
            ("name: " + "n" * 257 + "\ndescription: d\n", [(2, "A3")]),
            ("name: " + "n" * 256 + "\ndescription: d\n", []),
        ):
            with self.subTest(frontmatter=frontmatter):
                self.assertEqual([(line, rule) for _, line, rule in lint(agent(frontmatter))[0]], expected)

    def test_a5_same_name_in_one_agents_directory(self):
        files = {".claude/agents/a.md": GOOD, ".claude/agents/team/b.md": GOOD, ".claude/agents/c.md": GOOD.replace("reviewer", "other"),
                 "pkg/.claude/agents/a.md": GOOD}
        found, messages, _ = lint(files)
        self.assertEqual(found, [(".claude/agents/team/b.md", 2, "A5")])
        self.assertIn("also the name of .claude/agents/a.md", messages[0])

    def test_a5_does_not_count_a_file_that_is_not_loaded(self):
        files = {".claude/agents/a.md": "---\nname: reviewer\n---\n", ".claude/agents/b.md": GOOD}
        self.assertEqual(ids(files), ["A4"])


class FamilyTest(unittest.TestCase):
    def test_agents_globs_are_configuration(self):
        files = {"tools/agents/helper.md": "# no frontmatter\n", AGENT: "# no frontmatter\n"}
        self.assertEqual(lint(files, '[discover]\nextend_agents_globs = ["tools/agents/*.md"]\n')[0],
                         [(AGENT, None, "A2"), ("tools/agents/helper.md", None, "A2")])
        self.assertEqual(lint(files, '[discover]\nagents_globs = []\n')[0], [])

    def test_same_name_outside_dot_claude_is_grouped_by_directory(self):
        config = '[discover]\nagents_globs = ["tools/**/*.md"]\n'
        files = {"tools/a/x.md": GOOD, "tools/a/y.md": GOOD, "tools/b/x.md": GOOD}
        self.assertEqual(lint(files, config)[0], [("tools/a/y.md", 2, "A5")])

    def test_instruction_and_skill_rules_do_not_run_on_subagent_files(self):
        long = GOOD + "line\n" * 600 + "[x](gone.md)\n"
        self.assertEqual(ids({AGENT: long}, 'extends = ["preset:strict"]\n'), [])

    def test_levels_aliases_and_no_directive(self):
        self.assertEqual(ids({AGENT: "# plain\n"}, '[rules.agent-frontmatter]\nlevel = "off"\n'), [])
        self.assertEqual(lint(agent("name: reviewer\n"), '[rules.A4]\nlevel = "error"\n')[2].returncode, 1)
        files = {"AGENTS.md": "<!-- agentfile-lint-disable-next-line A4 -- later -->\ntext\n"}
        r = run_new(make_repo(files))
        self.assertEqual(r.returncode, 1)
        self.assertIn("disable", r.stdout)



class ToolsTest(unittest.TestCase):
    """A6: an entry of `tools` Claude Code does not recognise is dropped without a word; with no
    entry left the subagent is refused (measured on 2.1.325)."""

    HEAD = "name: reviewer\ndescription: Use to review.\n"

    def found(self, tools: str, config: str = ""):
        where, messages, _ = lint(agent(self.HEAD + tools), config)
        return [(line, rule) for _, line, rule in where], messages

    def test_forms_claude_code_resolves_report_nothing(self):
        for tools in ("tools: Read, Grep, Glob, Bash\n", "tools: [Read, Bash]\n", "tools:\n  - Read\n  - Bash(git status)\n",
                      "tools: Agent(worker, researcher), Read(./docs), Task\n", 'tools: "*"\n', "tools: mcp__github__*, mcp__x__y, Read\n",
                      "tools:\n", "tools: null\n", "tools: ~\n", "tools: true\n", "tools: 5\n", "tools: Read Bash\n",
                      'tools:\n  - "Read, Bash"\n', "tools: (x), Read\n", "tools: [Read, [Bash]]\n", "model: sonnet\n",
                      "tools: [Agent(worker, LS, tester), Read]\n", "tools: Bash(git log, LS, x), Read\n",
                      "tools:\n  - Read\n  - null\n  - true\n", "tools: ['Read', \"Bash\"]\n"):
            with self.subTest(tools=tools):
                self.assertEqual(self.found(tools)[0], [])

    def test_unknown_names_are_reported_once_on_the_tools_line(self):
        where, messages = self.found("tools: Read, LS, MultiEdit, LS, Bash\n")
        self.assertEqual(where, [(4, "A6")])
        self.assertIn("`tools` names `LS`, `MultiEdit`, which", messages[0])
        self.assertIn("drops the entry without a warning", messages[0])
        where, messages = self.found("model: opus\ntools:\n  - Read\n  - Context7(x)\n")
        self.assertEqual(where, [(5, "A6")])
        self.assertIn("`Context7`,", messages[0])

    def test_no_entry_left_is_a_subagent_that_does_not_start(self):
        for tools in ("tools: read, bash\n", "tools: [LS]\n", "tools:\n  - Context7\n"):
            with self.subTest(tools=tools):
                where, messages = self.found(tools)
                self.assertEqual([rule for _, rule in where], ["A6"])
                self.assertIn("refuses to start the subagent", messages[0])
        # A subagent Claude Code does not load (A4) has no A6.
        self.assertEqual(ids(agent("name: reviewer\ntools: LS\n")), ["A4"])
        self.assertEqual(self.found('tools:\n  - "Read, LS"\n  - 5\n')[0], [(4, "A6")])
        # An entry that resolves is left: `*`, a quoted name after the second parse, a specifier in a flow list.
        self.assertIn("drops the entry", self.found('tools: "*, LS"\n')[1][0])
        self.assertIn("drops the entry", self.found("tools: [Bash(git log, status, x), LS]\n")[1][0])
        where, messages, _ = lint(agent("name: reviewer\ndescription: Use when asked. Examples: user: hello\ntools: [\"Read\", LS]\n"))
        self.assertIn("drops the entry", messages[0])
        # An MCP entry or `*` may resolve: the subagent starts.
        self.assertIn("drops the entry", self.found("tools: LS, mcp__github__*\n")[1][0])

    def test_a_flow_list_the_second_parse_turns_into_a_string_is_read(self):
        head = "name: reviewer\ndescription: Use when asked. Examples: user: hello\n"
        self.assertEqual(ids(agent(head + "tools: [Read, Grep, Glob]\n")), [])
        self.assertEqual(ids(agent(head + "tools: [Read, LS]\n")), ["A6"])

    def test_the_known_names_are_configuration(self):
        self.assertEqual(self.found("tools: Read, MyTool\n", '[shared.agents]\ntools = ["Read", "MyTool"]\n')[0], [])
        self.assertEqual(self.found("tools: Read, MyTool, Bash\n", '[shared.agents]\nextend_tools = ["MyTool"]\n')[0], [])
        self.assertIn("`Mytool`,", self.found("tools: Read Mytool\n", '[shared.agents]\nextend_tools = ["MyTool"]\n')[1][0])
        self.assertEqual(self.found("tools: Read, Bash\n", '[shared.agents]\ntools = ["Read"]\n')[0], [(4, "A6")])
        self.assertEqual(self.found("tools: LS\n", '[rules.A6]\nlevel = "off"\n')[0], [])

    def test_a_wrong_tools_setting_is_a_config_error(self):
        files = dict(agent(self.HEAD))
        files[".agentfile-lint.toml"] = '[shared.agents]\ntools = "Read"\n'
        r = run_new(make_repo(files), "--format", "json")
        self.assertEqual(r.returncode, 2)
        self.assertIn("shared.agents.tools", r.stderr)


class DisallowedToolsTest(unittest.TestCase):
    """A7: an unknown name in `disallowedTools` denies nothing (measured on 2.1.325:
    `disallowedTools: bash, write` leaves Bash and Write; `Bash, Write` removes them)."""

    HEAD = "name: reviewer\ndescription: Use to review.\n"

    def test_names_claude_code_knows_report_nothing(self):
        for field in ("disallowedTools: Bash, Write\n", "disallowedTools: Bash(git push *), mcp__github__*\n",
                      "disallowedTools:\n  - Edit\n  - Agent\n", "disallowedTools:\n", "disallowedTools: null\n"):
            with self.subTest(field=field):
                self.assertEqual(ids(agent(self.HEAD + field)), [])

    def test_unknown_names_are_one_finding_on_the_line(self):
        where, messages, _ = lint(agent(self.HEAD + "tools: Read, Bash\ndisallowedTools: bash, Write, write\n"))
        self.assertEqual([(line, rule) for _, line, rule in where], [(5, "A7")])
        self.assertIn("`disallowedTools` names `bash`, `write`, which", messages[0])
        self.assertIn("denies nothing", messages[0])

    def test_it_is_apart_from_a6_and_uses_its_names(self):
        both = agent(self.HEAD + "tools: read\ndisallowedTools: bash\n")
        self.assertEqual(ids(both), ["A6", "A7"])
        self.assertEqual(ids(both, '[rules.A6]\nlevel = "off"\n'), ["A7"])
        self.assertEqual(ids(both, '[rules.A7]\nlevel = "off"\n'), ["A6"])
        self.assertEqual(ids(agent(self.HEAD + "disallowedTools: MyTool\n"), '[shared.agents]\nextend_tools = ["MyTool"]\n'), [])
        self.assertEqual(ids(agent("name: reviewer\ndisallowedTools: bash\n")), ["A4"])     # not loaded: no A7


if __name__ == "__main__":
    unittest.main()
