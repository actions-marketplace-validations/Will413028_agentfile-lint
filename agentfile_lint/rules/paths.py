"""R3b: a path written in backticks must exist among the tracked files.

Instruction files in subprojects write paths relative to their own directory or module, so a
reference is tried against several bases: the file's directory and each ancestor up to the root,
then the configured `base_dirs`; under each base also the `source_roots` prefixes and the
`resolve_extensions`. Only tracked files (and their directories) count as existing.

Heuristic by nature (false positives are expected), so it ships at `warn`.
"""
from __future__ import annotations

import posixpath
import re
from typing import Any

from ..context import Context
from ..discover import glob_to_regex
from ..errors import check_keys, expect_bool, expect_regex_list, expect_str_items, require_keys
from ..finding import Finding
from ._text import code_spans, prose_lines

ID = "R3b"
NAME = "path-refs"
DESCRIPTION = "paths referenced in backticks exist (multi-base resolution; heuristic)"
CHECKS = ((ID, NAME, DESCRIPTION),)

_KEYS = {
    "level", "base_dirs", "source_roots", "resolve_extensions", "file_extensions",
    "ignore_patterns", "ignore_negated_words", "check_bare_names",
}
_SHAPE = re.compile(r"[A-Za-z0-9_./@+-]+")  # a path-like token; anything else (spaces, <>, *, ...) is skipped
_SUFFIX = re.compile(r"(?::\d+(?:-\d+)?|#[\w-]+)$")


def validate(shared: None, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    params = _params(tables)
    return params, {ID: params}


def _params(tables: dict[str, dict[str, Any]]) -> dict[str, Any]:
    params = tables[ID]
    where = f"rules.{ID}"
    check_keys(params, _KEYS, where)
    require_keys(params, _KEYS - {"level"}, where)
    return {
        "level": params["level"],
        "base_dirs": expect_str_items(params["base_dirs"], f"{where}.base_dirs"),
        "source_roots": expect_str_items(params["source_roots"], f"{where}.source_roots"),
        "resolve_extensions": expect_str_items(params["resolve_extensions"], f"{where}.resolve_extensions"),
        "file_extensions": expect_str_items(params["file_extensions"], f"{where}.file_extensions"),
        "ignore_patterns": expect_regex_list(params["ignore_patterns"], f"{where}.ignore_patterns"),
        "ignore_negated_words": expect_str_items(params["ignore_negated_words"], f"{where}.ignore_negated_words"),
        "check_bare_names": expect_bool(params["check_bare_names"], f"{where}.check_bare_names"),
    }


def _candidate(span: str, params: dict[str, Any]) -> str | None:
    """The path to resolve, or None when the span is not a checkable path reference."""
    token = _SUFFIX.sub("", span.strip())
    if not token or not _SHAPE.fullmatch(token) or "://" in token or token[0] in "-@~/" or not re.search(r"[A-Za-z]", token):
        return None
    if any(re.search(p, token) for p in params["ignore_patterns"]):
        return None
    token = token.rstrip("/")
    ext = posixpath.splitext(token)[1].lstrip(".")
    if "/" not in token:
        if not params["check_bare_names"] or ext not in params["file_extensions"]:
            return None
    return token


def _bases(path: str, ctx: Context, params: dict[str, Any]) -> list[str]:
    here = posixpath.dirname(path)
    bases = [here]
    while here:
        here = posixpath.dirname(here)
        bases.append(here)
    for pattern in params["base_dirs"]:
        if any(ch in pattern for ch in "*?"):
            regex = glob_to_regex(pattern)
            bases.extend(sorted(d for d in ctx.dirs if d and regex.match(d)))
        elif pattern.strip("/") in ctx.dirs:
            bases.append(pattern.strip("/"))
    seen: set[str] = set()
    return [b for b in bases if not (b in seen or seen.add(b))]


def _exists(token: str, bases: list[str], ctx: Context, params: dict[str, Any]) -> bool:
    prefixes = [""] + [r.strip("/") for r in params["source_roots"]]
    for base in bases:
        for prefix in prefixes:
            cand = posixpath.normpath(posixpath.join(base, prefix, token))
            if cand.startswith(".."):
                continue
            if cand in ctx.tracked_set or cand in ctx.dirs:
                return True
            if any(cand + ext in ctx.tracked_set for ext in params["resolve_extensions"]):
                return True
    return False


def check_repo(ctx: Context, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    found: list[Finding] = []
    words = [w.lower() for w in params["ignore_negated_words"]]
    for path, text in ctx.files.items():
        bases: list[str] | None = None
        for number, line in prose_lines(text):
            if words and any(w in line.lower() for w in words):
                continue
            for span in code_spans(line):
                token = _candidate(span, params)
                if token is None:
                    continue
                if bases is None:
                    bases = _bases(path, ctx, params)
                if not _exists(token, bases, ctx, params):
                    found.append(Finding(path, number, ID, f"path `{token}` not found from this file's directory, its ancestors, the repo root or base_dirs"))
    return found
