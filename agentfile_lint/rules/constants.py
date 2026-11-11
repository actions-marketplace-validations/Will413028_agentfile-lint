"""R6: copied constants, as candidates only.

A value copied from code into prose (`MaxBatch = 100`, `MAX_RETRIES 5`, `30 seconds`) goes stale when
the code changes. Only the code knows whether a number is a constant, so this rule lists
candidates and always reports them as warnings, whatever the rule level (`off` disables it).
"""
from __future__ import annotations

import re
from typing import Any

from ..errors import check_keys, expect_regex_list, require_keys
from ..finding import Finding
from ._text import prose_lines

ID = "R6"
NAME = "constants"
DESCRIPTION = "candidate constants copied from code into prose (always a warning)"
CHECKS = ((ID, NAME, DESCRIPTION),)
WARN_ONLY = (ID,)  # findings are warnings at any level; the engine reads it for allowlist notes


def validate(shared: None, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    params = _params(tables)
    return params, {ID: params}


def _params(tables: dict[str, dict[str, Any]]) -> dict[str, Any]:
    params = tables[ID]
    where = f"rules.{ID}"
    check_keys(params, {"level", "candidate_patterns"}, where)
    require_keys(params, ["candidate_patterns"], where)
    return {"level": params["level"], "candidate_patterns": expect_regex_list(params["candidate_patterns"], f"{where}.candidate_patterns")}


def check(path: str, text: str, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    patterns = [re.compile(p) for p in params["candidate_patterns"]]
    found: list[Finding] = []
    for number, line in prose_lines(text):
        for pattern in patterns:
            m = pattern.search(line)
            if m:
                found.append(Finding(path, number, ID, f"possible copied constant {m.group(0).strip()!r}; point to the code instead of repeating the value", level="warn"))
                break
    return found
