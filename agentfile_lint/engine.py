"""Run the enabled rules over the full set of each file family (instruction, skill, hooks, mcp files)."""
from __future__ import annotations

import datetime
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

from . import allowlist, disable, discover, overrides
from .config import Config
from .context import Context, normalize_newlines
from .finding import INPUT_RULE, Finding
from .rules import FAMILIES, FAMILY, INSTRUCTION, MODULES


# Rules with no module and no `[rules]` level, always on: id -> description (`--list-rules`, SARIF).
PSEUDO_RULES = {
    allowlist.RULE_ID: "expired, no-longer-needed or miscounted allowlist entries, at the level of the entry's rule; warns before expiry and on an override glob that matches no file (always on)",
    disable.RULE_ID: "malformed per-line directives; warns on a directive that suppresses nothing (always on)",
    INPUT_RULE: "analyzed file is not valid UTF-8; only an allowlist entry can exempt it (always on)",
}


# Rules whose findings are warnings at any level (a module's `WARN_ONLY` ids).
WARN_ONLY = frozenset(rule_id for module in MODULES for rule_id in getattr(module, "WARN_ONLY", ()))


def _level(rule_level: str, finding: Finding) -> str:
    """The level caps a finding: at `warn` it is never an error; `off` drops it. R6 emits warnings only."""
    if rule_level == "off":
        return "off"
    return "warn" if rule_level == "warn" or finding.level == "warn" else "error"


@dataclass
class Analysis:
    findings: list[Finding]
    suppressed: list[Finding]  # dropped by a per-line directive or an allowlist entry (fix safety net 2)
    texts: dict[str, str]      # what fixes' edits are computed on: analyzed files and the config, as stored


def analyze(
    root: Path, config: Config, today: datetime.date, warn_as_error: bool = False, use_git: bool = True,
) -> list[Finding]:
    return run(root, config, today, warn_as_error, use_git).findings


def edit_path(root: Path, path: Path) -> str:
    """How a fix names a file: relative to the root (as findings do) when inside it, else absolute."""
    full = Path(path).resolve()
    try:
        return full.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return full.as_posix()


def _dropped(before: list[Finding], after: list[Finding]) -> list[Finding]:
    left = Counter(after)
    out = []
    for f in before:
        if left[f]:
            left[f] -= 1
        else:
            out.append(f)
    return out


def run(
    root: Path, config: Config, today: datetime.date, warn_as_error: bool = False, use_git: bool = True,
    replaced: dict[str, str] | None = None,
) -> Analysis:
    """`analyze` plus what was suppressed and the texts read. `replaced` (path -> text) stands in for
    files on disk: the edited texts `--fix` checks before writing them."""
    replaced = replaced or {}
    files = discover.list_files(root, use_git)
    # Each family's rules see only that family's files; a file two glob lists match is in both.
    family_paths: dict[str, list[str]] = {}
    for family in FAMILIES:
        paths = discover.matching_files(root, config.family_globs(family), files)
        alias = discover.aliases(root, paths)
        family_paths[family] = [p for p in paths if p not in alias]
    analyzed = [p for paths in family_paths.values() for p in paths]
    findings: list[Finding] = []
    stored: dict[str, str] = {}
    for path in dict.fromkeys(analyzed):
        try:
            raw = replaced[path] if path in replaced else (root / path).read_bytes().decode("utf-8")
            stored[path] = raw  # read once, as stored (docs/design.md, R1a to R1d)
        except UnicodeDecodeError:
            findings.append(Finding(path, 0, INPUT_RULE, "file is not valid UTF-8"))
    others = {
        family: {p: normalize_newlines(stored[p]) for p in paths if p in stored}
        for family, paths in family_paths.items() if family != INSTRUCTION
    }
    ctx = Context(root, files, {p: stored[p] for p in family_paths[INSTRUCTION] if p in stored}, others)
    texts = {INSTRUCTION: ctx.files} | others
    for module in MODULES:
        base = {rule_id: config.rules[rule_id]["level"] for rule_id, _, _ in module.CHECKS}
        # A rule runs at the highest level a `raise` override can give it, so it has findings to raise.
        levels = {rule_id: overrides.run_level(rule_id, level, config.overrides) for rule_id, level in base.items()}
        if all(level == "off" for level in levels.values()):
            continue
        params = config.params[module.__name__]
        found: list[Finding] = []
        if hasattr(module, "check"):
            for path, text in texts[FAMILY[module]].items():
                found.extend(module.check(path, text, params, levels))
        if hasattr(module, "check_repo"):
            found.extend(module.check_repo(ctx, params, levels))
        # Overrides before the allowlist: an entry for a path an override silences is no longer needed.
        for f in found:
            level = _level(overrides.level_for(f.path, f.rule, base[f.rule], config.overrides), f)
            if level != "off":
                findings.append(replace(f, level=level))
    # Per-line directives before the allowlist: a suppressed finding never counts toward an entry's count.
    before = findings
    findings = disable.apply(findings, ctx.files)
    suppressed = _dropped(before, findings)
    source = config.source
    config_key = edit_path(root, source.path) if source else None
    editable = allowlist.Editable(config_key, source.text, source.inherits_entries) if source and source.own_entries else None
    before = findings

    def level_of(rule: str, path: str) -> str:
        """The highest level a finding of `rule` can have on `path`: what an entry's notes take."""
        known = config.rules.get(rule)
        if known is None:
            return "error"  # E0 has no `[rules]` level: always an error
        level = overrides.level_for(path, rule, known["level"], config.overrides)
        return "warn" if level == "error" and rule in WARN_ONLY else level

    # A file that is not valid UTF-8 had no rule run on it: n = 0 there says nothing, so no fix.
    findings = allowlist.apply(
        findings, config.entries, config.allowlist, set(analyzed), today, editable, set(stored), level_of=level_of,
    )
    suppressed += _dropped(before, findings)
    findings += overrides.stale(config.overrides, set(analyzed), root)
    if warn_as_error:
        findings = [replace(f, level="error") for f in findings]
    read = dict(stored) | ({config_key: source.text} if source else {})
    return Analysis(sorted(findings, key=Finding.sort_key), suppressed, read)
