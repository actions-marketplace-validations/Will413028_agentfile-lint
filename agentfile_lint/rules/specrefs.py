"""R3c: a spec section reference (`§N`) must match a numbered heading in the spec document.

`specs` maps instruction files to their spec document: the first entry whose `glob` matches the
file applies, and `{1}`, `{2}` in `spec` stand for what the glob's `*` matched. A reference written
as `name §N` (an ASCII word directly before the sign, other than one of `plain_words` such as "see")
points at another document and is skipped when `ignore_qualified` is true. `ignore_before` lists regexes tested against the text before a reference
on its line (for example a phrase naming another document). With no `specs` the rule does nothing.
"""
from __future__ import annotations

import re
from typing import Any

from ..context import Context
from ..discover import glob_to_regex
from ..errors import ConfigError, check_keys, expect_bool, expect_regex, expect_regex_list, expect_str, expect_str_items, expect_table_list, require_keys
from ..finding import Finding
from ._text import prose_lines

ID = "R3c"
NAME = "spec-refs"
DESCRIPTION = "spec section references (§N) match a numbered heading in the spec document"
CHECKS = ((ID, NAME, DESCRIPTION),)


def validate(shared: None, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    params = _params(tables)
    return params, {ID: params}


def _params(tables: dict[str, dict[str, Any]]) -> dict[str, Any]:
    params = tables[ID]
    where = f"rules.{ID}"
    check_keys(params, {"level", "specs", "ref_pattern", "heading_pattern", "ignore_qualified", "plain_words", "ignore_before"}, where)
    require_keys(params, ["specs", "ref_pattern", "heading_pattern", "ignore_qualified", "plain_words", "ignore_before"], where)
    specs = []
    for i, raw in enumerate(expect_table_list(params["specs"], f"{where}.specs")):
        at = f"{where}.specs[{i}]"
        check_keys(raw, {"glob", "spec"}, at)
        require_keys(raw, ["glob", "spec"], at)
        specs.append({"glob": expect_str(raw["glob"], f"{at}.glob"), "spec": expect_str(raw["spec"], f"{at}.spec")})
    for key in ("ref_pattern", "heading_pattern"):
        if re.compile(expect_regex(params[key], f"{where}.{key}")).groups != 1:
            raise ConfigError(f"{where}.{key}: must contain exactly one capture group (the section number)")
    return {
        "level": params["level"],
        "specs": specs,
        "ref_pattern": params["ref_pattern"],
        "heading_pattern": params["heading_pattern"],
        "ignore_qualified": expect_bool(params["ignore_qualified"], f"{where}.ignore_qualified"),
        "ignore_before": expect_regex_list(params["ignore_before"], f"{where}.ignore_before"),
        "plain_words": [w.lower() for w in expect_str_items(params["plain_words"], f"{where}.plain_words")],
    }


def _spec_path(path: str, params: dict[str, Any]) -> str | None:
    for entry in params["specs"]:
        m = glob_to_regex(entry["glob"], capture=True).match(path)
        if m:
            out = entry["spec"]
            for i, group in enumerate(m.groups(), start=1):
                out = out.replace("{%d}" % i, group)
            return out
    return None


def _qualified(before: str, plain_words: list[str]) -> bool:
    m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", before)
    return m is not None and m.group(1).lower() not in plain_words


def _numbers(heading: re.Pattern[str], body: str) -> set[str]:
    """Heading numbers in the spec; a heading 2.1 also makes section 2 a valid target."""
    out: set[str] = set()
    for m in heading.finditer(body):
        parts = m.group(1).split(".")
        out.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
    return out


def check_repo(ctx: Context, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    ref = re.compile(params["ref_pattern"])
    heading = re.compile(params["heading_pattern"], re.MULTILINE)
    sections: dict[str, set[str] | None] = {}
    found: list[Finding] = []
    for path, text in ctx.files.items():
        spec = _spec_path(path, params)
        if spec is None:
            continue
        if spec not in sections:
            body = ctx.read(spec) if spec in ctx.tracked_set else None
            sections[spec] = None if body is None else _numbers(heading, body)
        known = sections[spec]
        missing_reported = False
        for number, line in prose_lines(text):
            for m in ref.finditer(line):
                if any(re.search(p, line[:m.start()]) for p in params["ignore_before"]):
                    continue
                if params["ignore_qualified"] and _qualified(line[:m.start()], params["plain_words"]):
                    continue
                if known is None:
                    if missing_reported:
                        continue
                    missing_reported = True
                    found.append(Finding(path, number, ID, f"spec document {spec} is not a tracked file"))
                elif m.group(1) not in known:
                    found.append(Finding(path, number, ID, f"§{m.group(1)} has no matching heading in {spec}"))
    return found
