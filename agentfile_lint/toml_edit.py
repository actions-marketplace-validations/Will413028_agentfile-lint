"""Find `[[allowlist.entries]]` blocks and their `count` line in the text of a TOML file.

Not a TOML parser (the checker has no TOML writer, and the standard library none either): it reads
lines, so a multi-line string or array can fool it. Every edit built from what it finds goes through
`fix.toml_checked` (safety net 1), which re-parses the result; when it is fooled, the fix is dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .rules._text import split_lines

_ENTRY = re.compile(r"[ \t]*\[\[[ \t]*allowlist[ \t]*\.[ \t]*entries[ \t]*\]\][ \t]*(?:#.*)?")
# Any line that looks like a table or array-of-tables header ends the block before it.
_HEADER = re.compile(r"[ \t]*\[.*\][ \t]*(?:#.*)?")
_COUNT = re.compile(r"[ \t]*count[ \t]*=[ \t]*(?P<value>[0-9]+)[ \t]*(?:#.*)?")
_BLANK = re.compile(r"[ \t]*")
_COMMENT = re.compile(r"[ \t]*#.*")


@dataclass(frozen=True)
class Block:
    header: int         # 1-based line of `[[allowlist.entries]]`
    last: int           # last line of the entry's own keys (trailing blank and comment lines excluded)
    removal_start: int  # first line a removal takes: the header, plus the blank lines before it at the end of the file
    removal_end: int    # last line a removal takes: `last` plus the blank lines after it
    count: tuple[int, int, int] | None  # (line, first column, column after the digits) of `count = N`


def entry_blocks(text: str, entries: int) -> list[Block] | None:
    """The blocks of the `[[allowlist.entries]]` headers, in order; None unless there are exactly
    `entries` of them (an inline array, a quoted key or a header inside a string)."""
    lines = split_lines(text)
    headers = [i for i, line in enumerate(lines) if _ENTRY.fullmatch(line)]
    if len(headers) != entries:
        return None
    blocks: list[Block] = []
    for i in headers:
        stop = next((j for j in range(i + 1, len(lines)) if _HEADER.fullmatch(lines[j])), len(lines))
        last = stop - 1
        while last > i and (_BLANK.fullmatch(lines[last]) or _COMMENT.fullmatch(lines[last])):
            last -= 1
        removal_end = last
        while removal_end + 1 < stop and _BLANK.fullmatch(lines[removal_end + 1]):
            removal_end += 1
        removal_start = i
        if removal_end == len(lines) - 1:  # the last block: leave no blank lines at the end of the file
            while removal_start > 0 and _BLANK.fullmatch(lines[removal_start - 1]):
                removal_start -= 1
        count = None
        for j in range(i + 1, last + 1):
            m = _COUNT.fullmatch(lines[j])
            if m:
                count = (j + 1, m.start("value") + 1, m.end("value") + 1)
                break
        blocks.append(Block(i + 1, last + 1, removal_start + 1, removal_end + 1, count))
    return blocks
