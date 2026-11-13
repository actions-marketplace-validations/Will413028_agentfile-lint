"""Rule registry. A rule module may report several rule ids from one computation (docs/adr/0005).

Each module exposes:
- `CHECKS`: ((id, name, description), ...), one entry per rule id it reports. Every id has its own
  level; a finding carries the id of the check that produced it.
- `WHOLE_FILE` (optional): ids whose findings are about a whole file or its frontmatter; per-line
  directives reject them.
- `SHARED` (optional): (group, keys), the `[shared.<group>]` table its ids share.
- `FAMILY` (optional, default "instruction"): the file family `check` runs on, one of `FAMILIES`.
  Instruction files are `[discover] globs`; every other family is `[discover] <family>_globs`
  (docs/design.md, File families).
- `validate(shared, tables)`: `shared` is the validated-for-keys `[shared.<group>]` table (or None),
  `tables` maps each of its ids to its `[rules.<id>]` table; returns (params, effective): the module's
  params and, for each of its ids, its effective `[rules.<id>]` table (defaults filled in; `level`
  is set from the merged table), which `Config.rules` and `config --format json` show.
- `check(path, text, params, levels)` (one file, newlines normalized) and/or
  `check_repo(ctx, params, levels)` (the whole tracked set; a module of another family finds its
  files in `ctx.family_files`); `levels` maps each of its ids to its level.
  The engine runs a module once unless all its ids are off and drops findings of an id that is off.
Rules read parameters only; repo-specific behaviour is configuration, never a branch in code.
"""
from __future__ import annotations

from . import claude_md, constants, duplicate, hooks, mcp, paths, rot, rule_files, shape, size, skill, specrefs, testnames

MODULES = (size, shape, testnames, paths, specrefs, rot, duplicate, constants, claude_md, rule_files, skill, hooks, mcp)

# rule id -> its module, in report order.
RULES = {rule_id: module for module in MODULES for rule_id, _, _ in module.CHECKS}
NAMES = {rule_id: name for module in MODULES for rule_id, name, _ in module.CHECKS}
DESCRIPTIONS = {rule_id: desc for module in MODULES for rule_id, _, desc in module.CHECKS}

# Each check's name is an alias for its id in config files (docs/adr/0004).
ALIASES = {name: rule_id for rule_id, name in NAMES.items()}
if len(ALIASES) != len(RULES) or set(ALIASES) & set(RULES):
    raise RuntimeError("rule names must be unique and must not equal a rule id")

INSTRUCTION = "instruction"
# Every file family, in discovery order: instruction files, SKILL.md, hooks settings, .mcp.json.
FAMILIES = (INSTRUCTION, "skill", "hooks", "mcp")
# File family -> what its files are, for messages.
FAMILY_FILES = {
    INSTRUCTION: "instruction files", "skill": "SKILL.md files", "hooks": "Claude Code settings files",
    "mcp": ".mcp.json files",
}
# rule module -> the file family it checks.
FAMILY = {module: getattr(module, "FAMILY", INSTRUCTION) for module in MODULES}
if not set(FAMILY.values()) <= set(FAMILIES):
    raise RuntimeError("a rule module names a file family that FAMILIES does not list")

# `[shared.<group>]` -> its allowed keys.
SHARED = {module.SHARED[0]: set(module.SHARED[1]) for module in MODULES if hasattr(module, "SHARED")}

# Ids and aliases split in 0.7.0 (docs/adr/0005): a configuration error naming the new ids, never an
# alias for the group. Migration aid like the removed-key hints in the rule modules; remove both at 1.0.
_SPLIT = {"R1": ("size", ("R1a", "R1b", "R1c", "R1d")), "R4": ("rot", ("R4a", "R4b")), "R5": ("duplicates", ("R5a", "R5b"))}
RETIRED = {
    key: f"{old} ({alias}) was split in 0.7.0 into "
    + ", ".join(f"{i} ({NAMES[i]})" for i in new)
    + "; name the one you mean (docs/adr/0005)"
    for old, (alias, new) in _SPLIT.items()
    for key in (old, alias)
}
if set(RETIRED) & (set(RULES) | set(ALIASES)):
    raise RuntimeError("a retired rule id or alias is in use again")
