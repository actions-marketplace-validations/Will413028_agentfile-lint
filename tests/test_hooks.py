"""Hooks in Claude Code settings files (H1 to H9; docs/rules.md "H1 to H9 hooks").

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


class CommandPathTest(unittest.TestCase):
    """H7 and H8: the script a command hook names under the project directory (measured on 2.1.323:
    a missing script and a script without execute permission run directly do not run, silently)."""

    SCRIPT = ".claude/hooks/check.sh"

    def run_hooks(self, commands: list[str], files: dict[str, str] | None = None, executable: tuple[str, ...] = (),
                  config: str | None = None, settings: str = SETTINGS):
        tree = {settings: hooks({"Stop": [{"hooks": [c if isinstance(c, dict) else {"type": "command", "command": c} for c in commands]}]}),
                "AGENTS.md": "ok\n", **(files or {})}
        if config is not None:
            tree[".agentfile-lint.toml"] = config
        root = make_repo(tree)
        for name in executable:
            (root / name).chmod(0o755)
        r = run_new(root, "--format", "json")
        if r.returncode == 2:
            raise AssertionError(r.stderr)
        return [(f["rule"], f["message"]) for f in json.loads(r.stdout)["findings"]], root

    def test_tracked_executable_script_is_fine_in_every_spelling(self):
        commands = ['"$CLAUDE_PROJECT_DIR"/.claude/hooks/check.sh', "${CLAUDE_PROJECT_DIR}/.claude/hooks/check.sh --fast",
                    'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/check.sh"', 'FOO=1 exec "$CLAUDE_PROJECT_DIR"/.claude/hooks/check.sh']
        found, _ = self.run_hooks(commands, {self.SCRIPT: "#!/bin/sh\n"}, executable=(self.SCRIPT,))
        self.assertEqual(found, [])

    def test_exec_form_reads_the_program_and_the_script_in_args(self):
        """A hook with `args` runs without a shell (measured on 2.1.325): `command` is the program
        as written, and only `${CLAUDE_PROJECT_DIR}` is substituted, in `command` and in `args`."""
        def handler(command, *args):
            return {"type": "command", "command": command, "args": list(args)}
        here = "${CLAUDE_PROJECT_DIR}/.claude/hooks/"
        files = {self.SCRIPT: "#!/bin/sh\n", ".claude/hooks/plain.sh": "#!/bin/sh\n", "my hooks/check.sh": "#!/bin/sh\n"}
        fine = [handler(here + "check.sh", "--fast"), handler("bash", here + "plain.sh"),
                handler("${CLAUDE_PROJECT_DIR}/my hooks/check.sh"),
                # Code or another program's argument, not a script that is run.
                handler("sh", "-c", here + "gone.sh"), handler("grep", here + "gone.sh"), handler("bash", "run.sh", here + "gone.sh"),
                # Not substituted without a shell: no path under the project directory is named.
                handler("$CLAUDE_PROJECT_DIR/.claude/hooks/gone.sh"), handler("bash", "$CLAUDE_PROJECT_DIR/gone.sh"),
                # Words only a shell understands are not programs here.
                handler("source", here + "gone.sh"), handler("exec", "bash", here + "gone.sh"),
                # The whole `command` is the program: it is not split into words.
                handler("bash " + here + "gone.sh")]
        found, _ = self.run_hooks(fine, files, executable=(self.SCRIPT, "my hooks/check.sh"))
        self.assertEqual(found, [])
        found, _ = self.run_hooks([handler(here + "gone.sh"), handler("node", "--trace-warnings", here + "gone.js", "x"),
                                   handler(here + "plain.sh"), handler(here + "check.sh arg")], files, executable=(self.SCRIPT,))
        self.assertEqual([rule for rule, _ in found], ["H7", "H7", "H7", "H8"])
        self.assertIn("hooks.Stop.0.hooks.1.args.1 runs .claude/hooks/gone.js", found[1][1])
        self.assertIn("runs .claude/hooks/check.sh arg,", found[2][1])
        self.assertIn("hooks.Stop.0.hooks.2.command runs .claude/hooks/plain.sh directly", found[3][1])

    def test_exec_form_follows_wrapper_programs_and_shell_flags(self):
        """Measured on 2.1.325: `/usr/bin/env bash script` and `bash -e script` in exec form run the script."""
        def handler(command, *args):
            return {"type": "command", "command": command, "args": list(args)}
        here = "${CLAUDE_PROJECT_DIR}/.claude/hooks/"
        files = {".claude/hooks/python": "#!/bin/sh\n"}
        found, _ = self.run_hooks([handler("/usr/bin/env", "bash", here + "a.sh"), handler("env", "FOO=1", here + "b.sh"),
                                   handler("bash", "-e", here + "c.sh"), handler(here + "python", here + "d.py"),
                                   handler("nohup", "node", here + "e.js")], files, executable=(".claude/hooks/python",))
        self.assertEqual([rule for rule, _ in found], ["H7"] * 5)
        for i, key in enumerate(("args.1 runs .claude/hooks/a.sh", "args.1 runs .claude/hooks/b.sh", "args.1 runs .claude/hooks/c.sh",
                                 "args.0 runs .claude/hooks/d.py", "args.1 runs .claude/hooks/e.js")):
            self.assertIn(f"hooks.Stop.0.hooks.{i}.{key}", found[i][1])
        # An assignment is one only after `env`; `-c` and `-ec` still make the argument code.
        found, _ = self.run_hooks([handler("FOO=1", here + "gone.sh"), handler("bash", "-ec", here + "gone.sh"),
                                   # A second placeholder: not a path this reads.
                                   handler("bash", here + "${CLAUDE_PROJECT_DIR}/gone.sh")])
        self.assertEqual(found, [])
        # A file named like a wrapper under the project directory is the script, not `env`.
        found, _ = self.run_hooks([handler(here + "env", here + "data.txt")], {".claude/hooks/data.txt": "x\n"})
        self.assertEqual([message.split(",")[0] for _, message in found], ["hooks.Stop.0.hooks.0.command runs .claude/hooks/env"])

    def test_shell_flags_and_a_project_interpreter_in_shell_form(self):
        files = {".claude/hooks/python": "#!/bin/sh\n"}
        found, _ = self.run_hooks(['bash -e "$CLAUDE_PROJECT_DIR"/gone.sh', '"$CLAUDE_PROJECT_DIR"/.claude/hooks/python "$CLAUDE_PROJECT_DIR"/gone.py',
                                   'bash -ec "$CLAUDE_PROJECT_DIR"/x.sh', 'perl -e "$CLAUDE_PROJECT_DIR"/x.pl',
                                   'cat x | bash -es "$CLAUDE_PROJECT_DIR"/argument'],
                                  files, executable=(".claude/hooks/python",))
        self.assertEqual([message.split(",")[0] for _, message in found],
                         ["hooks.Stop.0.hooks.0.command runs gone.sh", "hooks.Stop.0.hooks.1.command runs gone.py"])

    def test_exec_form_does_not_use_the_configured_spellings_and_skips_bad_args(self):
        config = '[shared.hooks]\nproject_dir = ["$ROOT"]\n'
        found, _ = self.run_hooks([{"type": "command", "command": "$ROOT/gone.sh", "args": []},
                                   {"type": "command", "command": "${CLAUDE_PROJECT_DIR}/gone.sh", "args": "x"},
                                   {"type": "command", "command": "bash", "args": [1, "${CLAUDE_PROJECT_DIR}/gone.sh"]}], config=config)
        self.assertEqual(found, [])
        # With the default spellings too: a hook whose `args` is not a list of strings is not read.
        found, _ = self.run_hooks([{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/gone.sh", "args": "x"},
                                   {"type": "command", "command": "${CLAUDE_PROJECT_DIR}/gone.sh", "args": [1]},
                                   {"type": "command", "command": "${CLAUDE_PROJECT_DIR}/gone.sh", "args": None}])
        self.assertEqual(found, [])
        found, _ = self.run_hooks(["$ROOT/gone.sh", {"type": "command", "command": "${CLAUDE_PROJECT_DIR}/gone.sh", "args": []}], config=config)
        self.assertEqual([rule for rule, _ in found], ["H7", "H7"])

    def test_missing_script_is_h7_with_the_json_path(self):
        found, _ = self.run_hooks(["echo hi", '"$CLAUDE_PROJECT_DIR"/.claude/hooks/gone.sh'])
        self.assertEqual([rule for rule, _ in found], ["H7"])
        self.assertIn("hooks.Stop.0.hooks.1.command runs .claude/hooks/gone.sh", found[0][1])
        found, _ = self.run_hooks(['python3 -u "$CLAUDE_PROJECT_DIR/scripts/gone.py" --x', 'cd /tmp && "$CLAUDE_PROJECT_DIR"/gone.sh'])
        self.assertEqual([rule for rule, _ in found], ["H7", "H7"])

    def test_quoted_path_with_a_space_is_one_path(self):
        files = {"my hooks/check.sh": "#!/bin/sh\n"}
        found, _ = self.run_hooks(['"$CLAUDE_PROJECT_DIR/my hooks/check.sh"', '"$CLAUDE_PROJECT_DIR"/my\\ hooks/check.sh'],
                                  files, executable=("my hooks/check.sh",))
        self.assertEqual(found, [])
        found, _ = self.run_hooks(['"$CLAUDE_PROJECT_DIR/my hooks/gone.sh"'], files)
        self.assertIn("runs my hooks/gone.sh", found[0][1])

    def test_only_the_script_a_command_runs_is_judged(self):
        # Arguments, redirection targets, files the command creates, lists and a path it tests first.
        commands = ['echo x >> "$CLAUDE_PROJECT_DIR"/.claude/hook.log', 'mkdir -p "$CLAUDE_PROJECT_DIR"/tmp',
                    "PATH=$CLAUDE_PROJECT_DIR/bin:/usr/bin run-check", "lint --files=$CLAUDE_PROJECT_DIR/a.json,b.json",
                    'jq . "$CLAUDE_PROJECT_DIR"/gone.json', 'bash -c "$CLAUDE_PROJECT_DIR/gone.sh"', 'python3 -m "$CLAUDE_PROJECT_DIR/gone"',
                    '[ -x "$CLAUDE_PROJECT_DIR"/opt.sh ] && "$CLAUDE_PROJECT_DIR"/opt.sh', "# $CLAUDE_PROJECT_DIR/gone.sh",
                    'if [ -x "$CLAUDE_PROJECT_DIR/opt.sh" ]; then\n  "$CLAUDE_PROJECT_DIR/opt.sh"\nfi',
                    'if test -f "$CLAUDE_PROJECT_DIR"/o.py; then\n python3 "$CLAUDE_PROJECT_DIR"/o.py\nfi',
                    '! [ -x "$CLAUDE_PROJECT_DIR"/o.sh ] || "$CLAUDE_PROJECT_DIR"/o.sh',
                    'bash -lc "$CLAUDE_PROJECT_DIR/gone.sh arg"', 'python3 -uc "$CLAUDE_PROJECT_DIR/gone.py"', 'node -pe "$CLAUDE_PROJECT_DIR/gone.js"',
                    'pwsh -NoProfile -command "$CLAUDE_PROJECT_DIR/gone.ps1 x"', 'python3 - "$CLAUDE_PROJECT_DIR"/data < s.py',
                    "$CLAUDE_PROJECT_DIR/bin/run-`uname`.sh", 'bash "$CLAUDE_PROJECT_DIR/hooks/`uname`.sh"',
                    'cat <<EOF\n$CLAUDE_PROJECT_DIR/gone.sh\nEOF', 'node "$CLAUDE_PROJECT_DIR/.claude\\hooks\\x.js"',
                    '>"$CLAUDE_PROJECT_DIR"/out.log cat', 'true # ; "$CLAUDE_PROJECT_DIR"/gone.sh']
        self.assertEqual(self.run_hooks(commands)[0], [])
        # The same forms still find a script that is run.
        found, _ = self.run_hooks(['if true; then "$CLAUDE_PROJECT_DIR"/gone.sh; fi', 'bash -x "$CLAUDE_PROJECT_DIR"/gone2.sh',
                                   'cat <<<"x"; "$CLAUDE_PROJECT_DIR"/gone3.sh'])
        self.assertEqual([rule for rule, _ in found], ["H7"] * 3)

    def test_spelling_the_shell_does_not_expand_is_not_the_project_directory(self):
        commands = ["'$CLAUDE_PROJECT_DIR/gone.sh'", '\\$CLAUDE_PROJECT_DIR/gone.sh']
        self.assertEqual(self.run_hooks(commands)[0], [])

    def test_script_run_directly_without_execute_permission_is_h8(self):
        files = {self.SCRIPT: "#!/bin/sh\n"}
        found, _ = self.run_hooks(['"$CLAUDE_PROJECT_DIR"/.claude/hooks/check.sh'], files)
        self.assertEqual([rule for rule, _ in found], ["H8"])
        # Through an interpreter, or as an argument, the permission does not matter.
        found, _ = self.run_hooks(['bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/check.sh',
                                   'jq . "$CLAUDE_PROJECT_DIR"/.claude/hooks/check.sh'], files)
        self.assertEqual(found, [])
        # Directly in any command position.
        found, _ = self.run_hooks(['FOO=1 "$CLAUDE_PROJECT_DIR"/.claude/hooks/check.sh',
                                   'cd /tmp && "$CLAUDE_PROJECT_DIR"/.claude/hooks/check.sh; true'], files)
        self.assertEqual([rule for rule, _ in found], ["H8", "H8"])

    def test_untracked_file_on_disk_and_directories_count_as_there(self):
        found, root = self.run_hooks(['"$CLAUDE_PROJECT_DIR"/.claude/hooks/local.sh', 'ls "$CLAUDE_PROJECT_DIR"/.claude/hooks'],
                                     {self.SCRIPT: "#!/bin/sh\n"})
        self.assertEqual([rule for rule, _ in found], ["H7"])
        (root / ".claude/hooks/local.sh").write_text("#!/bin/sh\n")
        (root / ".claude/hooks/local.sh").chmod(0o755)
        self.assertEqual(json.loads(run_new(root, "--format", "json").stdout)["findings"], [])

    def test_paths_this_tool_cannot_resolve_are_not_judged(self):
        commands = ['"$CLAUDE_PROJECT_DIR"/scripts/$NAME.sh', '"$CLAUDE_PROJECT_DIR"/scripts/*.sh', "$HOME/bin/gone.sh",
                    "./scripts/gone.sh", "scripts/gone.sh", '"$CLAUDE_PROJECT_DIR"/../outside/gone.sh', "$OTHER_DIR/scripts/gone.sh"]
        self.assertEqual(self.run_hooks(commands)[0], [])

    def test_project_directory_spellings_are_configuration(self):
        config = '[shared.hooks]\nproject_dir = ["${APP_ROOT:-$HOME/app}"]\n'
        found, _ = self.run_hooks(['"${APP_ROOT:-$HOME/app}/scripts/gone.sh"', '"$CLAUDE_PROJECT_DIR"/scripts/gone.sh'], config=config)
        self.assertEqual([(rule, "scripts/gone.sh" in m) for rule, m in found], [("H7", True)])
        self.assertEqual(self.run_hooks(['"$CLAUDE_PROJECT_DIR"/x/gone.sh'], config='[shared.hooks]\nproject_dir = []\n')[0], [])
        with self.assertRaisesRegex(AssertionError, "shared.hooks.project_dir"):
            self.run_hooks(["/usr/bin/env x"], config='[shared.hooks]\nproject_dir = [""]\n')

    def test_hook_in_a_group_claude_code_ignores_is_not_judged(self):
        text = json.dumps({"hooks": {"Stop": [{"matcher": 5, "hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/gone.sh'}]}]}})
        self.assertEqual(rules_of(text), ["H3"])

    def test_nested_settings_resolve_from_their_own_project_directory(self):
        found, _ = self.run_hooks(['"$CLAUDE_PROJECT_DIR"/tools/run.sh'], {"pkg/tools/run.sh": "x\n", "tools/other.sh": "x\n"},
                                  executable=("pkg/tools/run.sh",), settings="pkg/.claude/settings.json")
        self.assertEqual(found, [])
        found, _ = self.run_hooks(['"$CLAUDE_PROJECT_DIR"/tools/other.sh'], {"tools/other.sh": "x\n"}, settings="pkg/.claude/settings.json")
        self.assertIn("looked for pkg/tools/other.sh", found[0][1])

    def test_levels_are_separate_and_bad_settings_are_left_to_h1(self):
        files = {self.SCRIPT: "#!/bin/sh\n"}
        commands = ['"$CLAUDE_PROJECT_DIR"/.claude/hooks/check.sh', '"$CLAUDE_PROJECT_DIR"/.claude/hooks/gone.sh']
        self.assertEqual([r for r, _ in self.run_hooks(commands, files, config='[rules.H7]\nlevel = "off"\n')[0]], ["H8"])
        self.assertEqual([r for r, _ in self.run_hooks(commands, files, config='[rules.hooks-command-exec]\nlevel = "off"\n')[0]], ["H7"])
        self.assertEqual(rules_of("{not json"), ["H1"])


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
        # The example's script is not in this repository: H7, checked in CommandPathTest.
        self.assertEqual(rules_of(text), ["H7"])

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


class MisplacedKeyTest(unittest.TestCase):
    """H9: a top-level key that works somewhere else and does nothing here (measured on 2.1.325:
    `defaultMode`, `deny`, `disallowedTools` and `mcpServers` at the top level change nothing)."""

    def test_keys_in_their_place_and_other_keys_report_nothing(self):
        text = json.dumps({"permissions": {"defaultMode": "plan", "allow": ["Read"], "deny": ["Bash"], "ask": []},
                           "env": {}, "model": "opus", "enabledPlugins": {}, "_comment": "x", "unknownKey": 1})
        self.assertEqual(rules_of(text), [])

    def test_each_misplaced_key_is_one_finding_that_names_its_place(self):
        text = json.dumps({"defaultMode": "plan", "mcpServers": {}, "disallowedTools": ["Read"], "deny": [], "env": {},
                           "allow": [], "ask": [], "allowedTools": []})      # the last three: not measured, not shipped
        found, doc = lint({SETTINGS: text})
        self.assertEqual(found, [(SETTINGS, None, "H9")] * 4)
        local = ".claude/settings.local.json"
        self.assertEqual(lint({"sub/" + local: text}, None, "--no-git")[0], [("sub/" + local, None, "H9")] * 4)
        got = [f["message"] for f in doc["findings"]]
        self.assertIn("top-level key `defaultMode` is not a setting", got[0])
        self.assertIn("it belongs in `permissions.defaultMode`", got[0])
        self.assertTrue(any("`mcpServers`" in m and "`.mcp.json`" in m for m in got))
        self.assertTrue(any("`disallowedTools`" in m and "`permissions.deny`" in m for m in got))

    def test_only_a_settings_file_is_read(self):
        # A file a repository adds to the family for its hooks has its own top level.
        text = json.dumps({"mcpServers": {}, "hooks": {"Nope": []}})
        config = '[discover]\nextend_hooks_globs = ["plugin/hooks.json"]\n'
        self.assertEqual([rule for _, _, rule in lint({"plugin/hooks.json": text}, config)[0]], ["H2"])

    def test_it_is_reported_beside_the_hook_findings(self):
        self.assertEqual(rules_of(json.dumps({"defaultMode": "plan", "hooks": 5})), ["H3", "H9"])
        self.assertEqual(rules_of(json.dumps({"defaultMode": "plan", "hooks": {"Nope": []}})), ["H2", "H9"])
        self.assertEqual(rules_of(json.dumps({"defaultMode": "plan", "hooks": {}})), ["H9"])
        self.assertEqual(rules_of("[]"), ["H1"])

    def test_the_keys_are_configuration(self):
        text = json.dumps({"defaultMode": "plan", "teamKey": 1})
        found, doc = lint({SETTINGS: text}, '[rules.H9.keys]\nteamKey = "the team file"\n')
        self.assertEqual([rule for _, _, rule in found], ["H9", "H9"])       # a repository's keys add to the shipped ones
        self.assertTrue(any(f["message"].endswith("it belongs in the team file") for f in doc["findings"]))
        self.assertEqual(lint({SETTINGS: text}, '[rules.H9]\nlevel = "off"\n')[0], [])
        self.assertEqual(lint({SETTINGS: text}, '[rules.H9]\nignore = ["defaultMode"]\n')[0], [])
        for config, word in (('[rules.H9]\nkeys = ["defaultMode"]\n', "rules.H9.keys"), ('[rules.H9.keys]\nx = 1\n', "rules.H9.keys.x"),
                             ('[rules.H9]\nkey = 1\n', "rules.H9"), ('[rules.H9]\nignore = "defaultMode"\n', "rules.H9.ignore"),
                             ('[rules.H9]\nignore = ["Deny"]\n', "rules.H9.ignore names Deny")):
            with self.subTest(config=config):
                files = {SETTINGS: text, "AGENTS.md": "ok\n", ".agentfile-lint.toml": config}
                r = run_new(make_repo(files), "--format", "json")
                self.assertEqual(r.returncode, 2)
                self.assertIn(word, r.stderr)


if __name__ == "__main__":
    unittest.main()
