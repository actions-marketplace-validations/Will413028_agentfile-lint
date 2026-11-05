"""Hooks in Claude Code settings files (H1 to H6; docs/rules.md "H1 to H6 hooks").

Each case's consequence was measured with `claude doctor` on Claude Code 2.1.318 (2026-11-06).
"""
import json
import unittest
from unittest import mock

from helpers import make_repo, run_new

from agentfile_lint.rules import hooks as hooks_rule, mcp as mcp_rule

SETTINGS = ".claude/settings.json"


def lint(files: dict[str, str | bytes], config: str | None = None, *args: str):
    """Findings as (path, line, rule) triples from a JSON run, plus the parsed document."""
    files = dict(files)
    files.setdefault("AGENTS.md", "ok\n")
    if config is not None:
        files[".agentfile-lint.toml"] = config
    root = make_repo(files)
    r = run_new(root, "--format", "json", "--today", "2026-11-06", *args)
    if r.returncode == 2:
        raise AssertionError(r.stderr)
    doc = json.loads(r.stdout)
    return [(f["file"], f["line"], f["rule"]) for f in doc["findings"]], doc


def hooks(value) -> str:
    return json.dumps({"hooks": value})


def handler(event: str = "Stop", **fields) -> str:
    return hooks({event: [{"matcher": "", "hooks": [fields]}]})


def rules_of(text: str | bytes, path: str = SETTINGS) -> list[str]:
    return sorted({rule for _, _, rule in lint({path: text})[0]})


def messages(text: str | bytes, path: str = SETTINGS) -> list[str]:
    return [f["message"] for f in lint({path: text})[1]["findings"]]


class ValidSettingsTest(unittest.TestCase):
    def test_documented_examples_report_nothing(self):
        # hooks reference, "How a hook resolves" and the five handler types.
        text = hooks({
            "PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "if": "Bash(rm *)", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/block-rm.sh", "args": []},
            ]}],
            "PostToolUse": [{"matcher": "Write|Edit", "hooks": [
                {"type": "mcp_tool", "server": "my_server", "tool": "security_scan", "input": {"file_path": "${tool_input.file_path}"}},
                {"type": "http", "url": "http://localhost:8080/hooks/pre-tool-use"},
            ]}],
            "Stop": [{"hooks": [{"type": "prompt", "prompt": "Check $ARGUMENTS"}, {"type": "agent", "prompt": "Verify"}]}],
        })
        self.assertEqual(rules_of(text), [])

    def test_settings_without_hooks_and_a_leading_bom_report_nothing(self):
        self.assertEqual(rules_of('{"permissions": {"allow": []}}'), [])
        # Claude Code reads a settings file that starts with a UTF-8 byte order mark.
        self.assertEqual(rules_of(b"\xef\xbb\xbf" + handler(type="command", command="x").encode()), [])

    def test_every_documented_event_is_known(self):
        events = (
            "SessionStart Setup UserPromptSubmit UserPromptExpansion PreToolUse PermissionRequest PermissionDenied "
            "PostToolUse PostToolUseFailure PostToolBatch Notification MessageDisplay SubagentStart SubagentStop "
            "TaskCreated TaskCompleted Stop StopFailure TeammateIdle InstructionsLoaded ConfigChange CwdChanged "
            "DirectoryAdded FileChanged WorktreeCreate WorktreeRemove PreCompact PostCompact PreModelSwitch "
            "PostModelSwitch Elicitation ElicitationResult SessionEnd"
        ).split()
        self.assertEqual(len(events), 33)
        text = hooks({e: [{"hooks": [{"type": "command", "command": "true"}]}] for e in events})
        self.assertEqual(rules_of(text), [])

    def test_local_settings_and_nested_project_directories_are_checked(self):
        # Claude Code reads .claude/settings.json from the directory a session starts in.
        # settings.local.json is usually git-ignored, so --no-git is what reaches it.
        bad = handler(type="shell", command="x")
        found, _ = lint({".claude/settings.local.json": bad, "compiler/.claude/settings.json": bad}, None, "--no-git")
        self.assertEqual(sorted(p for p, _, _ in found), [".claude/settings.local.json", "compiler/.claude/settings.json"])

    def test_other_json_files_are_not_checked(self):
        self.assertEqual(lint({"package.json": "{", "claude/settings.json": "{"})[0], [])


