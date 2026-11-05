"""Overrides: permanent path scopes that change a rule's level (docs/adr/0004 decision 3, docs/adr/0006).

By default an override only lowers. An entry with `raise = true` only raises (from `off` too). For one
file and one rule: when any lowering entry matches, the lowest of the rule level and those entries
applies (lowering wins over raising); otherwise the highest of the rule level and the matching raising
entries. Entry order never matters. Each glob of every entry from a config file (not a preset) must match
an analyzed file (any family); a glob that matches none is a warning on the file that wrote it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import discover
from .allowlist import RULE_ID
from .errors import ConfigError, check_keys, expect_str, expect_str_list, require_keys
from .finding import Finding

LOWER = ("warn", "off")  # the levels of an entry without `raise`
RAISE = ("error", "warn")  # the levels of an entry with `raise = true`
_RANK = {"error": 2, "warn": 1, "off": 0}


@dataclass(frozen=True)
class Override:
    paths: tuple[str, ...]
    rules: tuple[tuple[str, str], ...]  # (rule id, level): warn | off, or error | warn when raise_
    reason: str
    source: str  # the config file (or preset) the entry is written in
    index: int  # its position in that file
    direct: bool  # written in the config file the run loads directly (not inherited through `extends`)
    raise_: bool = False


def parse(raw: Any, known_rules: set[str]) -> list[Override]:
    """`raw` is a list of (entry table, source, index in source, direct), aliases already resolved."""
    # A file reached twice through `extends` (a diamond) counts once. An `unset` on one branch may have
    # shortened one copy; the other branch still inherits the entry, so the copies' globs are united.
    merged: dict[tuple[str, int], tuple[Any, bool]] = {}
    for item, source, index, direct in raw:
        known = merged.get((source, index))
        if known is not None and isinstance(item, dict) and isinstance(known[0], dict):
            copies = sorted((known[0].get("paths", []), item.get("paths", [])), key=len, reverse=True)
            paths = list(dict.fromkeys([*copies[0], *copies[1]]))  # the longer copy keeps the written order
            item = {**known[0], "paths": paths}
        merged[(source, index)] = (item, direct)
    out: list[Override] = []
    for (source, index), (item, direct) in merged.items():
        where = f"{source}: overrides[{index}]"
        check_keys(item, {"paths", "rules", "reason", "raise"}, where)
        require_keys(item, ("paths", "rules", "reason"), where)
        paths = expect_str_list(item["paths"], f"{where}.paths")
        raise_ = item.get("raise", False)
        if not isinstance(raise_, bool):
            raise ConfigError(f"{where}.raise: expected true or false")
        allowed = RAISE if raise_ else LOWER
        rules = item["rules"]
        if not isinstance(rules, dict) or not rules:
            raise ConfigError(f"{where}.rules: expected a table of rule = \"{allowed[0]}\" | \"{allowed[1]}\"")
        for rule, level in rules.items():
            if rule not in known_rules:
                raise ConfigError(f"{where}.rules: unknown rule {rule!r} (only rules with a [rules] table)")
            if level not in allowed:
                hint = "an entry with raise = true only raises" if raise_ else "an override only lowers unless raise = true"
                raise ConfigError(f"{where}.rules.{rule}: expected \"{allowed[0]}\" or \"{allowed[1]}\" ({hint})")
        reason = expect_str(item["reason"], f"{where}.reason")
        out.append(Override(tuple(paths), tuple(rules.items()), reason, source, index, direct, raise_))
    return out


def run_level(rule: str, level: str, overrides: list[Override]) -> str:
    """The highest level `rule` can reach on any file: what the rule must run at to have findings to raise."""
    for o in overrides:
        raised = dict(o.rules).get(rule) if o.raise_ else None
        if raised is not None and _RANK[raised] > _RANK[level]:
            level = raised
    return level


def level_for(path: str, rule: str, level: str, overrides: list[Override]) -> str:
    """The level of `rule` on `path`: lowering entries win, else the highest of level and raising entries."""
    lowers, raises = [], []
    for o in overrides:
        value = dict(o.rules).get(rule)
        if value is not None and discover.matches(path, list(o.paths)):
            (raises if o.raise_ else lowers).append(value)
    if lowers:
        return min([level, *lowers], key=_RANK.__getitem__)
    return max([level, *raises], key=_RANK.__getitem__)


def stale(overrides: list[Override], present: set[str], root: Path) -> list[Finding]:
    """A warning for each override glob that matches no analyzed file, on the file that wrote it.

    Presets carry no overrides; an inherited glob a repository does not need is removed there with `unset`.
    """
    out: list[Finding] = []
    for o in overrides:
        if o.source.startswith("preset:"):
            continue
        fix = "remove it" if o.direct else "remove it there, or unset it in the config that extends it"
        origin = "" if o.direct else " (inherited through extends)"
        for glob in o.paths:
            if not any(discover.matches(p, [glob]) for p in present):
                out.append(Finding(
                    _display(o.source, root), 0, RULE_ID,
                    f"overrides[{o.index}]{origin}: glob {glob!r} matches no analyzed file; {fix}",
                    level="warn",
                ))
    return out


def _display(source: str, root: Path) -> str:
    """Repo-relative inside the repo; as given on the command line outside it."""
    try:
        return Path(source).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return source
