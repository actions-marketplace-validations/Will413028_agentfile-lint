"""Configuration: shipped preset + optional repo config with `extends`; unknown keys fail.

Merge rule: tables merge key by key (the child wins); every other value, lists included,
is replaced as a whole. Two lists concatenate along the `extends` chain instead (parents first):
`[[overrides]]`, since replacing them would silently drop the overrides of the config a file extends
(a file removes an inherited glob with an `unset` entry), and `discover.extend_globs`, which adds to
`discover.globs` the way ruff's `extend-select` adds to `select`.
"""
from __future__ import annotations

import datetime
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from . import allowlist, overrides as overrides_mod
from .errors import (
    LEVELS, ConfigError, check_keys, expect_int, expect_str, expect_str_list, expect_table_list, require_keys,
)
from .finding import INPUT_RULE
from .rules import ALIASES, MODULES, RETIRED, RULES, SHARED

CONFIG_NAME = ".agentfile-lint.toml"
# Migration aid for the 0.4.0 rename; remove at 1.0.
LEGACY_CONFIG_NAME = ".instruction-lint.toml"
PRESET_PREFIX = "preset:"
DEFAULT_PRESET = "preset:default"
_TOP_KEYS = {"extends", "discover", "allowlist", "shared", "rules", "overrides", "check_pins"}
PIN_DEFAULTS = {
    "repo": "agentfile-lint",
    "files": [
        ".pre-commit-config.yaml", ".pre-commit-config.yml", "lefthook.yml", "lefthook.yaml",
        ".lefthook.yml", ".lefthook.yaml", ".github/workflows/*.yml", ".github/workflows/*.yaml",
    ],
}


def default_config_path(root: Path | None) -> Path | None:
    """The repo-root config file, or None. Fails when only the pre-0.4.0 file name exists."""
    if root is None:
        return None
    path = root / CONFIG_NAME
    if path.is_file():
        return path
    if (root / LEGACY_CONFIG_NAME).is_file():
        raise ConfigError(
            f"found {LEGACY_CONFIG_NAME}, which agentfile-lint no longer reads; "
            f"rename it to {CONFIG_NAME} (git mv {LEGACY_CONFIG_NAME} {CONFIG_NAME})"
        )
    return None


@dataclass
class Config:
    globs: list[str]  # `discover.globs` as merged (the child replaces the list)
    allowlist: allowlist.Settings
    entries: list[allowlist.Entry]
    rules: dict[str, dict[str, Any]]  # rule id -> its merged, validated `[rules.<id>]` table, including "level"
    shared: dict[str, dict[str, Any]] = field(default_factory=dict)  # group -> its `[shared.<group>]` table
    params: dict[str, Any] = field(default_factory=dict)  # rule module name -> what its validate() returned
    check_pins: dict[str, Any] = field(default_factory=lambda: dict(PIN_DEFAULTS))  # repo, files
    overrides: list[overrides_mod.Override] = field(default_factory=list)
    extend_globs: list[str] = field(default_factory=list)  # `discover.extend_globs`, concatenated along `extends`

    @property
    def all_globs(self) -> list[str]:
        """What discovery matches: `globs` then `extend_globs`, duplicates dropped."""
        return list(dict.fromkeys(self.globs + self.extend_globs))


