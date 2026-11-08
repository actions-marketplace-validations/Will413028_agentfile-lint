"""R1a to R1e: size (docs/adr/0005). One computation, five ids, each with its own level:

- R1a (`file-bytes`) and R1b (`file-lines`): per-file limits chosen by path glob (first match wins in
  each id's own `limits`), counted on the text as stored on disk minus `[shared.size] excluded_blocks`.
- R1c (`path-bytes`): the combined size of a file and the files matching the same glob in its ancestor
  directories, the set an agent loads from the root down (Codex stops at 32 KiB in total). Every entry
  applies. Sizes are the bytes stored on disk, as the agent reads them (no block removal). The finding
  is on the file where the total first exceeds the limit, not on the files below it.
- R1d (`line-length`): characters per line outside the excluded blocks.
- R1e (`file-chars`): characters per file (code points, as `wc -m` counts, a CR included) after removing
  the frontmatter and block-level HTML comments and trimming surrounding whitespace, the text Claude
  Code measures against its per-file limit; `excluded_blocks` does not apply (the agent reads them).
  Limits by path glob, first match wins; an entry without `max_chars` sets no limit, and an entry with
  `frontmatter_key` matches only a file whose frontmatter parses and has that top-level key.
"""
from __future__ import annotations

import posixpath
import re
from typing import Any

from .. import frontmatter
from ..context import Context, normalize_newlines
from ._text import LINE_END, parent_dirs, split_lines
from ..discover import glob_to_regex
from ..errors import ConfigError, check_keys, expect_int, expect_str, expect_table_list, require_keys
from ..finding import Finding

CHECKS = (
    ("R1a", "file-bytes", "bytes per file, limits by path glob (first match wins)"),
    ("R1b", "file-lines", "lines per file, limits by path glob (first match wins)"),
    ("R1c", "path-bytes", "combined bytes of a file and the same-glob files in its ancestor directories"),
    ("R1d", "line-length", "characters per line"),
    ("R1e", "file-chars", "characters per file without frontmatter and block HTML comments, limits by path glob"),
)
# Ids whose findings are about a whole file (line 0); a per-line directive cannot name them.
WHOLE_FILE = ("R1a", "R1b", "R1c", "R1e")
SHARED = ("size", {"excluded_blocks"})

_LIMIT_KEY = {"R1a": "max_bytes", "R1b": "max_lines", "R1c": "max_bytes"}
_SHARED_HINT = "moved to [shared.size] in 0.7.0 (docs/adr/0005)"
_REMOVED = {
    "bytes_level": "removed in 0.7.0; per-file bytes are R1a, with its own level (docs/adr/0005)",
    "lines_level": "removed in 0.7.0; per-file lines are R1b, with its own level (docs/adr/0005)",
    "path_limits": "removed in 0.7.0; the combined size on a path is R1c, in [[rules.R1c.limits]] (docs/adr/0005)",
    "max_line_chars": "removed in 0.7.0; line length is R1d, with `max_chars` (docs/adr/0005)",
    "excluded_blocks": _SHARED_HINT,
}
_ENTRY_REMOVED = {
    **_REMOVED,
    "level": "removed in 0.7.0; each id has one level, set in its [rules.<id>] table (docs/adr/0005)",
}
# A key of the other per-file id: the 0.6.0 `limits` entry held both.
_OTHER_ID = {
    "max_lines": "per-file lines are R1b in 0.7.0: move it to a [[rules.R1b.limits]] entry (docs/adr/0005)",
    "max_bytes": "per-file bytes are R1a in 0.7.0: move it to a [[rules.R1a.limits]] entry (docs/adr/0005)",
}
_TABLE_REMOVED = {
    **_REMOVED,
    "max_bytes": "a limit goes in a [[rules.<id>.limits]] entry with a glob: R1a for one file, R1c for a path "
    "(the root/subproject/nested tiers were removed in 0.3.0; docs/adr/0005)",
}