class JsonTest(unittest.TestCase):
    def test_invalid_json_is_reported_at_its_line(self):
        found, doc = lint({SETTINGS: '{\n  "hooks": {\n    "Stop": [}\n}\n'})
        self.assertEqual(found, [(SETTINGS, 3, "H1")])
        self.assertEqual(doc["findings"][0]["level"], "warning")
        self.assertIn("not valid JSON", doc["findings"][0]["message"])

    def test_json_that_javascript_rejects_is_invalid(self):
        for text in ('{"hooks": {},}', '{"hooks": {}} // c', '{"timeout": NaN}', '{"a": Infinity}'):
            with self.subTest(text=text):
                self.assertEqual(rules_of(text), ["H1"])

    def test_an_empty_or_blank_file_reports_nothing(self):
        # Claude Code reads an empty settings file as no settings.
        for text in ("", "  \n"):
            with self.subTest(text=text):
                self.assertEqual(rules_of(text), [])

    def test_a_top_level_value_other_than_an_object(self):
        self.assertEqual(rules_of("[1]"), ["H1"])
        self.assertIn("not an object", messages("[1]")[0])

    def test_too_deep_to_read_is_reported_as_not_checked_not_as_invalid(self):
        # Python's parser gives up at a depth that depends on its version; JSON.parse may read the file.
        with mock.patch("json.loads", side_effect=RecursionError):
            for module, rule in ((hooks_rule, "H1"), (mcp_rule, "M1")):
                with self.subTest(rule):
                    (f,) = module.check("f.json", "{}", {}, {})
                    self.assertEqual((f.rule, f.line), (rule, 0))
                    self.assertIn("not checked", f.message)
                    self.assertNotIn("not valid JSON", f.message)
                    self.assertNotIn("Claude Code", f.message)

    def test_integers_python_refuses_to_convert_do_not_crash(self):
        # More than 4300 digits: JSON.parse reads it as a number; the rest of the file is still checked.
        text = '{"x": ' + "9" * 5000 + ', "hooks": {"Stop": [{"hooks": [{"type": "shell", "command": "x"}]}]}}'
        self.assertEqual(rules_of(text), ["H4"])


class EventTest(unittest.TestCase):
    def test_unknown_event_name(self):
        text = hooks({"NotAnEvent": [{"hooks": [{"type": "command", "command": "x"}]}], "preToolUse": []})
        self.assertEqual(rules_of(text), ["H2"])
        self.assertEqual(len(messages(text)), 2)
        self.assertIn("hooks.NotAnEvent", messages(text)[0])

    def test_an_unknown_event_is_not_checked_further(self):
        self.assertEqual(rules_of(hooks({"NotAnEvent": {"x": 1}})), ["H2"])


