"""Applying fixes: `--fix`, `--unsafe-fixes` and `--diff` (docs/design.md, Fixes).

A rule attaches a `finding.Fix` to a finding; this module turns the fixes of one run into new file
texts. Two safety nets, each a single path:

1. `toml_checked`: a fix that edits TOML is attached only when the edited text, parsed again, differs
   from the original in the target alone (a rule calls it when it builds the fix); otherwise the
   finding keeps its message and gets no fix, which leaves a suggestion only.
2. `plan`: after each pass of edits, the run is repeated on the new texts; the findings it suppresses
   (by directive or allowlist entry) must be among those suppressed before, line numbers moved by the
   edits. Otherwise nothing is written.
"""
from __future__ import annotations

import difflib
import os
import re
import tomllib
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .finding import SAFE, Edit, Finding, Fix
from .rules._text import LINE_END, split_lines


def _offsets(text: str) -> list[int]:
    """Offset of the start of each line, plus one past the end for the line after the last one."""
    starts = [0] + [m.end() for m in LINE_END.finditer(text)]
    if starts[-1] != len(text):
        starts.append(len(text))
    return starts


def _offset(starts: list[int], where: tuple[int, int], text: str) -> int:
    line, column = where
    if not 1 <= line <= len(starts):
        raise ValueError(f"line {line} is outside the file")
    base = starts[line - 1]
    stop = starts[line] if line < len(starts) else len(text)
    if base + column - 1 > stop:
        raise ValueError(f"column {column} is outside line {line}")
    return base + column - 1


def apply_edits(text: str, edits: Iterable[Edit]) -> str:
    """`text` with `edits` applied; the edits must not overlap."""
    starts = _offsets(text)
    spans = sorted((_offset(starts, e.start, text), _offset(starts, e.end, text), e.text) for e in edits)
    out: list[str] = []
    done = 0
    for begin, end, new in spans:
        if begin < done:
            raise ValueError("overlapping edits")
        out += [text[done:begin], new]
        done = end
    out.append(text[done:])
    return "".join(out)


def line_delete(path: str, text: str, first: int, last: int) -> Edit:
    """An edit that removes lines `first` to `last` (1-based, inclusive) of `text` with their line
    endings. When `last` is the file's last line and has no line ending, the ending before `first` goes
    instead, so no two lines are joined."""
    lines = split_lines(text)
    has_final_newline = text.endswith(("\n", "\r"))
    if last < len(lines) or has_final_newline:
        return Edit(path, (first, 1), (last + 1, 1), "")
    if first == 1:
        return Edit(path, (1, 1), (last, len(lines[last - 1]) + 1), "")
    return Edit(path, (first - 1, len(lines[first - 2]) + 1), (last, len(lines[last - 1]) + 1), "")


def toml_checked(text: str, edits: tuple[Edit, ...], expected: dict[str, Any]) -> bool:
    """Safety net 1: the edited TOML must parse to `expected`, the original parse with only the
    target changed (empty tables and arrays the edit leaves behind count as absent)."""
    try:
        after = tomllib.loads(apply_edits(text, edits))
    except (tomllib.TOMLDecodeError, ValueError):
        return False
    return _pruned(after) == _pruned(expected)


