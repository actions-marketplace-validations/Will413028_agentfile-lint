"""JSON as Claude Code reads its settings files and `.mcp.json` (docs/rules.md, H1 and M1).

Claude Code is a JavaScript program; `JSON.parse` rejects what Python's `json` accepts beyond the
standard (`NaN`, `Infinity`). Measured on Claude Code 2.1.318: a leading UTF-8 byte order mark is
read, and an empty or blank file sets nothing (`blank`).
"""
from __future__ import annotations

import json
from typing import Any, NamedTuple


class _NotJson(ValueError):
    pass


def _reject_constant(name: str) -> Any:
    raise _NotJson(f"{name} is not JSON")


def blank(text: str) -> bool:
    """An empty or blank file (a byte order mark aside), which Claude Code reads as nothing set."""
    return not text.removeprefix("\ufeff").strip()


class Problem(NamedTuple):
    """Why a file was not read: `invalid` JSON (at `line`, 0 when not known), or not checked at all."""

    line: int
    why: str
    invalid: bool = True


def load(text: str) -> tuple[Any, Problem | None]:
    """(value, None), or (None, problem). Integers are read as floats, as JavaScript reads every number:
    Python refuses to convert an integer of more than 4300 digits, which `JSON.parse` reads."""
    try:
        return json.loads(text.removeprefix("\ufeff"), parse_constant=_reject_constant, parse_int=float), None
    except json.JSONDecodeError as exc:
        return None, Problem(exc.lineno, f"{exc.msg} (line {exc.lineno}, column {exc.colno})")
    except _NotJson as exc:
        return None, Problem(0, str(exc))
    except RecursionError:
        return None, Problem(0, "nested too deeply for agentfile-lint to read; the file was not checked", invalid=False)


def kind(value: Any) -> str:
    """The JSON name of a value's type, for messages."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return {str: "string", list: "array", dict: "object"}[type(value)]