def to_jsonable(cfg: "Config") -> dict[str, Any]:
    """The effective configuration as plain JSON data (dates as ISO strings)."""
    return {
        "discover": {"globs": cfg.globs, "extend_globs": cfg.extend_globs},
        "allowlist": {
            "max_days": cfg.allowlist.max_days,
            "max_entries": cfg.allowlist.max_entries,
            "warn_days": cfg.allowlist.warn_days,
            "entries": [
                {"rule": e.rule, "path": e.path, "count": e.count, "reason": e.reason, "expires": e.expires.isoformat()}
                for e in cfg.entries
            ],
        },
        "shared": cfg.shared,
        "rules": cfg.rules,
        "overrides": [
            {"paths": list(o.paths), "rules": dict(o.rules), "reason": o.reason, **({"raise": True} if o.raise_ else {})}
            for o in cfg.overrides
        ],
        "check_pins": cfg.check_pins,
    }


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _read(source: str, text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{source}: invalid TOML: {exc}") from exc


def _load_raw(ref: str, base_dir: Path | None, seen: tuple[str, ...]) -> dict[str, Any]:
    if ref.startswith(PRESET_PREFIX):
        name = ref[len(PRESET_PREFIX):]
        key = ref
        try:
            text = (resources.files("agentfile_lint") / "presets" / f"{name}.toml").read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise ConfigError(f"unknown preset {name!r}") from exc
        data = _read(ref, text)
    else:
        path = Path(ref)
        if not path.is_absolute() and base_dir is not None:
            path = base_dir / path
        key = str(path.resolve())
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"cannot read config {path}: {exc.strerror}") from exc
        data = _read(str(path), text)
        base_dir = path.parent
    if key in seen:
        raise ConfigError(f"extends cycle at {ref}")
    extends = data.get("extends", [DEFAULT_PRESET] if ref != DEFAULT_PRESET else [])
    if isinstance(extends, str):
        extends = [extends]
    if not isinstance(extends, list) or not all(isinstance(e, str) for e in extends):
        raise ConfigError(f"{ref}: extends must be a list of strings")
    merged: dict[str, Any] = {}
    inherited: list[tuple[Any, str, int, bool]] = []
    extend_globs: list[Any] = []
    for parent in extends:
        parent_raw = _load_raw(parent, base_dir, seen + (key,))
        inherited += parent_raw.pop("overrides")
        extend_globs += parent_raw.pop("extend_globs")
        merged = _merge(merged, parent_raw)
    if "extend_globs" in data:  # the merged chain carries it at the top level; a file writes it under [discover]
        raise ConfigError(f"{ref}: extend_globs belongs in [discover]")
    own = _resolve_aliases({k: v for k, v in data.items() if k != "extends"}, ref)
    own_overrides = expect_table_list(own.pop("overrides", []), f"{ref}: overrides")
    discover = own.get("discover")
    if isinstance(discover, dict) and "extend_globs" in discover:
        extend_globs += expect_str_list(discover["extend_globs"], f"{ref}: discover.extend_globs", allow_empty=True)
        own = {**own, "discover": {k: v for k, v in discover.items() if k != "extend_globs"}}
    # The file this run loads directly; entries from the files it extends are "inherited".
    direct = not seen and not ref.startswith(PRESET_PREFIX)
    merged = _merge(merged, own)
    mine: list[tuple[Any, str, int, bool]] = []
    for i, entry in enumerate(own_overrides):
        if isinstance(entry, dict) and "unset" in entry:
            inherited = _unset(entry, inherited, f"{ref}: overrides[{i}]")
        else:
            # As given for the file the run loads; resolved for an inherited one, whose ref is relative to
            # the file that extends it, not to the working directory.
            mine.append((entry, ref if direct else key, i, direct))
    merged["overrides"] = inherited + mine
    merged["extend_globs"] = extend_globs
    return merged


def _unset(entry: dict[str, Any], inherited: list[tuple[Any, str, int, bool]], where: str) -> list[tuple[Any, str, int, bool]]:
    """Remove the `unset` globs from the overrides this file inherits; an entry left with no glob goes."""
    check_keys(entry, {"unset", "reason"}, where)
    require_keys(entry, ("unset", "reason"), where)
    globs = expect_str_list(entry["unset"], f"{where}.unset")
    expect_str(entry["reason"], f"{where}.reason")
    out = inherited
    for glob in globs:
        hit = [item for item in out if isinstance(item[0], dict) and isinstance(item[0].get("paths"), list)
               and glob in item[0]["paths"]]
        if not hit:
            raise ConfigError(f"{where}.unset: {glob!r} is not a glob of any inherited override")
        out = [
            ({**e, "paths": [p for p in e["paths"] if p != glob]}, *rest) if (e, *rest) in hit else (e, *rest)
            for e, *rest in out
        ]
    return [item for item in out if not (isinstance(item[0], dict) and item[0].get("paths") == [])]


def _resolve_aliases(data: dict[str, Any], source: str) -> dict[str, Any]:
    """Replace rule aliases with rule ids in one config file, before it merges with its parents.

    Resolving per file keeps a repo's `[rules.file-lines]` overriding a preset's `[rules.R1b]`; one file
    naming the same rule both ways is ambiguous and fails.
    """
    rules = data.get("rules")
    if isinstance(rules, dict):
        resolved: dict[str, Any] = {}
        written: dict[str, str] = {}  # rule id -> the key the file used
        for key, value in rules.items():
            _retired(key, f"{source}: rules.{key}")
            rule_id = ALIASES.get(key, key)
            if rule_id in resolved:
                raise ConfigError(f"{source}: rules.{written[rule_id]} and rules.{key} name the same rule; use one")
            resolved[rule_id] = value
            written[rule_id] = key
        data = {**data, "rules": resolved}
    al = data.get("allowlist")
    if isinstance(al, dict) and isinstance(al.get("entries"), list):
        for i, e in enumerate(al["entries"]):
            if isinstance(e, dict) and isinstance(e.get("rule"), str):
                _retired(e["rule"], f"{source}: allowlist.entries[{i}].rule")
        entries = [
            {**e, "rule": ALIASES[e["rule"]]} if isinstance(e, dict) and isinstance(e.get("rule"), str) and e["rule"] in ALIASES else e
            for e in al["entries"]
        ]
        data = {**data, "allowlist": {**al, "entries": entries}}
    ov = data.get("overrides")
    if isinstance(ov, list):
        resolved_ov = []
        for i, entry in enumerate(ov):
            if isinstance(entry, dict) and isinstance(entry.get("rules"), dict):
                levels: dict[str, Any] = {}
                written = {}
                for key, value in entry["rules"].items():
                    _retired(key, f"{source}: overrides[{i}].rules.{key}")
                    rule_id = ALIASES.get(key, key)
                    if rule_id in levels:
                        raise ConfigError(
                            f"{source}: overrides[{i}].rules.{written[rule_id]} and .{key} name the same rule; use one"
                        )
                    levels[rule_id] = value
                    written[rule_id] = key
                entry = {**entry, "rules": levels}
            resolved_ov.append(entry)
        data = {**data, "overrides": resolved_ov}
    return data


