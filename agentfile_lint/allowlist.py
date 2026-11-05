"""Allowlist: time-boxed, counted exceptions. Every entry needs rule, path, count, reason, expires.

An entry suppresses the findings of its rule in its file only while their number n equals or is
below `count` (docs/adr/0005). n > count suppresses nothing and fails, so a new violation is never
hidden under an old exception; n < count fails asking to lower the count; n = 0 fails as no longer
needed; an expired entry fails and suppresses nothing. Exceptions can only shrink.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from .errors import ConfigError, check_keys, expect_int, expect_str
from .finding import Finding

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


def apply(
    findings: list[Finding],
    entries: list[Entry],
    settings: Settings,
    present: set[str],
    today: datetime.date,
) -> list[Finding]:
    """Drop findings covered by a live entry; add findings about the entries themselves.

    `present` is the full set of analyzed paths (decision: always the full set, never argv).
    """
    found: dict[tuple[str, str], int] = {}
    for f in findings:
        found[(f.rule, f.path)] = found.get((f.rule, f.path), 0) + 1
    covered: set[tuple[str, str]] = set()
    notes: list[Finding] = []
    for e in entries:
        days = (e.expires - today).days
        n = found.get((e.rule, e.path), 0)
        if days < 0:
            notes.append(Finding(
                e.path, 0, RULE_ID,
                f"entry for {e.rule} expired on {e.expires} ({-days} days ago); fix the file or renew with a new reason",
            ))
            continue
        if n == 0:
            why = "file is not an analyzed instruction file" if e.path not in present else f"file no longer violates {e.rule}"
            notes.append(Finding(e.path, 0, RULE_ID, f"entry for {e.rule} is no longer needed ({why}); remove it"))
            continue
        if n > e.count:
            # The new findings cannot be told apart from the accepted ones, so all are reported.
            notes.append(Finding(
                e.path, 0, RULE_ID,
                f"entry for {e.rule} has count {e.count} but the file has {_findings(n)}; none is suppressed, "
                f"fix the file down to {e.count} or fewer",
            ))
        else:
            covered.add((e.rule, e.path))
            if n < e.count:
                notes.append(Finding(
                    e.path, 0, RULE_ID,
                    f"entry for {e.rule} has count {e.count} but the file has {_findings(n)}; lower count to {n}",
                ))
        if days <= settings.warn_days:
            notes.append(Finding(
                e.path, 0, RULE_ID, f"entry for {e.rule} expires in {days} days ({e.expires})", level="warn",
            ))
    return [f for f in findings if (f.rule, f.path) not in covered] + notes
