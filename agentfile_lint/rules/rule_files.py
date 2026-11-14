"""P1 to P5: Claude Code rule files (`.claude/rules/**/*.md`) and their `paths` frontmatter.

A rule file without `paths` loads in every session; one with `paths` loads only once Claude reads a
file a pattern matches. Each id reports a frontmatter that silently gives another behaviour than the
one written (measured with Claude Code 2.1.323, docs/rules.md "P1 to P5 rule files"):

- P1: the frontmatter does not parse, so it is ignored and the rule loads in every session.
- P2: `paths` holds no pattern (a number, a boolean, a mapping, nothing, an empty list), so the rule
  loads in every session.
- P3: a pattern matches no tracked file, so the rule never loads through it.
- P4: there is no `paths` but a key that looks like it (`globs`, `path`, `Paths`), which Claude Code
  ignores, so the rule loads in every session.
- P5: one item of the `paths` list is not a string and is ignored; the other patterns work.

"Every session" is for a rule in the root `.claude/rules/`; one in a subdirectory's loads on demand,
and what it loses is its path scope.

Runs on instruction files inside a `.claude/rules/` directory. The frontmatter is read as Claude Code
reads it (`frontmatter.parse_as_claude_code`): when the YAML does not parse, the values of
`key: value` lines that hold a YAML special character are quoted and the block is parsed again, so
`paths: **/*.ts` is a pattern, not an error.
Patterns are relative to the directory that holds that `.claude` folder: a pattern without a slash
matches at any depth, a leading `/` anchors it, a trailing `/` names a directory, a pattern that
matches a directory matches everything in it, `{a,b}` expands, letter case is ignored, and a
comma-separated string is a list.
"""
from __future__ import annotations

import re
from typing import Any

from .. import frontmatter
from ..context import Context
from ..errors import check_keys, expect_str_list, levels_only, require_keys
from ..finding import Finding

CHECKS = (
    ("P1", "rule-yaml", "a rule file's frontmatter is valid YAML"),
    ("P2", "rule-paths-type", "`paths` in a rule file is a glob or a list of globs"),
    ("P3", "rule-paths-match", "every `paths` pattern of a rule file matches a tracked file"),
    ("P4", "rule-paths-key", "a rule file has no key that looks like a misspelt `paths`"),
    ("P5", "rule-paths-item", "every item of a rule file's `paths` list is a string"),
)
# Findings sit on frontmatter lines, where an HTML comment cannot be written: no per-line directive.
WHOLE_FILE = ("P1", "P2", "P3", "P4", "P5")

# A root rule without a scope loads at launch; one in a subdirectory's `.claude/rules/` loads with that
# directory's rules. Either way the scope written in the file is not applied.
EVERY_SESSION = "Claude Code loads the rule without a path scope (a root rule: in every session)"
MAX_EXPANSIONS = 1000   # Claude Code's budget of expanded patterns for one `paths` list
# Glob syntax this module does not read: negation, extended globs, POSIX classes and set operators
# in a bracket expression. A pattern that uses it is never reported.
_UNREAD = re.compile(r"\A!|[@?*+!]\(|\[[^\]]*(?:\[:|--|&&|~~|\|\|)")


