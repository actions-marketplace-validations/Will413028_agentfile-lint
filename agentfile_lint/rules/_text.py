"""Shared text helpers for rules: skip fenced code and HTML comments, find inline code spans."""
from __future__ import annotations

import posixpath
import re
from typing import Iterator

_FENCE = re.compile(r"\s*(`{3,}|~{3,})")
_COMMENT = re.compile(r"<!--.*?-->")
SPAN = re.compile(r"`([^`\n]+)`")
LINE_END = re.compile(r"\r\n|\r|\n")


def split_lines(text: str) -> list[str]:
    """Lines as `grep -n` and editors count them: only LF, CRLF and a lone CR end a line (never form
    feed, U+2028 or the other breaks `str.splitlines` knows); a final line ending adds no empty line."""
    lines = LINE_END.split(text)
    if lines[-1] == "":
        lines.pop()
    return lines


def parent_dirs(path: str) -> list[str]:
    """Directories strictly above the directory of `path`, nearest first; the root is ""."""
    out: list[str] = []
    d = posixpath.dirname(path)
    while d:
        d = posixpath.dirname(d)
        out.append(d)
    return out


def prose_lines(text: str) -> Iterator[tuple[int, str]]:
    """(1-based line number, line) for lines outside fenced code blocks; HTML comments are cut out."""
    for number, _, line in prose_lines_raw(text):
        yield number, line


def prose_lines_raw(text: str) -> Iterator[tuple[int, str, str]]:
    """`prose_lines` with the line as written: (number, raw line, line with HTML comments cut out).
    A line that is all inside a comment opened on an earlier line is skipped."""
    fence: str | None = None
    in_comment = False
    for number, raw in enumerate(split_lines(text), start=1):
        line = raw
        if in_comment:
            end = line.find("-->")
            if end < 0:
                continue
            line = line[end + 3:]
            in_comment = False
        if fence is not None:
            closing = raw.strip()
            if closing and set(closing) == {fence[0]} and len(closing) >= len(fence):
                fence = None
            continue
        m = _FENCE.match(line)
        if m:
            fence = m.group(1)
            continue
        line = _COMMENT.sub("", line)
        start = line.find("<!--")
        if start >= 0:
            line = line[:start]
            in_comment = True
        yield number, raw, line


def code_spans(line: str) -> Iterator[str]:
    for m in SPAN.finditer(line):
        yield m.group(1)
