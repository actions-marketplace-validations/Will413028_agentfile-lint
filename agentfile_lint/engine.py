"""Run the enabled rules over the full set of each file family (instruction, skill, hooks, mcp files)."""
from __future__ import annotations

import datetime
from dataclasses import replace
from pathlib import Path

from . import allowlist, disable, discover, overrides
from .config import Config
from .context import Context, normalize_newlines
from .finding import INPUT_RULE, Finding
from .rules import FAMILIES, FAMILY, INSTRUCTION, MODULES


# Rules with no module and no `[rules]` level, always on: id -> description (`--list-rules`, SARIF).
PSEUDO_RULES = {
    allowlist.RULE_ID: "expired, no-longer-needed or miscounted allowlist entries; warns before expiry and on an override glob that matches no file (always on)",
    disable.RULE_ID: "malformed per-line directives; warns on a directive that suppresses nothing (always on)",
    INPUT_RULE: "analyzed file is not valid UTF-8; only an allowlist entry can exempt it (always on)",
}


def _level(rule_level: str, finding: Finding) -> str:
    """The level caps a finding: at `warn` it is never an error; `off` drops it. R6 emits warnings only."""
    if rule_level == "off":
        return "off"
    return "warn" if rule_level == "warn" or finding.level == "warn" else "error"


def analyze(
    root: Path, config: Config, today: datetime.date, warn_as_error: bool = False, use_git: bool = True,
) -> list[Finding]:
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
            stored[path] = (root / path).read_bytes().decode("utf-8")  # read once, as stored (docs/design.md, R1a to R1d)
        except UnicodeDecodeError:
            findings.append(Finding(path, 0, INPUT_RULE, "file is not valid UTF-8"))
    ctx = Context(root, files, {p: stored[p] for p in family_paths[INSTRUCTION] if p in stored})
    texts = {INSTRUCTION: ctx.files} | {
        family: {p: normalize_newlines(stored[p]) for p in paths if p in stored}
        for family, paths in family_paths.items() if family != INSTRUCTION
    }
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
    findings = disable.apply(findings, ctx.files)
    findings = allowlist.apply(findings, config.entries, config.allowlist, set(analyzed), today)
    findings += overrides.stale(config.overrides, set(analyzed), root)
    if warn_as_error:
        findings = [replace(f, level="error") for f in findings]
    return sorted(findings, key=Finding.sort_key)
