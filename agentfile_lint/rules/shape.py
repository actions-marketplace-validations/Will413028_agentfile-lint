"""R2: file shape. Files matching a glob must have the listed section headings, in order.

A shape is data: `glob`, `sections`, and optional extras (a required title, a one-line purpose,
bullet-only sections, patterns that must appear). The first shape whose glob matches a file applies.
"""
from __future__ import annotations

import re
from typing import Any

from ..discover import glob_to_regex
from ..errors import (
    ConfigError, check_keys, expect_bool, expect_int, expect_regex_list, expect_str,
    expect_str_items, expect_str_list, expect_table_list, require_keys,
)
from ..finding import Finding
from ._text import prose_lines

ID = "R2"
NAME = "shape"
DESCRIPTION = "required section headings in order (and optional title, purpose, bullet-only sections)"
CHECKS = ((ID, NAME, DESCRIPTION),)

_MODES = ("exact", "ordered")
_SHAPE_KEYS = {"glob", "sections", "mode", "heading_level", "title", "purpose", "bullets_only", "must_match"}


def validate(shared: None, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    params = _params(tables)
    return params, {ID: params}


def _params(tables: dict[str, dict[str, Any]]) -> dict[str, Any]:
    params = tables[ID]
    where = f"rules.{ID}"
    check_keys(params, {"level", "shapes"}, where)
    require_keys(params, ["shapes"], where)
    shapes = []
    for i, raw in enumerate(expect_table_list(params["shapes"], f"{where}.shapes")):
        at = f"{where}.shapes[{i}]"
        check_keys(raw, _SHAPE_KEYS, at)
        require_keys(raw, ["glob", "sections"], at)
        mode = raw.get("mode", "exact")
        if mode not in _MODES:
            raise ConfigError(f"{at}.mode: expected one of {', '.join(_MODES)}")
        level = expect_int(raw.get("heading_level", 2), f"{at}.heading_level")
        if level > 6:
            raise ConfigError(f"{at}.heading_level: expected 1 to 6")
        shapes.append({
            "glob": expect_str(raw["glob"], f"{at}.glob"),
            "sections": expect_str_list(raw["sections"], f"{at}.sections"),
            "mode": mode,
            "heading_level": level,
            "title": expect_bool(raw.get("title", False), f"{at}.title"),
            "purpose": expect_bool(raw.get("purpose", False), f"{at}.purpose"),
            "bullets_only": expect_str_items(raw.get("bullets_only", []), f"{at}.bullets_only"),
            "must_match": expect_regex_list(raw.get("must_match", []), f"{at}.must_match"),
        })
    return {"level": params["level"], "shapes": shapes}


def _quote(names: list[str]) -> str:
    return ", ".join(f'"{n}"' for n in names)


def _heading_re(level: int) -> re.Pattern[str]:
    return re.compile(r"^" + "#" * level + r"(?!#)[ \t]+(.*?)[ \t]*#*[ \t]*$")


def check(path: str, text: str, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    shape = next((s for s in params["shapes"] if glob_to_regex(s["glob"]).match(path)), None)
    if shape is None:
        return []
    found: list[Finding] = []
    lines = list(prose_lines(text))
    wanted: list[str] = shape["sections"]
    level = shape["heading_level"]
    pattern = _heading_re(level)
    headings = [(n, m.group(1).strip()) for n, line in lines if (m := pattern.match(line))]
    names = [h for _, h in headings]

    for section in wanted:
        if section not in names:
            found.append(Finding(path, 0, ID, f'missing section "{section}"'))
    if shape["mode"] == "exact":
        for number, name in headings:
            if name not in wanted:
                found.append(Finding(path, number, ID, f'unexpected section "{name}" (allowed: {_quote(wanted)})'))
    present = [w for w in wanted if w in names]
    order = [n for n in names if n in wanted]
    if len(set(order)) != len(order):
        dup = next(n for n in order if order.count(n) > 1)
        found.append(Finding(path, next(num for num, name in headings if name == dup), ID, f'duplicate section "{dup}"'))
    elif order != present:
        wrong = next(o for o, p in zip(order, present) if o != p)
        line = next(num for num, name in headings if name == wrong)
        found.append(Finding(path, line, ID, f"sections out of order: expected {_quote(present)}, found {_quote(order)}"))

    if shape["title"] or shape["purpose"]:
        content = [(n, line) for n, line in lines if line.strip()]
        if not content or not re.match(r"#(?!#)[ \t]+\S", content[0][1]):
            found.append(Finding(path, content[0][0] if content else 0, ID, "file must start with a level-1 title"))
        elif shape["purpose"]:
            found.extend(_purpose(path, lines, content[0][0]))
    for name in shape["bullets_only"]:
        found.extend(_bullets_only(path, lines, pattern, name))
    for expr in shape["must_match"]:
        if not re.search(expr, text):
            found.append(Finding(path, 0, ID, f"nothing matches required pattern {expr!r}"))
    return found


def _purpose(path: str, lines: list[tuple[int, str]], title_line: int) -> list[Finding]:
    after = [(n, line) for n, line in lines if n > title_line]
    body = [(n, line) for n, line in after if line.strip()]
    if not body or body[0][1].lstrip().startswith(("#", "-", "*", "+", "|", ">")):
        return [Finding(path, title_line, ID, "the title must be followed by a one-line purpose")]
    number = body[0][0]
    nxt = next(((n, line) for n, line in after if n == number + 1), None)
    if nxt is not None and nxt[1].strip() and not nxt[1].startswith("#"):
        return [Finding(path, number, ID, "the purpose must be a single line (blank line before the next block)")]
    return []


def _bullets_only(path: str, lines: list[tuple[int, str]], pattern: re.Pattern[str], section: str) -> list[Finding]:
    found: list[Finding] = []
    inside = False
    for number, line in lines:
        m = pattern.match(line)
        if m:
            inside = m.group(1).strip() == section
            continue
        if line.startswith("#"):
            inside = False
        if inside and line.strip() and not re.match(r"\s*(?:[-*+]|\d+[.)])\s", line) and not line.startswith((" ", "\t")):
            found.append(Finding(path, number, ID, f'section "{section}" may only contain bullet items'))
    return found
