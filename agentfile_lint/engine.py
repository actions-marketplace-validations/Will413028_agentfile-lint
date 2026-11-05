"""Run the enabled rules over the full instruction-file set."""
from __future__ import annotations

import datetime
from dataclasses import replace
from pathlib import Path

from . import allowlist, disable, discover, overrides
from .config import Config
from .context import Context
from .finding import INPUT_RULE, Finding
from .rules import MODULES


# Rules with no module and no `[rules]` level, always on: id -> description (`--list-rules`, SARIF).
PSEUDO_RULES = {
    allowlist.RULE_ID: "expired, no-longer-needed or miscounted allowlist entries; warns before expiry and on an override glob that matches no file (always on)",
    disable.RULE_ID: "malformed per-line directives; warns on a directive that suppresses nothing (always on)",
    INPUT_RULE: "instruction file is not valid UTF-8; only an allowlist entry can exempt it (always on)",
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
    paths = discover.instruction_files(root, config.all_globs, files)
    alias = discover.aliases(root, paths)
    paths = [p for p in paths if p not in alias]
    findings: list[Finding] = []
    raw: dict[str, str] = {}
    for path in paths:
        try:
            raw[path] = (root / path).read_bytes().decode("utf-8")  # read once, as stored (docs/design.md, R1a to R1d)
        except UnicodeDecodeError:
            findings.append(Finding(path, 0, INPUT_RULE, "file is not valid UTF-8"))
    ctx = Context(root, files, raw)
    for module in MODULES:
        base = {rule_id: config.rules[rule_id]["level"] for rule_id, _, _ in module.CHECKS}
        # A rule runs at the highest level a `raise` override can give it, so it has findings to raise.
        levels = {rule_id: overrides.run_level(rule_id, level, config.overrides) for rule_id, level in base.items()}
        if all(level == "off" for level in levels.values()):
            continue
        params = config.params[module.__name__]
        found: list[Finding] = []
        if hasattr(module, "check"):
            for path, text in ctx.files.items():
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
    findings = allowlist.apply(findings, config.entries, config.allowlist, set(paths), today)
    findings += overrides.stale(config.overrides, set(paths), root)
    if warn_as_error:
        findings = [replace(f, level="error") for f in findings]
    return sorted(findings, key=Finding.sort_key)
