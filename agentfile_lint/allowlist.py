"""Allowlist: time-boxed, counted exceptions. Every entry needs rule, path, count, reason, expires.

An entry suppresses the findings of its rule in its file only while their number n equals or is
below `count` (docs/adr/0005). n > count suppresses nothing and fails, so a new violation is never
hidden under an old exception; n < count fails asking to lower the count; n = 0 fails as no longer
needed; an expired entry fails and suppresses nothing. Exceptions can only shrink.

Those notes have the level of the entry's rule on the entry's path (`off` counts as `warn`), so an
entry is never stricter than the rule it excepts: listing a warning's known findings cannot fail a run.

Fixes (docs/design.md, Fixes), only for entries written in the config file the run loads: lowering
`count` to n, and removing an entry whose file no longer violates the rule. Both are safe, and both
only shrink an exception. Nothing else is fixed: n > count is a new violation, an expired entry needs
a person to fix the file or write a new reason, and n = 0 for a file this run did not analyze depends
on what the run saw (git, `--no-git`, globs), not on the file.
"""
from __future__ import annotations

import datetime
import tomllib
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple

from . import fix, toml_edit
from .errors import ConfigError, check_keys, expect_int, expect_str
from .finding import SAFE, Edit, Finding, Fix

RULE_ID = "allowlist"


@dataclass(frozen=True)
class Settings:
    max_days: int
    max_entries: int
    warn_days: int


@dataclass(frozen=True)
class Entry:
    rule: str
    path: str
    count: int
    reason: str
    expires: datetime.date


def parse(raw: Any, settings: Settings, known_rules: set[str], today: datetime.date) -> list[Entry]:
    if not isinstance(raw, list):
        raise ConfigError("allowlist.entries: expected an array of tables")
    if len(raw) > settings.max_entries:
        raise ConfigError(
            f"allowlist.entries: {len(raw)} entries exceed the limit of {settings.max_entries}; "
            "fix the files instead of listing more exceptions"
        )
    latest = today + datetime.timedelta(days=settings.max_days)
    entries: list[Entry] = []
    seen: set[tuple[str, str]] = set()
    for i, item in enumerate(raw):
        where = f"allowlist.entries[{i}]"
        check_keys(item, {"rule", "path", "count", "reason", "expires"}, where)
        for key in ("rule", "path", "count", "reason", "expires"):
            if key not in item:
                raise ConfigError(f"{where}: missing key {key}")
        rule = expect_str(item["rule"], f"{where}.rule")
        if rule not in known_rules:
            raise ConfigError(f"{where}.rule: unknown rule {rule!r}")
        path = expect_str(item["path"], f"{where}.path")
        count = expect_int(item["count"], f"{where}.count", 1)
        reason = expect_str(item["reason"], f"{where}.reason")
        expires = item["expires"]
        # TOML dates arrive as datetime.date; a quoted string is accepted too.
        if isinstance(expires, str):
            try:
                expires = datetime.date.fromisoformat(expires)
            except ValueError as exc:
                raise ConfigError(f"{where}.expires: not a YYYY-MM-DD date") from exc
        if isinstance(expires, datetime.datetime) or not isinstance(expires, datetime.date):
            raise ConfigError(f"{where}.expires: expected a YYYY-MM-DD date")
        if expires > latest:
            raise ConfigError(
                f"{where}.expires: {expires} is more than {settings.max_days} days from {today} "
                f"(latest allowed {latest})"
            )
        if (rule, path) in seen:
            raise ConfigError(f"{where}: duplicate entry for {rule} {path}")
        seen.add((rule, path))
        entries.append(Entry(rule, path, count, reason, expires))
    return entries


def _findings(n: int) -> str:
    return f"{n} finding" if n == 1 else f"{n} findings"


class Editable(NamedTuple):
    """The config file whose entries a fix may edit: `path` as edits name it, `text` as stored, and
    whether a file it extends has entries (they come back when the file's own list is gone)."""

    path: str
    text: str
    inherits_entries: bool


