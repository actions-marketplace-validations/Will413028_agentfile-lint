"""H1 to H6: hooks in Claude Code settings files (docs/rules.md "H1 to H6 hooks").

Only what the hooks reference states: the file is JSON, `hooks` maps documented event names to
matcher groups, each handler has a known `type` and that type's required fields, and a command hook
names a command. Optional fields and other settings keys are not checked: the key set changes with
Claude Code releases, and a full schema is out of scope (docs/rules.md, Not checked).

Each consequence in a message was measured with `claude doctor` on Claude Code 2.1.318. A handler or
matcher group under PreToolUse or PermissionRequest that cannot be loaded keeps Claude Code from
applying the settings around it, since it may guard the permissions declared beside it; elsewhere
Claude Code ignores just that entry. Positions are JSON paths in the form `claude doctor` prints
(`hooks.Stop.0.hooks.1`); the line is the file (0) except for a JSON syntax error.
"""
from __future__ import annotations

from typing import Any

from ..errors import levels_only
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
)
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


def validate(shared: None, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    return {}, levels_only(tables)


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
    if "hooks" not in data:
        return []
    found: list[Finding] = []
    hooks = data["hooks"]
    if not isinstance(hooks, dict):
        return [Finding(path, 0, "H3", f"hooks is a JSON {kind(hooks)}, not an object mapping event names to "
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
