"""S1 to S12: SKILL.md files, grouped by the reader that would break (docs/adr/0007).

Two readers treat the same file differently. Claude Code ignores fields it does not know, takes a
`name` that differs from the directory and loads a skill whose YAML does not parse with no fields set.
claude.ai upload, the Skills API and the Agent Skills specification reject a key outside the
specification's six. Each id belongs to the readers it protects (`READERS`); `[skills] targets` names
the readers a repository writes for, and an id none of them reads never runs, whatever its level.

Runs on the skill file family (`[discover] skill_globs`), never on instruction files. Frontmatter
scalars are read as their text (`frontmatter.parse(strings=True)`): YAML 1.1 type resolution would
turn `description: yes` into a boolean and `2026-02-30` into a conversion error, which neither reader
sees.
"""
from __future__ import annotations

import posixpath
import unicodedata
from typing import Any

from .. import frontmatter
from ..errors import ConfigError, check_keys, expect_str_list, levels_only
from ..finding import Finding
from ._text import split_lines

FAMILY = "skill"
SECTION = "skills"   # the top-level `[skills]` table this module validates

CLAUDE_CODE = "claude-code"
AGENTSKILLS = "agentskills"
TARGETS = (AGENTSKILLS, CLAUDE_CODE)

CHECKS = (
    ("S1", "skill-yaml", "SKILL.md frontmatter is valid YAML and a mapping"),
    ("S2", "skill-lines", "SKILL.md has fewer than 500 lines"),
    ("S3", "skill-listing-chars", "description plus when_to_use fit Claude Code's 1536-character skill listing"),
    ("S4", "skill-metadata-map", "metadata is a map"),
    ("S5", "skill-frontmatter", "SKILL.md starts with YAML frontmatter"),
    ("S6", "skill-name-length", "name is a string of 1 to 64 characters"),
    ("S7", "skill-name-chars", "name is lowercase letters, digits and single inner hyphens"),
    ("S8", "skill-name-dir", "name equals the skill's directory name"),
    ("S9", "skill-description", "description is a string of 1 to 1024 characters"),
    ("S10", "skill-compatibility", "compatibility is a string of 1 to 500 characters"),
    ("S11", "skill-keys", "only the specification's six frontmatter keys"),
    ("S12", "skill-name-refused", "name and directory name hold no character Claude Code refuses"),
)
READERS = {
    "S1": (CLAUDE_CODE, AGENTSKILLS), "S2": (CLAUDE_CODE, AGENTSKILLS),
    "S3": (CLAUDE_CODE,), "S4": (CLAUDE_CODE,), "S12": (CLAUDE_CODE,),
    **{rule_id: (AGENTSKILLS,) for rule_id in ("S5", "S6", "S7", "S8", "S9", "S10", "S11")},
}
WHOLE_FILE = ("S2", "S5")   # S12 on a directory name is line 0 too; S ids take no directive anyway

NON_STRING_KEY = "a mapping key is not a string"
MAX_LINES = 499         # "Keep SKILL.md under 500 lines"
MAX_LISTING = 1536      # Claude Code's default `skillListingMaxDescChars`
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
SPEC_KEYS = ("allowed-tools", "compatibility", "description", "license", "metadata", "name")