def _retired(key: str, where: str) -> None:
    if key in RETIRED:
        raise ConfigError(f"{where}: {RETIRED[key]}")


def load(config_path: Path | None, today: datetime.date) -> Config:
    """Load the preset plus `config_path` (when given). Raises ConfigError on any problem."""
    if config_path is None:
        raw = _load_raw(DEFAULT_PRESET, None, ())
    else:
        raw = _load_raw(str(config_path), None, ())
    return _validate(raw, today)


def _validate(raw: dict[str, Any], today: datetime.date) -> Config:
    check_keys(raw, _TOP_KEYS | {"extend_globs"}, "config")  # extend_globs: collected by _load_raw
    discover = raw.get("discover", {})
    check_keys(discover, {"globs"}, "discover")  # extend_globs was taken out while loading
    globs = expect_str_list(discover.get("globs"), "discover.globs")

    al = raw.get("allowlist", {})
    check_keys(al, {"max_days", "max_entries", "warn_days", "entries"}, "allowlist")
    settings = allowlist.Settings(
        max_days=expect_int(al.get("max_days"), "allowlist.max_days", 0),
        max_entries=expect_int(al.get("max_entries"), "allowlist.max_entries", 0),
        warn_days=expect_int(al.get("warn_days"), "allowlist.warn_days", 0),
    )

    shared_raw = raw.get("shared", {})
    check_keys(shared_raw, set(SHARED), "shared")
    for group, keys in SHARED.items():
        if group not in shared_raw:
            raise ConfigError(f"shared.{group}: missing")
        check_keys(shared_raw[group], keys, f"shared.{group}")
    rules_raw = raw.get("rules", {})
    check_keys(rules_raw, set(RULES) | set(ALIASES), "rules")  # aliases are resolved by now; listed as a hint
    rules: dict[str, dict[str, Any]] = {}
    params: dict[str, Any] = {}
    for module in MODULES:
        ids = [rule_id for rule_id, _, _ in module.CHECKS]
        for rule_id in ids:
            if rule_id not in rules_raw:
                raise ConfigError(f"rules.{rule_id}: missing")
            if not isinstance(rules_raw[rule_id], dict):
                raise ConfigError(f"rules.{rule_id}: expected a table")
            if rules_raw[rule_id].get("level") not in LEVELS:
                raise ConfigError(f"rules.{rule_id}.level: expected one of {', '.join(LEVELS)}")
        group = module.SHARED[0] if hasattr(module, "SHARED") else None
        tables = {rule_id: rules_raw[rule_id] for rule_id in ids}
        params[module.__name__], effective = module.validate(shared_raw.get(group), tables)
        for rule_id in ids:
            # The one source of each id's effective table (defaults filled in), read by the engine for
            # the level and printed by `config --format json`.
            rules[rule_id] = {**effective[rule_id], "level": tables[rule_id]["level"]}

    # E0 has no `[rules]` table (it cannot be turned off), but an allowlist entry may name it.
    entries = allowlist.parse(al.get("entries", []), settings, set(RULES) | {INPUT_RULE}, today)
    pins = raw.get("check_pins", {})
    check_keys(pins, set(PIN_DEFAULTS), "check_pins")
    pins = {
        "repo": expect_str(pins.get("repo", PIN_DEFAULTS["repo"]), "check_pins.repo"),
        "files": expect_str_list(pins.get("files", PIN_DEFAULTS["files"]), "check_pins.files"),
    }
    overrides = overrides_mod.parse(raw.get("overrides", []), set(RULES))
    extend_globs = list(raw.get("extend_globs", []))
    shared = {group: shared_raw[group] for group in SHARED}
    return Config(
        globs=globs, allowlist=settings, entries=entries, rules=rules, shared=shared, params=params,
        check_pins=pins, overrides=overrides, extend_globs=extend_globs,
    )
