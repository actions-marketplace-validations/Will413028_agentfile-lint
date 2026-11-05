"""R3a: a test name written in backticks must be defined somewhere in the repository.

Per language, `test_defs` gives the shape of a name, how its definition looks and which tracked
files to search. A language with no matching tracked file is skipped (nothing to judge against).
"""
from __future__ import annotations

import re
from typing import Any

from ..context import Context
from ..discover import glob_to_regex
from ..errors import check_keys, expect_regex, expect_str, expect_str_list, expect_table_list, require_keys, ConfigError
from ..finding import Finding
from ._text import code_spans, prose_lines

ID = "R3a"
NAME = "test-names"
DESCRIPTION = "test names referenced in backticks exist in the repository"
CHECKS = ((ID, NAME, DESCRIPTION),)


def validate(shared: None, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    params = _params(tables)
    return params, {ID: params}


def _params(tables: dict[str, dict[str, Any]]) -> dict[str, Any]:
    params = tables[ID]
    where = f"rules.{ID}"
    check_keys(params, {"level", "test_defs"}, where)
    require_keys(params, ["test_defs"], where)
    defs = []
    for i, raw in enumerate(expect_table_list(params["test_defs"], f"{where}.test_defs")):
        at = f"{where}.test_defs[{i}]"
        check_keys(raw, {"name", "definition", "files"}, at)
        require_keys(raw, ["name", "definition", "files"], at)
        definition = expect_str(raw["definition"], f"{at}.definition")
        if "{name}" not in definition:
            raise ConfigError(f"{at}.definition: must contain the {{name}} placeholder")
        expect_regex(definition.replace("{name}", "x"), f"{at}.definition")
        defs.append({
            "name": expect_regex(raw["name"], f"{at}.name"),
            "definition": definition,
            "files": expect_str_list(raw["files"], f"{at}.files"),
        })
    return {"level": params["level"], "test_defs": defs}


def _defined(ctx: Context, spec: dict[str, Any]) -> set[str] | None:
    globs = [glob_to_regex(g) for g in spec["files"]]
    files = [p for p in ctx.tracked if any(g.match(p) for g in globs)]
    if not files:
        return None
    regex = re.compile(spec["definition"].replace("{name}", "(?P<name>" + spec["name"] + ")"), re.MULTILINE)
    names: set[str] = set()
    for path in files:
        text = ctx.read(path)
        if text is not None:
            names.update(m.group("name") for m in regex.finditer(text))
    return names


def check_repo(ctx: Context, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    specs = []
    for spec in params["test_defs"]:
        names = _defined(ctx, spec)
        if names is not None:
            specs.append((re.compile(spec["name"]), names))
    if not specs:
        return []
    found: list[Finding] = []
    for path, text in ctx.files.items():
        for number, line in prose_lines(text):
            for span in code_spans(line):
                token = span[:-2] if span.endswith("()") else span
                matching = [names for shape, names in specs if shape.fullmatch(token)]
                if matching and not any(token in names for names in matching):
                    found.append(Finding(path, number, ID, f"test `{token}` is not defined in any searched test file"))
    return found