def _pruned(value: Any) -> Any:
    if isinstance(value, dict):
        out = {k: _pruned(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in ({}, [])}
    if isinstance(value, list):
        return [_pruned(v) for v in value]
    return value


def line_moves(old: str, edits: list[Edit], new: str) -> dict[int, int | None]:
    """Old line number -> its line number in `new` (`old` with `edits` applied); None for a line whose
    whole content and line ending the edits removed. Exact: computed from both texts."""
    starts = _offsets(old)
    spans = sorted((_offset(starts, e.start, old), _offset(starts, e.end, old), e.text) for e in edits)
    new_starts = [0] + [m.end() for m in LINE_END.finditer(new)]
    out: dict[int, int | None] = {}
    for number, line in enumerate(split_lines(old), start=1):
        line_start = starts[number - 1]
        content_end = line_start + len(line)
        has_ending = content_end < len(old)
        shift = 0  # length change from the edits before the line
        new_pos = None
        for begin, end, text in spans:
            if end <= line_start:
                shift += len(text) - (end - begin)
                continue
            if begin <= line_start:  # the line starts inside this edit
                if content_end < end or (content_end == end and not has_ending):
                    out[number] = None  # content and line ending gone
                    break
                new_pos = begin + shift + len(text)  # the rest of the line follows the replacement
            break
        if number not in out:
            out[number] = bisect_right(new_starts, new_pos if new_pos is not None else line_start + shift)
    return out


def widened(before: Iterable, after: Iterable) -> list[str]:
    """Allowlist entries (`rule`, `path`, `count`) in `after` that accept more than `before` did:
    new ones and raised counts, as "rule path". Exceptions only shrink (docs/adr/0005)."""
    old = {(e.rule, e.path): e.count for e in before}
    return sorted(f"{e.rule} {e.path}" for e in after if old.get((e.rule, e.path), 0) < e.count)


class Rejected(Exception):
    """The fixes cannot be applied (the re-run on the edited texts failed, or an edit does not fit)."""


@dataclass
class Plan:
    texts: dict[str, tuple[str, str]]  # edited path -> (old text, new text)
    fixed: int                          # fixes applied, over every pass
    held_unsafe: int                    # unsafe fixes left out (no --unsafe-fixes)
    skipped: list[str]                  # why some fixes, or all, were not applied
    findings: list[Finding] | None     # the findings of the run on the new texts (None: nothing applied)


# Fixes can uncover fixes (a directive that was stacked becomes unused once the one below it goes):
# like ruff, apply them again on the result until no fix is left, at most this many times.
MAX_PASSES = 10

Rerun = Callable[[dict[str, str]], tuple[list[Finding], list[Finding], dict[str, str]]]


def plan(
    findings: list[Finding],
    suppressed: list[Finding],
    texts: dict[str, str],
    unsafe: bool,
    rerun: Rerun,
) -> Plan:
    """Choose the fixes, apply them in memory and check safety net 2 after every pass.

    `texts` holds the text each fix's edits were computed on (the analyzed files and the loaded config,
    as stored). `rerun(current)` analyzes again with `current` (path -> text) in place of the files on
    disk and returns (findings, suppressed, texts), the same three for the edited state."""
    original: dict[str, str] = {}
    current: dict[str, str] = {}
    origin: dict[str, dict[int, int]] = {}  # path -> line now -> line in the original text
    fixed = 0
    skipped: list[str] = []
    for _ in range(MAX_PASSES):
        fixes = _choose(findings, unsafe)
        if not fixes:
            break
        edits: dict[str, list[Edit]] = {}
        for f in fixes:
            if _add(edits, f.fix.edits):
                fixed += 1
        try:
            edits = {path: _to_end_of_file(texts[path], file_edits) for path, file_edits in edits.items()}
            new = {path: apply_edits(texts[path], file_edits) for path, file_edits in edits.items()}
        except (KeyError, ValueError) as exc:  # an edit outside the text it was computed on
            return Plan({}, 0, 0, [f"no fix applied: {exc}"], None)
        for path in new:
            original.setdefault(path, texts[path])
        try:
            after, after_suppressed, after_texts = rerun({**current, **new})
        except Rejected as exc:
            return Plan({}, 0, 0, [f"no fix applied: {exc}"], None)
        moves = {path: line_moves(texts[path], edits[path], new[path]) for path in new}
        grown = _newly_suppressed(suppressed, after_suppressed, moves)
        if grown:
            # Name lines as the files on disk number them: back through every pass.
            grown = [(p, origin.get(p, {}).get(line, line) if line else line, rule) for p, line, rule in grown]
            names = ", ".join(f"{p}:{line} {rule}" if line else f"{p} {rule}" for p, line, rule in grown)
            return Plan({}, 0, 0, [f"no fix applied: the fixes would suppress findings that are reported now ({names})"], None)
        for path, m in moves.items():
            back = origin.get(path, {})
            origin[path] = {now: back.get(old, old) for old, now in m.items() if now is not None}
        current.update(new)
        findings, suppressed, texts = after, after_suppressed, after_texts
    else:
        if _choose(findings, unsafe):
            skipped.append(f"fixes are left after {MAX_PASSES} passes; run --fix again")
    held = len({f.fix for f in findings if f.fix is not None and f.fix.applicability != SAFE}) if not unsafe else 0
    if not current:
        return Plan({}, 0, held, skipped, None)
    changed = {p: (original[p], current[p]) for p in current if original[p] != current[p]}
    return Plan(changed, fixed, held, skipped, findings)


def _choose(findings: list[Finding], unsafe: bool) -> list[Finding]:
    """One finding per distinct fix (a directive whose every rule is unused carries one fix several times)."""
    seen: set[Fix] = set()
    out = []
    for f in findings:
        if f.fix is None or f.fix in seen or (f.fix.applicability != SAFE and not unsafe):
            continue
        seen.add(f.fix)
        out.append(f)
    return out


def _add(edits: dict[str, list[Edit]], new: tuple[Edit, ...]) -> bool:
    """Add one fix's edits unless one overlaps an edit already chosen; overlapping deletions merge
    (two removed allowlist entries may both take the blank line between them). The fix left out
    returns in the next pass."""
    merged = {e.path: list(edits.get(e.path, [])) for e in new}
    for e in new:
        file_edits = merged[e.path]
        if e in file_edits:  # the same edit from another fix: applied once
            continue
        for other in list(file_edits):
            if not (e.start < other.end and other.start < e.end):
                continue
            if e.text or other.text:
                return False
            file_edits.remove(other)
            e = Edit(e.path, min(e.start, other.start), max(e.end, other.end), "")
        file_edits.append(e)
    edits.update(merged)
    return True


def _to_end_of_file(text: str, edits: list[Edit]) -> list[Edit]:
    """A deletion from the start of a line to the end of the file also takes the blank lines before
    it, so removing the last entries or directives leaves no blank lines at the end (also when two
    removals merged)."""
    lines = split_lines(text)
    if not lines:
        return edits
    ends = {(len(lines) + 1, 1), (len(lines), len(lines[-1]) + 1)}  # after the last line ending, or at the end
    edits = sorted(edits, key=lambda e: e.start)
    while True:  # join deletions that touch end to start, extend the one at the end; until stable
        joined: list[Edit] = []
        for e in edits:
            if joined and not e.text and not joined[-1].text and joined[-1].end == e.start:
                e = Edit(e.path, joined[-1].start, e.end, "")
                joined.pop()
            joined.append(e)
        last = joined[-1]
        if not last.text and last.start[1] == 1 and last.end in ends:
            first = last.start[0]
            while first > 1 and not lines[first - 2].strip():
                first -= 1
            joined[-1] = Edit(last.path, (first, 1), last.end, "")
        if joined == edits:
            return joined
        edits = joined


def _newly_suppressed(before: list[Finding], after: list[Finding], moves: dict[str, dict]) -> list[tuple]:
    """Safety net 2: findings suppressed after the edits and not before, by (path, line, rule), line as
    numbered before the edits. The message is left out: it may quote a line number the edits moved."""
    old = Counter()
    for f in before:
        line = f.line
        if f.line and f.path in moves:
            line = moves[f.path].get(f.line)
            if line is None:
                continue
        old[(f.path, line, f.rule)] += 1
    grown = Counter((f.path, f.line, f.rule) for f in after) - old
    back = {path: {new: number for number, new in m.items() if new is not None} for path, m in moves.items()}
    return [(path, back.get(path, {}).get(line, line) if line else line, rule) for path, line, rule in sorted(grown)]


_KEEPENDS = re.compile(r"[^\n]*\n|[^\n]+$")


def _lines(text: str) -> list[str]:
    """Lines with their endings as patch tools split them: at LF only (a CRLF line keeps its CR, and a
    lone CR or U+2028 does not end a line), so `git apply` takes the diff."""
    return _KEEPENDS.findall(text)


def diff(texts: dict[str, tuple[str, str]]) -> str:
    """Unified diff of every changed file, `a/` and `b/` prefixed as git prints them."""
    out: list[str] = []
    for path in sorted(texts):
        old, new = texts[path]
        name = path.lstrip("/")
        for line in difflib.unified_diff(_lines(old), _lines(new), f"a/{name}", f"b/{name}"):
            out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(out)


def write(root: Path, texts: dict[str, tuple[str, str]]) -> None:
    """Write every edited file, or none: each must be writable before the first is written."""
    targets = {path: root / path for path in texts}
    for path, target in targets.items():
        if not os.access(target, os.W_OK):
            raise OSError(f"cannot write {path}: permission denied; no file was changed")
    for path, (_, new) in texts.items():
        targets[path].write_bytes(new.encode("utf-8"))