def validate(section: Any, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    section = {} if section is None else section
    check_keys(section, {"targets"}, SECTION)
    targets = expect_str_list(section.get("targets"), f"{SECTION}.targets", allow_empty=True)
    for i, target in enumerate(targets):
        if target not in TARGETS:
            raise ConfigError(f"{SECTION}.targets[{i}]: unknown reader {target!r} (expected: {', '.join(TARGETS)})")
    return {"targets": list(dict.fromkeys(targets))}, levels_only(tables)


def section_json(params: dict[str, Any]) -> dict[str, Any]:
    """The effective `[skills]` table, for `config --format json`."""
    return {"targets": params["targets"]}


def check(path: str, text: str, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    targets = set(params["targets"])
    return [f for f in _check(path, text) if targets & set(READERS[f.rule])]


def _refused(name: str) -> str | None:
    """Why Claude Code refuses `name` (skills docs, "Characters a skill name can't hold"), or None."""
    for i, c in enumerate(name):
        category = unicodedata.category(c)
        if c in "<>":
            return f"{c!r}"
        if c == " ":
            if i == 0 or i == len(name) - 1 or name[i + 1] == " ":
                return "a space at the start or end, or two in a row"
        elif category in ("Cc", "Cf"):
            return f"control or format character U+{ord(c):04X} (zero-width, direction-changing or control)"
        elif category in ("Co", "Cn"):
            return f"private-use or unassigned character U+{ord(c):04X}"
        elif category in ("Zs", "Zl", "Zp"):
            return f"blank U+{ord(c):04X} other than a plain space"
    return None


def _check(path: str, text: str) -> list[Finding]:
    found: list[Finding] = []
    directory_raw = posixpath.basename(posixpath.dirname(path))
    why = _refused(directory_raw) if directory_raw else None
    if why:
        found.append(Finding(path, 0, "S12", f"directory name {directory_raw!r} has {why}, which Claude Code refuses: "
                             "the skill does not load (in a plugin's skills/ the characters become hyphens)"))
    lines = len(split_lines(text))
    if lines > MAX_LINES:
        found.append(Finding(path, 0, "S2", f"SKILL.md has {lines} lines; keep it under {MAX_LINES + 1} "
                             "and move reference material to separate files"))
    fm = frontmatter.parse(text, strings=True)
    if fm is None:
        found.append(Finding(path, 0, "S5", "no YAML frontmatter; the specification requires it, "
                             "starting with '---' on the first line"))
        return found
    if fm.error is not None:
        if fm.error.endswith(NON_STRING_KEY):   # readers differ here; do not claim what Claude Code does
            consequence = "YAML readers differ on such a key; write it as a plain string"
        else:
            consequence = "Claude Code loads the skill with no fields set"
        found.append(Finding(path, fm.line, "S1", f"{fm.error}; {consequence}"))
        return found
    data = {} if fm.value is None else fm.value
    if not isinstance(data, dict):
        found.append(Finding(path, 1, "S1", f"frontmatter is a YAML {type(data).__name__}, not a mapping; "
                             "Claude Code loads the skill with no fields set"))
        return found
    line = lambda key: fm.keys.get(key, 1)  # noqa: E731

    listing = "".join(v for v in (data.get("description"), data.get("when_to_use")) if isinstance(v, str))
    if len(listing) > MAX_LISTING:
        key = "description" if "description" in data else "when_to_use"
        found.append(Finding(path, line(key), "S3", f"description and when_to_use are {len(listing)} characters; "
                             f"Claude Code cuts each skill's listing text at {MAX_LISTING}"))
    if "metadata" in data and not isinstance(data["metadata"], dict):
        found.append(Finding(path, line("metadata"), "S4", "metadata is not a map; Claude Code drops it"))

    name = data.get("name")
    # A block scalar (`name: |`) ends in a line break that is YAML syntax, not part of the name.
    why = _refused(name.rstrip("\n")) if isinstance(name, str) else None
    if why:
        found.append(Finding(path, line("name"), "S12", f"name {name!r} has {why}, which Claude Code refuses: "
                             "the / menu does not show it and typing it does not invoke the skill"))
    if not isinstance(name, str) or not name.strip():
        found.append(Finding(path, line("name"), "S6", "name is required: a non-empty string"))
    else:
        name = unicodedata.normalize("NFKC", name.strip())
        if len(name) > MAX_NAME:
            found.append(Finding(path, line("name"), "S6", f"name is {len(name)} characters, limit {MAX_NAME}"))
        if not _name_chars_ok(name):
            found.append(Finding(path, line("name"), "S7", f"name {name!r} must be lowercase letters, digits and "
                                 "hyphens, without a leading, trailing or doubled hyphen"))
        directory = unicodedata.normalize("NFKC", directory_raw)
        # A SKILL.md at the repository root lives in the checkout's directory, whose name is not known.
        if directory and directory != name:
            found.append(Finding(path, line("name"), "S8", f"name {name!r} differs from its directory {directory!r}"))

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        found.append(Finding(path, line("description"), "S9", "description is required: a non-empty string"))
    elif len(description) > MAX_DESCRIPTION:
        found.append(Finding(path, line("description"), "S9",
                             f"description is {len(description)} characters, limit {MAX_DESCRIPTION}"))

    if "compatibility" in data:
        value = data["compatibility"]
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_COMPATIBILITY:
            what = f"{len(value)} characters" if isinstance(value, str) else f"a YAML {type(value).__name__}"
            found.append(Finding(path, line("compatibility"), "S10",
                                 f"compatibility is {what}; it must be a string of 1 to {MAX_COMPATIBILITY}"))

    extra = sorted(str(k) for k in data if k not in SPEC_KEYS)
    if extra:
        first = next(k for k in data if k not in SPEC_KEYS)
        found.append(Finding(path, line(str(first)), "S11", f"key(s) {', '.join(extra)} outside the specification's "
                             f"{', '.join(SPEC_KEYS)}; claude.ai upload and the Skills API reject them"))
    return found


def _name_chars_ok(name: str) -> bool:
    """The reference validator's reading (skills-ref): after NFKC, lowercase, every character
    alphanumeric or `-`, no leading, trailing or doubled hyphen."""
    return (
        name == name.lower()
        and not name.startswith("-") and not name.endswith("-") and "--" not in name
        and all(c.isalnum() or c == "-" for c in name)
    )