def validate(shared: dict[str, Any], tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    require_keys(shared, ["excluded_blocks"], "shared.size")
    blocks = shared["excluded_blocks"]
    if not isinstance(blocks, list):
        raise ConfigError("shared.size.excluded_blocks: expected a list of {begin, end} tables")
    for i, block in enumerate(blocks):
        at = f"shared.size.excluded_blocks[{i}]"
        check_keys(block, {"begin", "end"}, at)
        require_keys(block, ["begin", "end"], at)
        for key in ("begin", "end"):
            expect_str(block[key], f"{at}.{key}")
    params: dict[str, Any] = {"excluded_blocks": blocks}
    for rule_id, key in _LIMIT_KEY.items():
        where = f"rules.{rule_id}"
        table = tables[rule_id]
        check_keys(table, {"level", "limits"}, where, {"max_lines": _OTHER_ID["max_lines"], **_TABLE_REMOVED})
        require_keys(table, ["limits"], where)
        limits = []
        for i, raw in enumerate(expect_table_list(table["limits"], f"{where}.limits")):
            at = f"{where}.limits[{i}]"
            other = {k: v for k, v in _OTHER_ID.items() if k != key}
            check_keys(raw, {"glob", key}, at, {**_ENTRY_REMOVED, **other})
            require_keys(raw, ["glob", key], at)
            limits.append({"glob": expect_str(raw["glob"], f"{at}.glob"), key: expect_int(raw[key], f"{at}.{key}")})
        params[rule_id] = limits
    table = tables["R1d"]
    check_keys(table, {"level", "max_chars"}, "rules.R1d", _TABLE_REMOVED)
    if table["level"] != "off":
        require_keys(table, ["max_chars"], "rules.R1d")
    params["R1d"] = expect_int(table["max_chars"], "rules.R1d.max_chars") if "max_chars" in table else None
    params["R1e"] = _char_limits(tables["R1e"])
    effective: dict[str, dict[str, Any]] = {rule_id: {"limits": params[rule_id]} for rule_id in (*_LIMIT_KEY, "R1e")}
    effective["R1d"] = {} if params["R1d"] is None else {"max_chars": params["R1d"]}
    return params, effective


def _char_limits(table: dict[str, Any]) -> list[dict[str, Any]]:
    check_keys(table, {"level", "limits"}, "rules.R1e")
    require_keys(table, ["limits"], "rules.R1e")
    limits = []
    for i, raw in enumerate(expect_table_list(table["limits"], "rules.R1e.limits")):
        at = f"rules.R1e.limits[{i}]"
        check_keys(raw, {"glob", "max_chars", "frontmatter_key"}, at)
        require_keys(raw, ["glob"], at)
        entry: dict[str, Any] = {"glob": expect_str(raw["glob"], f"{at}.glob")}
        if "max_chars" in raw:
            entry["max_chars"] = expect_int(raw["max_chars"], f"{at}.max_chars")
        if "frontmatter_key" in raw:
            entry["frontmatter_key"] = expect_str(raw["frontmatter_key"], f"{at}.frontmatter_key")
        limits.append(entry)
    return limits


def _block_patterns(params: dict[str, Any]) -> list[re.Pattern[str]]:
    # The block and one trailing line ending (LF, CRLF or a lone CR), matched non-greedily across lines.
    return [
        re.compile(re.escape(b["begin"]) + ".*?" + re.escape(b["end"]) + "(?:\r\n|\r|\n)?", re.DOTALL)
        for b in params["excluded_blocks"]
    ]


_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")  # one line on disk with its ending


def limit_for(path: str, limits: list[dict[str, Any]]) -> dict[str, Any]:
    """The first `limits` entry whose glob matches; no match means no size limit."""
    for entry in limits:
        if glob_to_regex(entry["glob"]).match(path):
            return entry
    return {}


def _block_spans(raw: str, params: dict[str, Any]) -> list[tuple[int, int]]:
    """Character spans of the excluded blocks in the raw text, merged where they overlap."""
    spans = sorted(m.span() for p in _block_patterns(params) for m in p.finditer(raw) if m.end() > m.start())
    return _complement(_complement(spans, len(raw)), len(raw))


def _complement(spans: list[tuple[int, int]], size: int) -> list[tuple[int, int]]:
    kept, pos = [], 0
    for start, end in sorted(spans):
        if start > pos:
            kept.append((pos, start))
        pos = max(pos, end)
    if pos < size:
        kept.append((pos, size))
    return kept


def check_repo(ctx: Context, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    found: list[Finding] = []
    if any(levels[rule_id] != "off" for rule_id in ("R1a", "R1b", "R1d", "R1e")):
        for path in sorted(ctx.raw):
            found.extend(_check_file(path, ctx.raw[path], params, levels))
    if levels["R1c"] == "off":
        return found
    sizes = {p: len(text.encode("utf-8")) for p, text in ctx.raw.items()}  # bytes on disk
    for entry in params["R1c"]:
        pattern = glob_to_regex(entry["glob"])
        matched = {p: n for p, n in sizes.items() if pattern.match(p)}
        by_dir: dict[str, list[str]] = {}
        for p in sorted(matched):
            by_dir.setdefault(posixpath.dirname(p), []).append(p)
        limit = entry["max_bytes"]
        for path in sorted(matched):
            ancestors = [a for d in reversed(parent_dirs(path)) for a in by_dir.get(d, [])]  # root first
            before = sum(matched[a] for a in ancestors)
            total = before + matched[path]
            if total <= limit or before > limit:  # within the limit, or the overflow starts above
                continue
            if ancestors:
                message = f"file and its ancestors ({', '.join(ancestors)}) total {total} bytes, limit {limit}"
            else:
                message = f"file is {total} bytes, limit {limit}"
            found.append(Finding(path, 0, "R1c", message))
    return found


def _check_file(path: str, raw: str, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    """Single-file limits on the text as stored on disk (CRLF counts two bytes), minus excluded blocks."""
    spans = _block_spans(raw, params)
    body = "".join(raw[start:end] for start, end in _complement(spans, len(raw)))
    found: list[Finding] = []
    max_bytes = limit_for(path, params["R1a"]).get("max_bytes")
    size = len(body.encode("utf-8"))  # raw bytes outside the blocks
    if max_bytes is not None and size > max_bytes:
        found.append(Finding(path, 0, "R1a", f"file is {size} bytes, limit {max_bytes}"))
    max_lines = limit_for(path, params["R1b"]).get("max_lines")
    # Each kept piece's endings become LF before joining, so a lone CR before a block and the LF after it
    # never merge into one CRLF and hide a line.
    lines = len(split_lines("".join(LINE_END.sub("\n", raw[s:e]) for s, e in _complement(spans, len(raw)))))
    if max_lines is not None and lines > max_lines:
        found.append(Finding(path, 0, "R1b", f"file is {lines} lines, limit {max_lines}"))
    if levels["R1e"] != "off":
        found.extend(_check_chars(path, raw, params["R1e"]))
    max_chars = params["R1d"]
    if max_chars is None or levels["R1d"] == "off":
        return found
    # Line numbers are the lines on disk (LF, CRLF or CR, as `grep -n` and annotations count them); only
    # the characters outside the blocks count toward a line's length, so a line wholly inside a block is
    # never reported. Lines and spans are both in order, so one moving index walks the spans.
    i = 0
    for number, m in enumerate(_LINE.finditer(raw), start=1):
        start, end = m.start(), m.start() + len(m.group().rstrip("\r\n"))
        while i < len(spans) and spans[i][1] <= start:
            i += 1
        length = end - start
        for s_start, s_end in spans[i:]:
            if s_start >= end:
                break
            length -= min(s_end, end) - max(s_start, start)
        if length > max_chars:
            found.append(Finding(path, number, "R1d", f"line is {length} characters, limit {max_chars}"))
    return found


# JavaScript's String.prototype.trim set (WhiteSpace and LineTerminator), which Claude Code applies:
# unlike str.strip() it removes U+FEFF and keeps U+001C to U+001F and U+0085.
_JS_SPACE = "\t\n\v\f\r \u00a0\u1680\u2028\u2029\u202f\u205f\u3000\ufeff" + "".join(map(chr, range(0x2000, 0x200B)))
_FENCE_OPEN = re.compile(r" {0,3}(`{3,}|~{3,})")
_COMMENT_START = re.compile(r" {0,3}<!--")
_COMMENT_END = re.compile(r"<!--(?:-?>|.*?-->)", re.DOTALL)  # CommonMark: `<!-->` and `<!--->` are closed
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ENDINGS = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)*")  # rest of the line and the empty lines after it


def _check_chars(path: str, raw: str, limits: list[dict[str, Any]]) -> list[Finding]:
    entry = next((e for e in limits if glob_to_regex(e["glob"]).match(path) and _has_key(raw, e)), {})
    max_chars = entry.get("max_chars")
    if max_chars is None:
        return []
    size = len(char_text(raw))
    return [Finding(path, 0, "R1e", f"file is {size} characters, limit {max_chars}")] if size > max_chars else []


def _has_key(raw: str, entry: dict[str, Any]) -> bool:
    key = entry.get("frontmatter_key")
    if key is None:
        return True
    parsed = frontmatter.parse(normalize_newlines(raw), strings=True)
    return parsed is not None and parsed.error is None and isinstance(parsed.value, dict) and key in parsed.value


def char_text(raw: str) -> str:
    """The text R1e counts: `raw` (endings as stored) without the frontmatter and the block-level HTML
    comments, trimmed. Comment blocks follow Claude Code's Markdown lexer at the top level: a line that
    starts (after up to 3 spaces, outside a fenced code block) with `<!--` opens one, which ends at the
    end of the line holding its `-->` plus the empty lines after it; its comments are removed, and the
    rest is kept only when it is not blank. An unclosed comment is kept. A comment line indented by up to
    3 spaces inside a list item is removed here too, where the lexer would keep it (it counts a few
    characters less); one after a block quote's `>` is kept, as by the lexer."""
    text = _without_frontmatter(raw)
    out: list[str] = []
    fence: str | None = None
    pos = 0
    while pos < len(text):
        m = _LINE.match(text, pos)
        line = m.group()
        body = line.rstrip("\r\n")
        if fence is not None:
            stripped = body.lstrip(" ")
            if len(body) - len(stripped) <= 3 and stripped.startswith(fence) and not stripped.lstrip(fence[0]).strip():
                fence = None
        elif (opened := _FENCE_OPEN.match(body)) is not None and not (opened.group(1)[0] == "`" and "`" in body[opened.end():]):
            fence = opened.group(1)
        elif _COMMENT_START.match(body) is not None:
            start = body.index("<!--")
            closed = _COMMENT_END.match(text, pos + start)
            if closed is None:  # unclosed: the rest of the file is one HTML block that keeps its text
                out.append(text[pos:])
                break
            end = _ENDINGS.match(text, closed.end()).end()
            rest = _COMMENT.sub("", text[pos:end])
            if rest.strip(_JS_SPACE):
                out.append(rest)
            pos = end
            continue
        out.append(line)
        pos = m.end()
    return "".join(out).strip(_JS_SPACE)


def _without_frontmatter(raw: str) -> str:
    """`raw` after the frontmatter block `frontmatter.split` finds (an optional BOM included), line
    endings kept as stored. No closing line means no frontmatter."""
    found = frontmatter.split(normalize_newlines(raw))
    if found is None or found[1] == 0:
        return raw
    text = raw.removeprefix("\ufeff")
    for number, m in enumerate(_LINE.finditer(text), start=1):  # the same LF, CRLF and CR line ends
        if number == found[1]:
            return text[m.end():]
    return raw
