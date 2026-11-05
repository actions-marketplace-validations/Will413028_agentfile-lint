"""Shared error type and small schema helpers for configuration validation."""
from __future__ import annotations

import re
from typing import Any, Iterable

LEVELS = ("error", "warn", "off")


class ConfigError(Exception):
    """The configuration (or an allowlist entry) is invalid. The CLI exits with 2."""


def check_keys(table: Any, allowed: Iterable[str], where: str, removed: dict[str, str] | None = None) -> None:
    """Fail on non-table values and on any key not in `allowed` (typos must not pass silently).

    `removed` maps a key that an earlier release accepted to a message naming what replaces it.
    """
    if not isinstance(table, dict):
        raise ConfigError(f"{where}: expected a table")
    allowed = set(allowed)
    gone = sorted(set(table) & set(removed or {}))
    if gone:
        raise ConfigError(f"{where}.{gone[0]}: {removed[gone[0]]}")
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(sorted(allowed))})"
        )


def expect_int(value: Any, where: str, minimum: int = 1) -> int:
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{where}: expected an integer >= {minimum}")
    return value


def expect_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: expected a non-empty string")
    return value


def expect_str_list(value: Any, where: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or not (value or allow_empty):
        raise ConfigError(f"{where}: expected a {'' if allow_empty else 'non-empty '}list of strings")
    return [expect_str(v, f"{where}[{i}]") for i, v in enumerate(value)]


def levels_only(tables: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The effective tables of rule ids whose `[rules.<id>]` table takes only `level`."""
    effective = {}
    for rule_id, table in tables.items():
        check_keys(table, {"level"}, f"rules.{rule_id}")
        effective[rule_id] = {"level": table["level"]}
    return effective


def expect_bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: expected true or false")
    return value


def expect_level(value: Any, where: str) -> str:
    if value not in LEVELS:
        raise ConfigError(f"{where}: expected one of {', '.join(LEVELS)}")
    return value


def expect_str_items(value: Any, where: str) -> list[str]:
    """A list of non-empty strings; an empty list is allowed."""
    if not isinstance(value, list):
        raise ConfigError(f"{where}: expected a list of strings")
    return [expect_str(v, f"{where}[{i}]") for i, v in enumerate(value)]


def expect_regex(value: Any, where: str) -> str:
    text = expect_str(value, where)
    try:
        re.compile(text)
    except re.error as exc:
        raise ConfigError(f"{where}: invalid regular expression: {exc}") from exc
    return text


def expect_regex_list(value: Any, where: str) -> list[str]:
    return [expect_regex(v, f"{where}[{i}]") for i, v in enumerate(expect_str_items(value, where))]


def expect_table_list(value: Any, where: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise ConfigError(f"{where}: expected an array of tables")
    return value


def require_keys(table: dict[str, Any], keys: Iterable[str], where: str) -> None:
    for key in keys:
        if key not in table:
            raise ConfigError(f"{where}: missing key {key}")
