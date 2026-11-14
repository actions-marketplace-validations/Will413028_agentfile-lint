"""A1 to A7: Claude Code subagent files (`.claude/agents/**/*.md`).

A subagent file that Claude Code cannot read is not an error anywhere: the subagent is simply not in
the list Claude chooses from. A1 to A5 are each one way that happens (measured with Claude Code 2.1.323,
docs/rules.md "A1 to A7 subagent files"):

- A1: the frontmatter does not parse, even after Claude Code's second attempt.
- A2: the file has no frontmatter.
- A3: `name` is missing, not a non-empty string, or one Claude Code refuses (it starts with `-`, has
  a `:`, or is longer than 256 characters; documented, not measured here).
- A4: `description` is missing or not a non-empty string.
- A5: another subagent file in the same `agents` directory has the same `name`; only one is loaded.

A6 is about a file that does load: `tools` names a tool Claude Code does not recognise (measured with
2.1.325). The entry is dropped without a word and the subagent runs without that tool; when no entry
is left, Claude Code refuses to start the subagent. The names it knows are data (`[shared.agents] tools`).
A7 is the same check on `disallowedTools`, where an unknown name denies nothing: the subagent keeps
the tool its author meant to take away (`disallowedTools: bash`).

Runs on the agents file family (`[discover] agents_globs`). The frontmatter is read as Claude Code
reads it (`frontmatter.parse_as_claude_code`): a `description` with a colon in it is quoted on the second
attempt and is fine. Upper case and spaces in `name` are fine too.
"""
from __future__ import annotations

import posixpath
import re
from typing import Any

from ..context import Context
from ..discover import matches
from ..errors import check_keys, expect_str_list, levels_only, require_keys
from ..finding import Finding
from ..frontmatter import is_string, parse_as_claude_code

FAMILY = "agents"

CHECKS = (
    ("A1", "agent-yaml", "a subagent file's frontmatter is valid YAML and a mapping"),
    ("A2", "agent-frontmatter", "a subagent file starts with YAML frontmatter"),
    ("A3", "agent-name", "a subagent file has a name"),
    ("A4", "agent-description", "a subagent file has a description"),
    ("A5", "agent-duplicate-name", "no two subagent files in one agents directory have the same name"),
    ("A6", "agent-tools", "every entry of a subagent file's `tools` names a tool Claude Code knows"),
    ("A7", "agent-disallowed-tools", "every entry of a subagent file's `disallowedTools` names a tool Claude Code knows"),
)
SHARED = ("agents", {"tools", "extend_tools"})
WHOLE_FILE = ("A2",)   # the other ids are on frontmatter lines; A ids take no directive anyway

NOT_LOADED = "Claude Code does not load the subagent"
MAX_NAME = 256