def validate(shared: Any, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    p4 = tables["P4"]
    check_keys(p4, {"level", "keys"}, "rules.P4")
    require_keys(p4, ["keys"], "rules.P4")
    keys = expect_str_list(p4["keys"], "rules.P4.keys", allow_empty=True)
    effective = levels_only({rule_id: table for rule_id, table in tables.items() if rule_id != "P4"})
    effective["P4"] = {"keys": keys}
    return {"keys": keys}, effective


def base_dir(path: str) -> str | None:
    """The directory holding the `.claude` folder of a rule file ("" is the root), or None when
    `path` is not inside a `.claude/rules/` directory."""
    parts = path.split("/")
    for i in range(len(parts) - 2):
        if parts[i] == ".claude" and parts[i + 1] == "rules":
            return "/".join(parts[:i])
    return None


def check_repo(ctx: Context, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    found: list[Finding] = []
    candidates: dict[str, tuple[set[str], set[str]]] = {}
    for path, text in ctx.files.items():
        base = base_dir(path)
        if base is None:
            continue
        fm = frontmatter.parse_as_claude_code(text)
        if fm is None:
            continue
        if fm.error is not None:
            found.append(Finding(path, fm.line, "P1", f"{fm.error}; Claude Code ignores the frontmatter: "
                                 f"{EVERY_SESSION}, whatever `paths` says"))
            continue
        data = fm.value
        if not isinstance(data, dict):
            continue
        if "paths" not in data:
            alike = [k for k in data if k in params["keys"] or k.lower() == "paths"]
            if alike:
                found.append(Finding(path, fm.keys.get(alike[0], 1), "P4", f"key {alike[0]!r} is not `paths` and is ignored; "
                                     f"{EVERY_SESSION}"))
            continue
        line = fm.keys.get("paths", 1)
        patterns, no_pattern, ignored = _patterns(data["paths"], fm.plain.get("paths", False))
        if no_pattern:
            found.append(Finding(path, line, "P2", f"`paths` is {no_pattern}; {EVERY_SESSION}"))
        elif ignored:
            found.append(Finding(path, line, "P5", f"`paths` has {ignored} that is not a string; Claude Code ignores "
                                 "it and uses the other patterns"))
        if levels["P3"] == "off":
            continue
        if base not in candidates:
            candidates[base] = _under(ctx, base)
        budget = MAX_EXPANSIONS
        for pattern in patterns:
            expanded = _expand(pattern, budget)
            if expanded is None:
                expanded = [pattern]      # over the budget: used unexpanded, its braces literal
            elif len(expanded) > 1:
                budget -= len(expanded)
            if not _UNREAD.search(pattern) and not any(_matches(p, *candidates[base]) for p in expanded):
                where = f"under {base}/" if base else "in the repository"
                found.append(Finding(path, line, "P3", f"`paths` pattern {pattern!r} matches no tracked file {where}; "
                                     "the rule never loads through it"))
    return found


def _patterns(value: object, plain: object) -> tuple[list[str], str | None, str | None]:
    """(the patterns Claude Code uses, why `paths` holds none or None, what it ignores or None)."""
    if isinstance(value, dict):
        return [], "a mapping, not a glob or a list of globs", None
    if isinstance(value, list):
        flags = plain if isinstance(plain, list) and len(plain) == len(value) else [False] * len(value)
        strings = [item for item, flag in zip(value, flags) if isinstance(item, str) and frontmatter.is_string(item, flag)]
        patterns = [s.strip() for s in strings if s.strip()]
        if not patterns:
            return [], "an empty list" if not value else "a list without a string", None
        skipped = len(value) - len(strings)
        return patterns, None, None if not skipped else "an item" if skipped == 1 else f"{skipped} items"
    if not frontmatter.is_string(value, plain):
        return [], "empty" if str(value) in ("", "~") or str(value).lower() == "null" else f"{value}, not a string", None
    patterns = [p.strip() for p in _split_commas(str(value)) if p.strip()]
    return patterns, None if patterns else "an empty string", None


def _split_commas(text: str) -> list[str]:
    """A comma-separated `paths` string as its patterns; a comma inside braces belongs to the pattern."""
    out, depth, start = [], 0, 0
    for i, c in enumerate(text):
        if c == "{":
            depth += 1
        elif c == "}" and depth:
            depth -= 1
        elif c == "," and depth == 0:
            out.append(text[start:i])
            start = i + 1
    return out + [text[start:]]


def _under(ctx: Context, base: str) -> tuple[set[str], set[str]]:
    """(every tracked file under `base`, every directory that holds one), relative to `base`."""
    prefix = base + "/" if base else ""
    files: set[str] = set()
    dirs: set[str] = set()
    for path in ctx.tracked:
        if not path.startswith(prefix):
            continue
        parts = path[len(prefix):].split("/")
        files.add("/".join(parts))
        dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
    return files, dirs


def _expand(pattern: str, budget: int) -> list[str] | None:
    """Brace expansion; None when it needs more than `budget` patterns."""
    done, todo = [], [pattern]
    while todo:
        if len(done) + len(todo) > max(budget, 1):
            return None
        current = todo.pop()
        group = _first_group(current)
        if group is None:
            done.append(current)
            continue
        start, end, options = group
        todo.extend(current[:start] + option + current[end + 1:] for option in options)
    return done


def _first_group(pattern: str) -> tuple[int, int, list[str]] | None:
    """(index of `{`, index of its `}`, the comma-separated options) of the first brace group that
    has a comma, or None."""
    for start, c in enumerate(pattern):
        if c != "{" or (start and pattern[start - 1] == "\\"):
            continue
        depth, options, piece = 0, [], start + 1
        for i in range(start + 1, len(pattern)):
            if pattern[i] == "{":
                depth += 1
            elif pattern[i] == "}" and depth:
                depth -= 1
            elif pattern[i] == "," and depth == 0:
                options.append(pattern[piece:i])
                piece = i + 1
            elif pattern[i] == "}":
                if options:
                    return start, i, options + [pattern[piece:i]]
                break
    return None


def _segment(segment: str) -> str | None:
    """One path segment as a regex; None when a `[` opens no bracket expression. `**` beside other
    characters is a `*`."""
    out: list[str] = []
    i = 0
    while i < len(segment):
        c = segment[i]
        if c == "*":
            if not out or out[-1] != "[^/]*":
                out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "\\" and i + 1 < len(segment):
            out.append(re.escape(segment[i + 1]))
            i += 2
        elif c == "[":
            first = i + 2 if segment[i + 1:i + 2] in ("!", "^") else i + 1
            close = segment.find("]", first + 1)
            if close == -1:
                return None
            negate = "^" if first == i + 2 else ""
            members = segment[first:close].replace("\\", "\\\\").replace("[", "\\[")
            out.append(f"(?!/)[{negate}{members}]")
            i = close + 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def _regex(body: str, anchored: bool) -> re.Pattern[str] | None:
    """A pattern without its leading and trailing slashes as a regex over paths relative to the base
    directory; None when it can match nothing."""
    segments = body.split("/")
    out = ["" if anchored or len(segments) > 1 else "(?:.*/)?"]
    for i, segment in enumerate(segments):
        last = i == len(segments) - 1
        if segment == "**":
            out.append(".*" if last else "(?:.*/)?")
            continue
        piece = _segment(segment)
        if piece is None:
            return None
        out.append(piece if last else piece + "/")
    try:
        return re.compile("".join(out) + r"\Z", re.IGNORECASE)
    except re.error:
        return None


def _matches(pattern: str, files: set[str], dirs: set[str]) -> bool:
    """Whether one expanded pattern matches a tracked file or a directory that holds one. With a
    trailing `/` only a directory counts."""
    body = pattern.lstrip("/").rstrip("/")
    regex = _regex(body, pattern.startswith("/")) if body else None
    if regex is None:
        return False
    return any(regex.match(c) for c in dirs) or (not pattern.endswith("/") and any(regex.match(c) for c in files))
