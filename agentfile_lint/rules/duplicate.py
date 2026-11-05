"""R5a and R5b: identical lines across instruction files (docs/adr/0005).

A line (whitespace-collapsed, list marker removed) of at least `min_chars` characters that appears
in two files is duplicated text. If one file is in an ancestor directory of the other, the descendant
repeats what is already loaded: R5a, on the descendant's line. Which pairs count as ancestor and
descendant is `ancestor_pairs`: `same-name` (two files with the same name, the ancestor in a strict
ancestor directory, as one agent loads them) or `any` (also different names, and two files in one
directory). Every other pair is a sibling pair: R5b. Lines are grouped once: a line that repeats an
ancestor is never also reported as a sibling duplicate, even with R5a off. Both ids read
`[shared.duplicates]`. Exact matches only; the whole tracked instruction-file set is always compared,
never just the files named on the command line, except the files `exclude` matches: those are left out
of the comparison entirely (neither reported nor used as the ancestor text).
"""
from __future__ import annotations

import posixpath
import re
from typing import Any

from ..context import Context
from ..discover import matches
from ..errors import ConfigError, check_keys, expect_bool, expect_int, expect_regex_list, expect_str_list, require_keys
from ..finding import Finding
from ._text import parent_dirs, prose_lines

CHECKS = (
    ("R5a", "ancestor-duplicates", "lines a file repeats from a file in an ancestor directory"),
    ("R5b", "sibling-duplicates", "lines repeated across files that are not ancestor and descendant"),
)
_KEYS = {"ancestor_pairs", "min_chars", "ignore_headings", "ignore_patterns", "exclude"}
SHARED = ("duplicates", _KEYS)
_PAIRS = ("same-name", "any")
_MARKER = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_TABLE_RULE = re.compile(r"^\|?[\s:|-]+\|?$")
_REMOVED = {
    "sibling_level": "removed in 0.7.0; sibling duplicates are R5b, with its own level (docs/adr/0005)",
    # The 0.6 `[rules.R5]` keys; `exclude` is new in 0.8.0 and never lived there.
    **{key: "moved to [shared.duplicates] in 0.7.0 (docs/adr/0005)" for key in _KEYS - {"exclude"}},
}


def validate(shared: dict[str, Any], tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    for rule_id, table in tables.items():
        check_keys(table, {"level"}, f"rules.{rule_id}", _REMOVED)
    where = "shared.duplicates"
    require_keys(shared, sorted(_KEYS), where)
    params = {
        "ancestor_pairs": _expect_pairs(shared["ancestor_pairs"], f"{where}.ancestor_pairs"),
        "min_chars": expect_int(shared["min_chars"], f"{where}.min_chars"),
        "ignore_headings": expect_bool(shared["ignore_headings"], f"{where}.ignore_headings"),
        "ignore_patterns": expect_regex_list(shared["ignore_patterns"], f"{where}.ignore_patterns"),
        "exclude": expect_str_list(shared["exclude"], f"{where}.exclude", allow_empty=True),
    }
    return params, {rule_id: {} for rule_id in tables}  # the parameters are all in [shared.duplicates]


def _expect_pairs(value: Any, where: str) -> str:
    if value not in _PAIRS:
        raise ConfigError(f"{where}: expected one of {', '.join(_PAIRS)}")
    return value


def _normalize(line: str) -> str:
    return re.sub(r"\s+", " ", _MARKER.sub("", line.strip()))


def _is_ancestor(a: str, b: str) -> bool:
    """File `a` sits in an ancestor directory of `b`, or in the same directory (and sorts first)."""
    da, db = posixpath.dirname(a), posixpath.dirname(b)
    if da == db:
        return a < b
    return da == "" or db.startswith(da + "/")


def _is_same_name_ancestor(a: str, b: str) -> bool:
    """File `a` has the name of `b` and sits in a strict ancestor directory of `b`."""
    return posixpath.basename(a) == posixpath.basename(b) and posixpath.dirname(a) in parent_dirs(b)


def check_repo(ctx: Context, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    ignore = [re.compile(p) for p in params["ignore_patterns"]]
    groups: dict[str, dict[str, int]] = {}  # normalized line -> {path: first line number}
    for path, text in ctx.files.items():
        if params["exclude"] and matches(path, params["exclude"]):
            continue
        for number, raw in prose_lines(text):
            if params["ignore_headings"] and raw.lstrip().startswith("#"):
                continue
            line = _normalize(raw)
            if len(line) < params["min_chars"] or _TABLE_RULE.match(line) or any(i.search(line) for i in ignore):
                continue
            groups.setdefault(line, {}).setdefault(path, number)
    found: list[Finding] = []
    is_ancestor = _is_same_name_ancestor if params["ancestor_pairs"] == "same-name" else _is_ancestor
    for line, where in groups.items():
        if len(where) < 2:
            continue
        shown = line if len(line) <= 60 else line[:57] + "..."
        for path, number in where.items():
            ancestors = sorted((o for o in where if o != path and is_ancestor(o, path)), key=lambda o: (-len(posixpath.dirname(o)), o))
            if ancestors:  # grouped once: never also a sibling duplicate, whatever R5a's level
                if levels["R5a"] != "off":
                    found.append(Finding(path, number, "R5a", f"line repeats {ancestors[0]}:{where[ancestors[0]]} ({shown!r}); keep it in the ancestor only"))
                continue
            others = [o for o in where if o != path and not is_ancestor(path, o)]
            if others and levels["R5b"] != "off":
                names = ", ".join(f"{o}:{where[o]}" for o in sorted(others)[:3])
                more = f" and {len(others) - 3} more" if len(others) > 3 else ""
                found.append(Finding(path, number, "R5b", f"line also appears in sibling file(s) {names}{more} ({shown!r})"))
    return found
