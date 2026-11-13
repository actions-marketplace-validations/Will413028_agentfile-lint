"""YAML frontmatter of a Markdown file: the only module that uses the vendored PyYAML (`_yaml`).

A frontmatter block starts on the first line with `---` and ends at the next line that is exactly
`---`. It is parsed with PyYAML's `SafeLoader`, which builds plain data only (no Python objects).
With `strings=True` the block is only composed (grammar, anchors and aliases, never a tag's
constructor) and every scalar is its text: `yes` and `2026-02-30` stay strings, as YAML 1.2 readers
read them, and so does `12`, as strictyaml reads it (YAML 1.1 and the YAML 1.2 core schema read the
integer 12). Merge keys (`<<`) are applied; a duplicate key or a key that is not a scalar is an error,
as in YAML 1.2 readers. `keys` gives the line of each top-level key and `plain` says which top-level
values were written without quotes. Used by the SKILL.md and rule-file rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import _yaml
from ._yaml.reader import ReaderError

DELIMITER = "---"
MERGE_TAG = "tag:yaml.org,2002:merge"


@dataclass(frozen=True)
class Frontmatter:
    value: object = None        # the parsed YAML value when `error` is None (a dict for a mapping)
    error: str | None = None    # why the block could not be parsed, or None
    line: int = 1               # 1-based file line of the error (the opening `---` when unknown)
    column: int = 1             # 1-based column of the error
    end: int = 0                # 1-based line of the closing `---`; 0 when unterminated
    keys: dict[str, int] = field(default_factory=dict)  # `strings=True`: top-level key -> 1-based file line
    # `strings=True`: top-level key -> True for a plain (unquoted, not block) scalar, for a sequence one
    # such bool per item, else False. A plain scalar is where a typed reader may see a number or null.
    plain: dict[str, object] = field(default_factory=dict)


def split(text: str) -> tuple[str, int] | None:
    """(YAML text, 1-based line of the closing `---`), or None when the file has no frontmatter.

    `text` has LF newlines; a leading UTF-8 BOM is ignored. An opening `---` without a closing one
    returns ("", 0)."""
    text = text.removeprefix("\ufeff")
    if text != DELIMITER and not text.startswith(DELIMITER + "\n"):
        return None
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i] == DELIMITER:
            return "\n".join(lines[1:i]) + ("\n" if i > 1 else ""), i + 1
    return "", 0


def _position(body: str, offset: int) -> tuple[int, int]:
    """1-based file (line, column) of a character offset into the YAML text (which starts on line 2)."""
    before = body[:offset]
    return before.count("\n") + 2, offset - (before.rfind("\n") + 1) + 1


def _plain(node: object, memo: dict[int, object]) -> object:
    """A composed node as str, list and dict; an alias reuses the converted value, as SafeLoader does,
    so nested aliases cannot expand exponentially. A key must be a scalar."""
    if id(node) in memo:
        return memo[id(node)]
    if isinstance(node, _yaml.ScalarNode):
        out: object = node.value
    elif isinstance(node, _yaml.SequenceNode):
        out = []
        memo[id(node)] = out
        out.extend(_plain(item, memo) for item in node.value)
    else:
        out = {}
        memo[id(node)] = out
        merged: dict[str, object] = {}
        for key, value in node.value:
            if not isinstance(key, _yaml.ScalarNode):
                # SafeLoader rejects it as unhashable too; turning it into text would expand every alias.
                raise _yaml.MarkedYAMLError(problem="a mapping key is not a string", problem_mark=key.start_mark)
            if key.tag == MERGE_TAG:
                sources = value.value if isinstance(value, _yaml.SequenceNode) else [value]
                for source in sources:
                    if not isinstance(source, _yaml.MappingNode):
                        raise _yaml.MarkedYAMLError(problem="a merge key '<<' takes a mapping or a list of mappings",
                                                    problem_mark=source.start_mark)
                    for k, v in _plain(source, memo).items():   # the first source that has a key wins
                        merged.setdefault(k, v)
                continue
            if key.value in out:
                raise _yaml.MarkedYAMLError(problem=f"duplicate key {key.value!r}", problem_mark=key.start_mark)
            out[key.value] = _plain(value, memo)
        for k, v in merged.items():   # keys written in the mapping win over merged ones
            out.setdefault(k, v)
    memo[id(node)] = out
    return out


def _is_plain(node: object) -> object:
    if isinstance(node, _yaml.SequenceNode):
        return [isinstance(item, _yaml.ScalarNode) and item.style is None for item in node.value]
    return isinstance(node, _yaml.ScalarNode) and node.style is None


def _as_strings(body: str) -> tuple[object, dict[str, int], dict[str, object]]:
    node = _yaml.compose(body, Loader=_yaml.SafeLoader)
    if node is None:
        return None, {}, {}
    value = _plain(node, {})
    keys: dict[str, int] = {}
    plain: dict[str, object] = {}
    if isinstance(node, _yaml.MappingNode):
        merge_line = None
        for key, item in node.value:   # keys are scalars by now
            if key.tag == MERGE_TAG:
                merge_line = merge_line or key.start_mark.line + 2
            else:
                keys.setdefault(key.value, key.start_mark.line + 2)
                plain.setdefault(key.value, _is_plain(item))
        if merge_line is not None and isinstance(value, dict):
            for k in value:
                keys.setdefault(k, merge_line)
    return value, keys, plain


def parse(text: str, strings: bool = False) -> Frontmatter | None:
    """Parse the frontmatter of `text` (LF newlines); None when the file has none. `strings`: see the
    module docstring."""
    found = split(text)
    if found is None:
        return None
    body, end = found
    if end == 0:
        return Frontmatter(error="frontmatter has no closing '---' line")
    try:
        keys: dict[str, int] = {}
        plain: dict[str, object] = {}
        if strings:
            value, keys, plain = _as_strings(body)
        else:
            value = _yaml.load(body, Loader=_yaml.SafeLoader)
    except _yaml.MarkedYAMLError as exc:
        # Report the mark together with the text that describes it.
        if exc.problem_mark is not None:
            mark, reason = exc.problem_mark, exc.problem or exc.context
        else:
            mark, reason = exc.context_mark, exc.context or exc.problem
        reason = f"invalid YAML: {reason or 'cannot parse'}"
        if mark is None:
            return Frontmatter(error=reason, end=end)
        # The YAML text starts on file line 2, after the opening `---`.
        return Frontmatter(error=reason, line=mark.line + 2, column=mark.column + 1, end=end)
    except ReaderError as exc:  # a character YAML does not allow; no mark, an offset instead
        line, column = _position(body, exc.position)
        return Frontmatter(error=f"invalid YAML: unacceptable character #x{exc.character:04x}",
                           line=line, column=column, end=end)
    except _yaml.YAMLError as exc:
        return Frontmatter(error="invalid YAML: " + str(exc).split("\n")[0], end=end)
    except RecursionError:  # nesting deeper than the interpreter's recursion limit
        return Frontmatter(error="invalid YAML: nested too deeply", end=end)
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        # SafeLoader's scalar constructors raise these on values that pass the grammar but not the
        # conversion: `2026-02-30`, `!!int abc`, `!!timestamp foo`, integers over Python's digit limit.
        return Frontmatter(error="invalid YAML: cannot convert a value: " + str(exc).split("\n")[0], end=end)
    return Frontmatter(value=value, end=end, keys=keys, plain=plain)
