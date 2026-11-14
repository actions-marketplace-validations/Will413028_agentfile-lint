"""H1 to H9: hooks in Claude Code settings files (docs/rules.md "H1 to H9 hooks").

Only what the hooks reference states: the file is JSON, `hooks` maps documented event names to
matcher groups, each handler has a known `type` and that type's required fields, and a command hook
names a command. Optional fields and other settings keys are not checked: the key set changes with
Claude Code releases, and a full schema is out of scope (docs/rules.md, Not checked). H9 is the one
exception, and a narrow one: a top-level key from the table `[rules.H9] keys`, each a key that works
in another place and does nothing at the top level of a settings file (measured on 2.1.325).

Each consequence in a message of H1 to H6 was measured with `claude doctor` on Claude Code 2.1.318;
H7 to H9 were measured by running headless sessions (2.1.323 and 2.1.325), and `claude doctor` says
nothing about them. A handler or
matcher group under PreToolUse or PermissionRequest that cannot be loaded keeps Claude Code from
applying the settings around it, since it may guard the permissions declared beside it; elsewhere
Claude Code ignores just that entry. Positions are JSON paths in the form `claude doctor` prints
(`hooks.Stop.0.hooks.1`); the line is the file (0) except for a JSON syntax error.

H7 and H8 look at the script a command hook runs inside the project: the program of one of its
simple commands, or the script handed to an interpreter (`bash`, `python3`, `node`; measured on Claude Code
2.1.323): a script that is not there, or one that is run directly without execute permission, does
not run. Claude Code treats that as a non-blocking error, so the action the hook was meant to check
goes ahead. A script counts when its word is one of `[shared.hooks] project_dir` (spellings of the
project directory, `$CLAUDE_PROJECT_DIR` by default) where the shell expands it, then a path without
an expansion of its own. Other paths in a command (arguments, redirection targets, files it creates)
are not judged. A hook with `args` runs without a shell (exec form, measured on 2.1.325): `command`
is the program as written, the script may be an element of `args`, and only `${CLAUDE_PROJECT_DIR}`
names the project directory.
"""
from __future__ import annotations

import os
import posixpath
import re
from typing import Any, Iterator

from ..context import Context
from ..errors import ConfigError, check_keys, expect_str, expect_str_list, levels_only, require_keys
from ..finding import Finding
from ._json import blank, kind, load

FAMILY = "hooks"

CHECKS = (
    ("H1", "settings-json", "settings file is valid JSON and an object"),
    ("H2", "hooks-event", "hook event names are ones Claude Code documents"),
    ("H3", "hooks-shape", "hooks, event lists, matcher groups and handler lists have the documented shape"),
    ("H4", "hooks-type", "every hook handler has a documented type"),
    ("H5", "hooks-required", "every hook handler has its type's required fields as strings"),
    ("H6", "hooks-empty-command", "a command hook's command is not empty"),
    ("H7", "hooks-command-path", "a script a hook command runs from the project directory exists"),
    ("H8", "hooks-command-exec", "a script a hook command runs directly has execute permission"),
    ("H9", "settings-misplaced-key", "a settings file has no top-level key that belongs somewhere else"),
)
SHARED = ("hooks", {"project_dir"})
WHOLE_FILE = tuple(rule_id for rule_id, _, _ in CHECKS)   # JSON has no comments; no directive applies

# Hooks reference, "Hook lifecycle" table and "Hook events" sections (2026-11-06); `claude doctor`
# on 2.1.318 lists the same 33.
EVENTS = frozenset((
    "SessionStart Setup UserPromptSubmit UserPromptExpansion PreToolUse PermissionRequest PermissionDenied "
    "PostToolUse PostToolUseFailure PostToolBatch Notification MessageDisplay SubagentStart SubagentStop "
    "TaskCreated TaskCompleted Stop StopFailure TeammateIdle InstructionsLoaded ConfigChange CwdChanged "
    "DirectoryAdded FileChanged WorktreeCreate WorktreeRemove PreCompact PostCompact PreModelSwitch "
    "PostModelSwitch Elicitation ElicitationResult SessionEnd"
).split())
# Hooks reference, "Hook handler fields": handler type -> its fields marked required (besides `type`).
REQUIRED = {
    "command": ("command",),
    "http": ("url",),
    "mcp_tool": ("server", "tool"),
    "prompt": ("prompt",),
    "agent": ("prompt",),
}
GUARDING = frozenset({"PreToolUse", "PermissionRequest"})
# H9 is about the top level of a settings file; another file of the family (one a repository adds
# to `hooks_globs` for its hooks) has its own top level.
SETTINGS_NAMES = frozenset({"settings.json", "settings.local.json"})