def validate(shared: Any, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    a2 = tables["A2"]
    check_keys(a2, {"level", "ignore"}, "rules.A2")
    require_keys(a2, ["ignore"], "rules.A2")
    ignore = expect_str_list(a2["ignore"], "rules.A2.ignore", allow_empty=True)
    check_keys(shared, {"tools", "extend_tools"}, "shared.agents")
    require_keys(shared, ["tools", "extend_tools"], "shared.agents")
    tools = expect_str_list(shared["tools"], "shared.agents.tools", allow_empty=True)
    extend = expect_str_list(shared["extend_tools"], "shared.agents.extend_tools", allow_empty=True)
    effective = levels_only({rule_id: table for rule_id, table in tables.items() if rule_id != "A2"})
    effective["A2"] = {"ignore": ignore}
    return {"ignore": ignore, "tools": frozenset(tools) | frozenset(extend)}, effective


def tool_entries(value: object, plain: object = False) -> list[str]:
    """The entries of a `tools` value: a YAML list, or a string (in brackets or not, which is what
    the second parse makes of a flow list). Entries are separated by commas or white space, in a
    list item too; inside parentheses both belong to the entry (`Agent(worker, researcher)`).
    `plain` is `Frontmatter.plain` for the key: a scalar that is not a string (`null`, `true`) is
    no entry. A list is read as its items joined by commas, which also puts back together an
    entry a flow list cut at the commas inside its parentheses."""
    if isinstance(value, list):
        flags = plain if isinstance(plain, list) and len(plain) == len(value) else [False] * len(value)
        value, plain = ", ".join(item for item, flag in zip(value, flags) if isinstance(item, str) and is_string(item, flag)), False
    if not isinstance(value, str) or not is_string(value, plain):
        return []
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    out, depth, start = [], 0, 0
    for i, c in enumerate(text + ","):
        if c == "(":
            depth += 1
        elif c == ")" and depth:
            depth -= 1
        elif (c == "," or c.isspace()) and depth == 0:
            out.append(text[start:i].strip("\"'"))
            start = i + 1
    return [entry for entry in out if entry]


_TOOL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")


def unknown_tools(value: object, known: frozenset[str], plain: object = False) -> tuple[list[str], bool]:
    """(the tool names of a `tools` value that are not in `known`, whether another entry is left).
    An entry's name is what stands before a `(`; `*` and MCP tools (`mcp__...`, which depend on
    the servers of the session) are never unknown, and neither is an entry whose name is not a
    word (`(x)`, `[Bash]`): how Claude Code reads those was not measured."""
    unknown: list[str] = []
    left = False
    for entry in tool_entries(value, plain):
        name = entry.split("(", 1)[0]
        if name == "*" or name.startswith("mcp__") or name in known:
            left = True
        elif _TOOL_NAME.match(name) and name not in unknown:
            unknown.append(name)
    return unknown, left


def agents_dir(path: str) -> str:
    """The `agents` directory a file belongs to: the one inside `.claude` when the path has one (Claude
    Code reads its subdirectories too), else the file's own directory."""
    parts = path.split("/")
    for i in range(len(parts) - 2):
        if parts[i] == ".claude" and parts[i + 1] == "agents":
            return "/".join(parts[:i + 2])
    return posixpath.dirname(path)


def check_repo(ctx: Context, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    found: list[Finding] = []
    names: dict[tuple[str, str], str] = {}   # (agents directory, name) -> the first file that has it
    for path, text in sorted(ctx.family_files.get(FAMILY, {}).items()):
        fm = parse_as_claude_code(text)
        if fm is None:
            if not matches(path, params["ignore"]):
                found.append(Finding(path, 0, "A2", f"no YAML frontmatter with `name` and `description`; {NOT_LOADED}"))
            continue
        if fm.error is not None:
            found.append(Finding(path, fm.line, "A1", f"{fm.error}; {NOT_LOADED}"))
            continue
        data = {} if fm.value is None else fm.value
        if not isinstance(data, dict):
            found.append(Finding(path, 1, "A1", f"frontmatter is a YAML {type(data).__name__}, not a mapping; {NOT_LOADED}"))
            continue
        usable = {}
        for key, rule in (("name", "A3"), ("description", "A4")):
            value = data.get(key)
            usable[key] = isinstance(value, str) and bool(value.strip()) and is_string(value, fm.plain.get(key, False))
            if not usable[key]:
                what = "missing" if key not in data else "not a non-empty string"
                found.append(Finding(path, fm.keys.get(key, 1), rule, f"`{key}` is {what}; {NOT_LOADED}"))
        name = data["name"].strip() if usable["name"] else ""
        refused = ("starts with `-`" if name.startswith("-") else "contains `:`" if ":" in name
                   else f"is {len(name)} characters, over {MAX_NAME}" if len(name) > MAX_NAME else None)
        if refused:
            usable["name"] = False
            found.append(Finding(path, fm.keys.get("name", 1), "A3", f"`name` {refused}; {NOT_LOADED}"))
        if all(usable.values()):
            key = (agents_dir(path), data["name"].strip())
            first = names.setdefault(key, path)
            if first != path:
                found.append(Finding(path, fm.keys.get("name", 1), "A5", f"name {key[1]!r} is also the name of {first}; "
                                     "Claude Code loads only one of them"))
            # A6 and A7 are for a subagent that loads.
            for field, rule in (("tools", "A6"), ("disallowedTools", "A7")):
                unknown, left = unknown_tools(data.get(field), params["tools"], fm.plain.get(field, False))
                if not unknown:
                    continue
                then = ("the entry denies nothing, and a tool meant by it stays available to the subagent" if rule == "A7"
                        else "it drops the entry without a warning and the subagent runs without it" if left
                        else "no entry is left, so Claude Code refuses to start the subagent")
                listed = ", ".join(f"`{name}`" for name in unknown)
                found.append(Finding(path, fm.keys.get(field, 1), rule, f"`{field}` names {listed}, which Claude Code does "
                                     f"not recognise as a tool (names are case-sensitive); {then}"))
    return found
