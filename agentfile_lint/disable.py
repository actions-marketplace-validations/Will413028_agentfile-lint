"""Per-line suppression: `<!-- agentfile-lint-disable-next-line R5a, R4b -- reason -->` (docs/adr/0006).

A directive is a line of its own, outside fenced code. It drops the findings of the named rules on the
next line of the same file ("next line" as `rules._text.split_lines` counts lines). Rule ids or their
aliases and a reason after ` -- ` are required; whole-file rules (`WHOLE_FILE` in a rule module) are not
accepted, since their findings have no line. A malformed directive is an error and a directive that
drops nothing is a warning, both under the pseudo rule `disable`, which no level or override changes.
Suppressed findings never reach the allowlist, so they do not count toward an entry's `count`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .finding import Finding
from .rules import ALIASES, MODULES, RETIRED, RULES
from .rules._text import prose_lines_raw

RULE_ID = "disable"
DIRECTIVE = "agentfile-lint-disable-next-line"
WHOLE_FILE = frozenset(rule_id for module in MODULES for rule_id in getattr(module, "WHOLE_FILE", ()))

_MARK = "agentfile-lint-disable"
# Anything that starts like a directive is parsed, so a typo is reported instead of ignored. Up to three
# spaces of indent, as for an HTML block in CommonMark: four make an indented code block.
_START = re.compile(r" {0,3}<!--\s*agentfile-lint-disable")
_FULL = re.compile(r" {0,3}<!--\s*" + re.escape(DIRECTIVE) + r"(?:\s+(?P<body>.*?))?\s*-->\s*")


@dataclass(frozen=True)
class Directive:
    path: str
    line: int
    rules: frozenset[str]


def _parse(path: str, number: int, line: str) -> Directive | Finding:
    m = _FULL.fullmatch(line)
    if not m:
        return Finding(path, number, RULE_ID,
                       f"malformed directive; write <!-- {DIRECTIVE} <rule ids> -- <reason> --> on its own line")
    ids_part, sep, reason = (" " + (m.group("body") or "")).partition(" -- ")
    names = [n for n in re.split(r"[\s,]+", ids_part.strip()) if n]
    if not names:
        return Finding(path, number, RULE_ID, "directive names no rule id")
    if not sep or not reason.strip():
        return Finding(path, number, RULE_ID, "directive needs a reason after ' -- '")
    rules: set[str] = set()
    for name in names:
        rule = ALIASES.get(name, name)
        if name in RETIRED:
            return Finding(path, number, RULE_ID, RETIRED[name])
        if rule not in RULES:
            return Finding(path, number, RULE_ID, f"unknown rule {name!r}")
        if rule in WHOLE_FILE:
            return Finding(path, number, RULE_ID,
                           f"{rule} is a whole-file rule; use an allowlist entry or an override instead")
        rules.add(rule)
    return Directive(path, number, frozenset(rules))


def scan(path: str, text: str) -> tuple[list[Directive], list[Finding]]:
    """Directives in one file and findings for the malformed ones. Fenced code and multi-line HTML
    comments are skipped the way every text rule skips them (`rules._text.prose_lines`)."""
    directives: list[Directive] = []
    errors: list[Finding] = []
    if _MARK not in text:  # most files have no directive
        return directives, errors
    for number, raw, _ in prose_lines_raw(text):
        if _START.match(raw):
            parsed = _parse(path, number, raw)
            (directives if isinstance(parsed, Directive) else errors).append(parsed)
    # A directive covers the line right after it; another directive there would cover nothing.
    lines = {d.line for d in directives} | {e.line for e in errors}
    stacked = [d for d in directives if d.line + 1 in lines]
    for d in stacked:
        errors.append(Finding(path, d.line, RULE_ID, "directive is followed by another directive; "
                              "name all rules in the one right above the line"))
    return [d for d in directives if d not in stacked], errors


def apply(findings: list[Finding], files: dict[str, str]) -> list[Finding]:
    """Drop findings a directive covers; add errors for malformed directives and warnings for unused ones."""
    directives: list[Directive] = []
    notes: list[Finding] = []
    for path, text in files.items():
        found, errors = scan(path, text)
        directives += found
        notes += errors
    by_line = {(d.path, d.line + 1): d for d in directives}
    used: set[tuple[Directive, str]] = set()
    kept: list[Finding] = []
    for f in findings:
        d = by_line.get((f.path, f.line)) if f.line else None
        if d is not None and f.rule in d.rules:
            used.add((d, f.rule))
        else:
            kept.append(f)
    for d in directives:
        for rule in sorted(d.rules):
            if (d, rule) not in used:
                notes.append(Finding(d.path, d.line, RULE_ID,
                                     f"directive for {rule} suppresses nothing on the next line; remove it",
                                     level="warn"))
    return kept + notes