def validate(shared: dict[str, Any], tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    check_keys(shared, {"project_dir"}, "shared.hooks")
    require_keys(shared, ["project_dir"], "shared.hooks")
    spellings = expect_str_list(shared["project_dir"], "shared.hooks.project_dir", allow_empty=True)
    h9 = tables["H9"]
    check_keys(h9, {"level", "keys", "ignore"}, "rules.H9")
    require_keys(h9, ["keys", "ignore"], "rules.H9")
    ignore = expect_str_list(h9["ignore"], "rules.H9.ignore", allow_empty=True)
    if not isinstance(h9["keys"], dict):
        raise ConfigError(f"rules.H9.keys must be a table of key = \"where it belongs\", got {type(h9['keys']).__name__}")
    misplaced = {key: expect_str(place, f"rules.H9.keys.{key}") for key, place in h9["keys"].items()}
    strangers = [key for key in ignore if key not in misplaced]
    if strangers:
        raise ConfigError(f"rules.H9.ignore names {', '.join(strangers)}, not in rules.H9.keys ({', '.join(sorted(misplaced))})")
    effective = levels_only({rule_id: table for rule_id, table in tables.items() if rule_id != "H9"})
    effective["H9"] = {"keys": misplaced, "ignore": ignore}
    return {"project_dir": spellings, "misplaced": {k: v for k, v in misplaced.items() if k not in ignore}}, effective


def _commands(data: Any) -> Iterator[tuple[str, str, list[str] | None]]:
    """(JSON path, command, args) of every command hook that H1 to H6 accept as one. `args` is None
    in shell form (no `args` key); a hook whose `args` is not a list of strings is left out."""
    hooks = data.get("hooks") if isinstance(data, dict) else None
    for event, groups in hooks.items() if isinstance(hooks, dict) else ():
        for i, group in enumerate(groups if event in EVENTS and isinstance(groups, list) else ()):
            if not isinstance(group, dict) or not isinstance(group.get("matcher", ""), str):
                continue
            handlers = group.get("hooks")
            for j, handler in enumerate(handlers if isinstance(handlers, list) else ()):
                if isinstance(handler, dict) and handler.get("type") == "command" and isinstance(handler.get("command"), str):
                    args = handler.get("args")
                    if "args" in handler and not (isinstance(args, list) and all(isinstance(a, str) for a in args)):
                        continue
                    yield f"hooks.{event}.{i}.hooks.{j}", handler["command"], args


# Programs that run the script given as their first argument, and words that only wrap a command.
_INTERPRETERS = frozenset("bash sh zsh dash ksh python python3 node bun deno ruby perl pwsh source .".split())
_WRAPPERS = frozenset("exec command nohup time env if then elif else while until do ! {".split())
_TESTS = frozenset(("[", "[[", "test"))
# With one of these before it, an interpreter's argument is code or a module, not a script: a short
# flag cluster holding c, e, m or p (`-c`, `-lc`, `-pe`), `--eval`, `--print`, `-Command`, or a bare `-`.
_INLINE = re.compile(r"-[A-Za-z]*[cemp][A-Za-z]*\Z|--eval\Z|--print\Z|-(?i:command)\Z|-\Z")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def simple_commands(command: str) -> list[list[tuple[str, str]]]:
    """The simple commands of a shell command line, each a list of words without its redirection
    targets. A word is (text with the quotes removed, a mark per character: `s` inside single
    quotes or after a backslash, where the shell expands nothing, else `u`)."""
    out: list[list[tuple[str, str]]] = [[]]
    text: list[str] = []
    marks: list[str] = []
    quote = ""
    started = redirect = False

    def end_word() -> None:
        nonlocal started, redirect
        if started and not redirect:
            out[-1].append(("".join(text), "".join(marks)))
        if started:
            redirect = False
        text.clear()
        marks.clear()
        started = False

    i = 0
    while i < len(command):
        c = command[i]
        if quote:
            if c == quote:
                quote = ""
            elif c == "\\" and quote == '"' and command[i + 1:i + 2] in ('"', "\\", "$", "`"):
                i += 1
                text.append(command[i])
                marks.append("s")
            else:
                text.append(c)
                marks.append("s" if quote == "'" else "u")
        elif c in "'\"":
            quote, started = c, True
        elif c == "\\" and i + 1 < len(command):
            i += 1
            started = True
            text.append(command[i])
            marks.append("s")
        elif c in " \t":
            end_word()
        elif c in ";&|()\n":
            end_word()
            out.append([])
        elif c in "<>":
            end_word()
            if command.startswith("<<", i) and not command.startswith("<<<", i):
                break   # a here-document: what follows is its text, not commands
            redirect = True
            while command[i + 1:i + 2] in (">", "<", "&", "|"):
                i += 1
        elif c == "#" and not started:
            break
        else:
            started = True
            text.append(c)
            marks.append("u")
        i += 1
    end_word()
    return [words for words in out if words]


def _project_path(word: tuple[str, str], spellings: list[str]) -> str | None:
    """The path a word names under the project directory: the word is a spelling the shell expands,
    then `/`, then a path without an expansion of its own."""
    text, marks = word
    for spelling in sorted(spellings, key=len, reverse=True):
        if text.startswith(spelling + "/") and "s" not in marks[:len(spelling)]:
            rest, rest_marks = text[len(spelling) + 1:], marks[len(spelling) + 1:]
            # A backslash that is still there sat inside double quotes: a Windows-style path, not ours.
            if not rest or "\\" in rest or any(c in "$*?{}[]~`" and m == "u" for c, m in zip(rest, rest_marks)):
                return None
            return posixpath.normpath(rest)
    return None


# Shells: only `c` (code) or `s` (script on stdin) in a flag cluster means the next word is not a
# script (`bash -e script` runs the script).
_SHELLS = frozenset("bash sh zsh dash ksh".split())
_SHELL_INLINE = re.compile(r"-[A-Za-z]*[cs][A-Za-z]*\Z|-\Z")
# Words only a shell understands: without one (exec form) they are not programs.
_SHELL_ONLY = frozenset("exec command if then elif else while until do ! { source .".split())
# Exec form: the one spelling of the project directory Claude Code substitutes without a shell.
_PLACEHOLDER = "${CLAUDE_PROJECT_DIR}"


def _scripts(words: list[tuple[str, str]], spellings: list[str], shell: bool) -> tuple[list[tuple[str, bool, int]], list[str]]:
    """((path under the project directory, whether it is run directly, index of its word) of each
    script one simple command runs, the paths it only tests). The program may be a script and an
    interpreter at once (`"$CLAUDE_PROJECT_DIR"/.venv/bin/python x.py`). Without a shell (exec
    form) an assignment counts only after a wrapper such as `env`, and a shell-only word is not a program."""
    start = 0
    while start < len(words):
        text, marks = words[start]
        if _ASSIGNMENT.match(text) and (marks[0] == "u" if shell else start):
            pass
        elif text not in _WRAPPERS or not shell and text in _SHELL_ONLY:
            break
        start += 1
    if start == len(words):
        return [], []
    program = words[start][0]
    if program in _TESTS:
        return [], [p for p in (_project_path(w, spellings) for w in words[start + 1:]) if p]
    found: list[tuple[str, bool, int]] = []
    path = _project_path(words[start], spellings)
    if path:
        found.append((path, True, start))
    name = posixpath.basename(program)
    if name in _INTERPRETERS and (shell or name not in _SHELL_ONLY):
        inline = _SHELL_INLINE if name in _SHELLS else _INLINE
        for i in range(start + 1, len(words)):
            if inline.match(words[i][0]):
                break
            if not words[i][0].startswith("-"):
                path = _project_path(words[i], spellings)
                if path:
                    found.append((path, False, i))
                break
    return found, []


def project_scripts(command: str, spellings: list[str]) -> list[tuple[str, bool, str]]:
    """(path under the project directory, whether it is run directly, the handler key that names
    it) of each script a shell-form command runs: the program of a simple command, or the script
    an interpreter is given. A path the same command tests first (`[ -x path ] && path`) is
    optional by design and left out."""
    found: list[tuple[str, bool, str]] = []
    tested: set[str] = set()
    for words in simple_commands(command):
        scripts, tests = _scripts(words, spellings, shell=True)
        found.extend((path, direct, "command") for path, direct, _ in scripts)
        tested.update(tests)
    return [entry for entry in dict.fromkeys(found) if entry[0] not in tested]


def exec_scripts(command: str, args: list[str]) -> list[tuple[str, bool, str]]:
    """`project_scripts` for exec form (a hook with `args`): no shell reads the hook, so `command`
    is the program as written, each element of `args` is one argument, and only
    `${CLAUDE_PROJECT_DIR}` names the project directory. A wrapper program (`env`, `nohup`,
    `time`, by name or by path) is followed into `args`."""
    def word(text: str) -> tuple[str, str]:
        # Marks as `simple_commands` gives them: the placeholder is expanded, the rest is literal.
        # A second placeholder is marked expanded too, which makes the word no path (`_project_path`).
        known = len(_PLACEHOLDER) if text.startswith(_PLACEHOLDER) else 0
        rest = text[known:]
        return text, "u" * known + ("u" if _PLACEHOLDER in rest else "s") * len(rest)

    # `/usr/bin/env` is the wrapper; a file of that name under the project directory is a script.
    name = posixpath.basename(command)
    words = [word(name if name in _WRAPPERS and not command.startswith(_PLACEHOLDER) else command)] + [word(arg) for arg in args]
    scripts, _ = _scripts(words, [_PLACEHOLDER], shell=False)
    return [(path, direct, f"args.{i - 1}" if i else "command") for path, direct, i in scripts]


def check_repo(ctx: Context, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    found: list[Finding] = []
    if levels["H7"] == "off" and levels["H8"] == "off":
        return found
    for path, text in ctx.family_files.get(FAMILY, {}).items():
        data, problem = (None, None) if blank(text) else load(text)
        if problem is not None:
            continue
        # The project directory: the one that holds the `.claude` folder of the settings file.
        folder = posixpath.dirname(path)
        base = posixpath.dirname(folder) if posixpath.basename(folder) == ".claude" else folder
        for where, command, args in _commands(data):
            scripts = project_scripts(command, params["project_dir"]) if args is None else exec_scripts(command, args)
            for relative, direct, key in scripts:
                target = posixpath.normpath(posixpath.join(base, relative))
                if target == ".." or target.startswith("../"):
                    continue
                on_disk = ctx.root / target
                if target not in ctx.tracked_set and target not in ctx.dirs and not on_disk.exists():
                    found.append(Finding(path, 0, "H7", f"{where}.{key} runs {relative}, which is not a tracked "
                                         f"file (looked for {target}); the hook cannot start, which is a non-blocking error: the action goes ahead without it"))
                elif direct and os.name != "nt" and on_disk.is_file() and not os.access(on_disk, os.X_OK):
                    found.append(Finding(path, 0, "H8", f"{where}.{key} runs {relative} directly, and the file has no "
                                         "execute permission; the hook cannot start, which is a non-blocking error: the action goes "
                                         "ahead without it (chmod +x the file, or run it through its interpreter)"))
    return found


def check(path: str, text: str, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    if blank(text):
        return []
    data, problem = load(text)
    if problem is not None:
        if not problem.invalid:
            return [Finding(path, 0, "H1", problem.why)]
        return [Finding(path, problem.line, "H1", f"not valid JSON: {problem.why}; Claude Code reports a "
                        "settings error and does not apply this file")]
    if not isinstance(data, dict):
        return [Finding(path, 0, "H1", f"the file is a JSON {kind(data)}, not an object; Claude Code does not "
                        "apply it")]
    found: list[Finding] = [
        Finding(path, 0, "H9", f"top-level key `{key}` is not a setting: Claude Code ignores it here without a warning; "
                f"it belongs in {params['misplaced'][key]}")
        for key in data if key in params["misplaced"] and posixpath.basename(path) in SETTINGS_NAMES]
    if "hooks" not in data:
        return found
    hooks = data["hooks"]
    if not isinstance(hooks, dict):
        return found + [Finding(path, 0, "H3", f"hooks is a JSON {kind(hooks)}, not an object mapping event names to "
                                "matcher groups; Claude Code ignores every hook in this file")]
    for event, groups in hooks.items():
        where = f"hooks.{event}"
        if event not in EVENTS:
            found.append(Finding(path, 0, "H2", f"{where}: unknown hook event {event!r}; Claude Code ignores its hooks "
                                 "(event names are case-sensitive, see the hooks reference)"))
            continue
        if not isinstance(groups, list):
            found.append(Finding(path, 0, "H3", f"{where} is a JSON {kind(groups)}, not an array of matcher groups; "
                                 f"{_ignored(event, 'this event')}"))
            continue
        for i, group in enumerate(groups):
            found += _group(path, event, f"{where}.{i}", group)
    return found


def _ignored(event: str, what: str) -> str:
    """What Claude Code does with a part of `event`'s hooks it cannot load."""
    if event in GUARDING:
        return (f"Claude Code cannot load {what}, and on {event} that keeps it from applying the settings "
                "around it, permissions included")
    return f"Claude Code ignores {what}"


def _group(path: str, event: str, where: str, group: Any) -> list[Finding]:
    if not isinstance(group, dict):
        return [Finding(path, 0, "H3", f"{where}: a matcher group is a JSON {kind(group)}, not an object; "
                        f"{_ignored(event, 'this matcher group')}")]
    if "matcher" in group and not isinstance(group["matcher"], str):
        return [Finding(path, 0, "H3", f"{where}.matcher is a JSON {kind(group['matcher'])}, not a string; "
                        f"{_ignored(event, 'this matcher group')}")]
    handlers = group.get("hooks")
    if not isinstance(handlers, list):
        got = "missing" if "hooks" not in group else f"a JSON {kind(handlers)}"
        return [Finding(path, 0, "H3", f"{where}.hooks is {got}, not an array of hook handlers; "
                        f"{_ignored(event, 'this matcher group')}")]
    found: list[Finding] = []
    for j, handler in enumerate(handlers):
        found += _handler(path, event, f"{where}.hooks.{j}", handler)
    return found


def _handler(path: str, event: str, where: str, handler: Any) -> list[Finding]:
    if not isinstance(handler, dict):
        return [Finding(path, 0, "H3", f"{where}: a hook handler is a JSON {kind(handler)}, not an object; "
                        f"{_ignored(event, 'this handler')}")]
    types = ", ".join(REQUIRED)
    if "type" not in handler:
        return [Finding(path, 0, "H4", f"{where} has no type (one of {types}); {_ignored(event, 'this handler')}")]
    hook_type = handler["type"]
    if not isinstance(hook_type, str) or hook_type not in REQUIRED:
        shown = repr(hook_type) if isinstance(hook_type, str) else f"a JSON {kind(hook_type)}"
        return [Finding(path, 0, "H4", f"{where}.type is {shown}, not one of {types}; {_ignored(event, 'this handler')}")]
    found: list[Finding] = []
    for field in REQUIRED[hook_type]:
        value = handler.get(field)
        if not isinstance(value, str):
            got = "missing" if field not in handler else f"a JSON {kind(value)}"
            found.append(Finding(path, 0, "H5", f"{where}.{field} is {got}; a {hook_type} hook requires it as a "
                                 f"string; {_ignored(event, 'this handler')}"))
    if hook_type == "command" and isinstance(handler.get("command"), str) and not handler["command"].strip():
        found.append(Finding(path, 0, "H6", f"{where}.command is empty; Claude Code loads the hook without a "
                             "warning, and it runs no program"))
    return found