class _Editor:
    """Builds the fixes of the entries written in one config file."""

    def __init__(self, target: Editable, entries: int):
        self.target = target
        self.entries = entries
        self.blocks = toml_edit.entry_blocks(target.text, entries)
        self.data = tomllib.loads(target.text) if self.blocks else None  # parsed once for safety net 1

    def _checked(self, description: str, edit: Edit, expected: dict) -> Fix | None:
        edits = (edit,)
        # Safety net 1: anything but the target changed means the locator was fooled; suggestion only.
        return Fix(SAFE, description, edits) if fix.toml_checked(self.target.text, edits, expected) else None

    def lower(self, index: int, n: int) -> Fix | None:
        block = self.blocks[index] if self.blocks else None
        if block is None or block.count is None:
            return None
        line, start, end = block.count
        edit = Edit(self.target.path, (line, start), (line, end), str(n))
        return self._checked(f"lower count to {n}", edit, _with_entry(self.data, index, lambda e: {**e, "count": n}))

    def remove(self, index: int) -> Fix | None:
        block = self.blocks[index] if self.blocks else None
        if block is None:
            return None
        edit = fix.line_delete(self.target.path, self.target.text, block.removal_start, block.removal_end)
        return self._checked("remove the entry", edit, _with_entry(self.data, index, None))


def _with_entry(data: dict, index: int, change) -> dict:
    """`data` with entry `index` changed by `change` (None removes it): what safety net 1 expects."""
    al = dict(data["allowlist"])
    entries = list(al["entries"])
    if change is None:
        del entries[index]
    else:
        entries[index] = change(entries[index])
    return {**data, "allowlist": {**al, "entries": entries}}


def apply(
    findings: list[Finding],
    entries: list[Entry],
    settings: Settings,
    present: set[str],
    today: datetime.date,
    editable: Editable | None = None,
    readable: set[str] | None = None,
    *,
    level_of: Callable[[str, str], str],
) -> list[Finding]:
    """Drop findings covered by a live entry; add findings about the entries themselves.

    `present` is the full set of analyzed paths (decision: always the full set, never argv).
    `editable` is the config file the run loads when `entries` are written in it (entries from a file
    it extends get no fix); `readable` the analyzed paths whose text the rules saw (default: all).
    `level_of(rule, path)` is the highest level a finding of `rule` can have on `path` (error | warn |
    off): the level of the entry's notes, where `off` gives `warn`.
    """
    editor = _Editor(editable, len(entries)) if editable is not None else None
    found: dict[tuple[str, str], int] = {}
    for f in findings:
        found[(f.rule, f.path)] = found.get((f.rule, f.path), 0) + 1
    # Entries a fix may remove: live, n = 0, and the rules read the file (`readable`, a subset of
    # `present`: one that is not valid UTF-8 had no rule run on it, so n = 0 there says nothing).
    readable = present if readable is None else readable
    removable = [
        i for i, e in enumerate(entries)
        if e.expires >= today and not found.get((e.rule, e.path)) and e.path in readable
    ]
    # Removing every own entry would bring back the entries of a file this one extends
    # (`allowlist.entries` replaces as a whole), which widens what is suppressed: one stays.
    if editor and editor.target.inherits_entries and len(removable) == len(entries):
        removable.pop()
    covered: set[tuple[str, str]] = set()
    notes: list[Finding] = []
    for index, e in enumerate(entries):
        days = (e.expires - today).days
        n = found.get((e.rule, e.path), 0)
        # An entry is never stricter than its rule on its path (an entry for a rule that is off warns).
        level = "error" if level_of(e.rule, e.path) == "error" else "warn"
        if days < 0:
            notes.append(Finding(
                e.path, 0, RULE_ID,
                f"entry for {e.rule} expired on {e.expires} ({-days} days ago); fix the file or renew with a new reason",
                level=level,
            ))
            continue
        if n == 0:
            fixed = e.path in present
            why = f"file no longer violates {e.rule}" if fixed else "file is not an analyzed file"
            notes.append(Finding(e.path, 0, RULE_ID, f"entry for {e.rule} is no longer needed ({why}); remove it",
                                 level=level, fix=editor.remove(index) if editor and index in removable else None))
            continue
        if n > e.count:
            # The new findings cannot be told apart from the accepted ones, so all are reported.
            notes.append(Finding(
                e.path, 0, RULE_ID,
                f"entry for {e.rule} has count {e.count} but the file has {_findings(n)}; none is suppressed, "
                f"fix the file down to {e.count} or fewer",
                level=level,
            ))
        else:
            covered.add((e.rule, e.path))
            if n < e.count:
                notes.append(Finding(
                    e.path, 0, RULE_ID,
                    f"entry for {e.rule} has count {e.count} but the file has {_findings(n)}; lower count to {n}",
                    level=level, fix=editor.lower(index, n) if editor else None,
                ))
        if days <= settings.warn_days:
            notes.append(Finding(
                e.path, 0, RULE_ID, f"entry for {e.rule} expires in {days} days ({e.expires})", level="warn",
            ))
    return [f for f in findings if (f.rule, f.path) not in covered] + notes