class ShapeTest(unittest.TestCase):
    def test_each_level_must_have_its_documented_shape(self):
        cases = {
            "hooks is an array": hooks([]),
            "hooks is null": hooks(None),
            "event value is an object": hooks({"Stop": {"hooks": []}}),
            "matcher group is a string": hooks({"Stop": ["x"]}),
            "group has no hooks": hooks({"Stop": [{"matcher": ""}]}),
            "group hooks is an object": hooks({"Stop": [{"hooks": {}}]}),
            "matcher is a number": hooks({"Stop": [{"matcher": 5, "hooks": []}]}),
            "handler is a string": hooks({"Stop": [{"hooks": ["echo hi"]}]}),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertEqual(rules_of(text), ["H3"])

    def test_the_message_names_the_json_path(self):
        self.assertIn("hooks.Stop.0.hooks.1", messages(hooks({"Stop": [{"hooks": [{"type": "command", "command": "x"}, 3]}]}))[0])

    def test_pre_tool_use_failures_name_the_wider_consequence(self):
        # doctor: "nothing it sits in is applied" for PreToolUse and PermissionRequest; elsewhere the entry goes.
        self.assertIn("permissions", messages(hooks({"PreToolUse": [{"matcher": 5, "hooks": []}]}))[0])
        self.assertIn("permissions", messages(handler("PermissionRequest", type="http"))[0])
        self.assertNotIn("permissions", messages(hooks({"Stop": [{"matcher": 5, "hooks": []}]}))[0])


class HandlerTest(unittest.TestCase):
    def test_type_missing_unknown_or_not_a_string(self):
        for fields in ({"command": "x"}, {"type": "shell", "command": "x"}, {"type": 1, "command": "x"}):
            with self.subTest(fields):
                self.assertEqual(rules_of(handler(**fields)), ["H4"])

    def test_required_fields_per_type(self):
        cases = [
            {"type": "command"}, {"type": "command", "command": ["x"]},
            {"type": "http"}, {"type": "mcp_tool", "server": "a"}, {"type": "mcp_tool", "tool": "t"},
            {"type": "prompt"}, {"type": "agent", "prompt": 5},
        ]
        for fields in cases:
            with self.subTest(fields):
                self.assertEqual(rules_of(handler(**fields)), ["H5"])

    def test_a_missing_field_names_the_field(self):
        self.assertIn("tool", messages(handler(type="mcp_tool", server="a"))[0])

    def test_empty_command(self):
        for command in ("", "   "):
            with self.subTest(command=command):
                self.assertEqual(rules_of(handler(type="command", command=command)), ["H6"])

    def test_empty_strings_in_other_required_fields_are_not_reported(self):
        # Claude Code loads an empty prompt, server or tool; it ignores an http hook whose url it cannot
        # parse (an empty one included), but URL syntax is not a required-field check (docs/rules.md).
        for fields in ({"type": "prompt", "prompt": ""}, {"type": "mcp_tool", "server": "", "tool": ""},
                       {"type": "http", "url": ""}):
            with self.subTest(fields):
                self.assertEqual(rules_of(handler(**fields)), [])

    def test_optional_field_types_are_not_checked(self):
        # Claude Code drops such an entry, but optional fields are outside the documented checks (docs/rules.md).
        self.assertEqual(rules_of(handler(type="command", command="x", timeout="5")), [])


class FamilyTest(unittest.TestCase):
    def test_hooks_globs_replace_and_extend(self):
        files = {SETTINGS: "{", "a/hooks.json": "{"}
        self.assertEqual({p for p, _, _ in lint(files, '[discover]\nhooks_globs = ["a/hooks.json"]\n')[0]}, {"a/hooks.json"})
        both = '[discover]\nextend_hooks_globs = ["a/hooks.json"]\n'
        self.assertEqual({p for p, _, _ in lint(files, both)[0]}, {SETTINGS, "a/hooks.json"})

    def test_empty_hooks_globs_turns_the_family_off(self):
        self.assertEqual(lint({SETTINGS: "{"}, "[discover]\nhooks_globs = []\n")[0], [])

    def test_h_rules_never_run_on_instruction_files(self):
        found, _ = lint({"AGENTS.md": "{ not json\n"}, '[discover]\nextend_globs = [".claude/settings.json"]\n')
        self.assertEqual(found, [])

    def test_r_rules_never_run_on_settings_files(self):
        long = json.dumps({"permissions": {"allow": ["x" * 2000]}})
        self.assertEqual(rules_of(long), [])

    def test_a_file_named_on_the_command_line_triggers_the_run(self):
        root = make_repo({"AGENTS.md": "ok\n", SETTINGS: "{"})
        r = run_new(root, "--format", "json", SETTINGS)
        self.assertEqual([f["rule"] for f in json.loads(r.stdout)["findings"]], ["H1"])

    def test_level_and_overrides_apply(self):
        cfg = '[rules.H1]\nlevel = "error"\n'
        found, doc = lint({SETTINGS: "{"}, cfg)
        self.assertEqual(doc["findings"][0]["level"], "error")
        off = '[[overrides]]\npaths = [".claude/settings.json"]\nrules = { settings-json = "off" }\nreason = "generated"\n'
        self.assertEqual(lint({SETTINGS: "{"}, off)[0], [])

    def test_a_directive_naming_an_h_or_m_id_names_the_family(self):
        text = "<!-- agentfile-lint-disable-next-line H1 -- x -->\nok\n<!-- agentfile-lint-disable-next-line M2 -- x -->\nok\n"
        found, doc = lint({"AGENTS.md": text})
        msgs = [f["message"] for f in doc["findings"]]
        self.assertEqual([r for _, _, r in found], ["disable", "disable"])
        self.assertIn("H1 checks Claude Code settings files", msgs[0])
        self.assertIn("M2 checks .mcp.json files", msgs[1])

    def test_non_utf8_settings_file_is_e0(self):
        self.assertEqual(rules_of(b'{"a": "\xff"}'), ["E0"])

    def test_effective_config_shows_the_keys(self):
        root = make_repo({"AGENTS.md": "ok\n"})
        doc = json.loads(run_new(root, "config", "--format", "json").stdout)
        self.assertEqual(doc["discover"]["hooks_globs"], ["**/.claude/settings.json", "**/.claude/settings.local.json"])
        self.assertEqual(doc["discover"]["extend_hooks_globs"], [])
        self.assertEqual([doc["rules"][f"H{i}"] for i in range(1, 7)], [{"level": "warn"}] * 6)


if __name__ == "__main__":
    unittest.main()
