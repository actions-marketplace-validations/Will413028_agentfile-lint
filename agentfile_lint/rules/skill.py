"""S1 to S14: SKILL.md files, grouped by the reader that would break (docs/adr/0007).

Two readers treat the same file differently. Claude Code ignores fields it does not know, takes a
`name` that differs from the directory and loads a skill whose YAML does not parse with no fields set.
claude.ai upload, the Skills API and the Agent Skills specification reject a key outside the
specification's six. Each id protects one reader or both (docs/rules.md); the default preset turns
on the Claude Code ids, and `preset:agentskills` adds the others. Which ids run is only their level.
S13 and S14 are about the body, whoever reads it: its size after compaction and the files it links to.

Runs on the skill file family (`[discover] skill_globs`), never on instruction files. Frontmatter
scalars are read as their text (`frontmatter.parse(strings=True)`): YAML 1.1 type resolution would
turn `description: yes` into a boolean and `2026-02-30` into a conversion error, which neither reader
sees.
"""
from __future__ import annotations

import posixpath
import re
import unicodedata
from typing import Any
from urllib.parse import unquote

from .. import frontmatter
from ..context import Context
from ..discover import SKIP_DIRS
from ..errors import check_keys, expect_int, levels_only
from ..finding import Finding
from ._text import SPAN, parent_dirs, prose_lines, split_lines

FAMILY = "skill"

CHECKS = (
    ("S1", "skill-yaml", "SKILL.md frontmatter is valid YAML and a mapping"),
    ("S2", "skill-lines", "SKILL.md has fewer than 500 lines"),
    ("S3", "skill-listing-chars", "description plus when_to_use fit Claude Code's skill listing (max_chars)"),
    ("S4", "skill-metadata-map", "metadata is a map"),
    ("S5", "skill-frontmatter", "SKILL.md starts with YAML frontmatter"),
    ("S6", "skill-name-length", "name is a string of 1 to 64 characters"),
    ("S7", "skill-name-chars", "name is lowercase letters, digits and single inner hyphens"),
    ("S8", "skill-name-dir", "name equals the skill's directory name"),
    ("S9", "skill-description", "description is a string of 1 to 1024 characters"),
    ("S10", "skill-compatibility", "compatibility is a string of 1 to 500 characters"),
    ("S11", "skill-keys", "only the specification's six frontmatter keys"),
    ("S12", "skill-name-refused", "name and directory name hold no character Claude Code refuses"),
    ("S13", "skill-compaction-tokens", "the body fits what Claude Code keeps of a skill after compaction (max_tokens, estimated)"),
    ("S14", "skill-links", "a relative Markdown link in SKILL.md points to a tracked file or directory"),
)
WHOLE_FILE = ("S2", "S5", "S13")   # S12 on a directory name is line 0 too; S ids take no directive anyway

NON_STRING_KEY = "a mapping key is not a string"
MAX_LINES = 499         # "Keep SKILL.md under 500 lines"
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
SPEC_KEYS = ("allowed-tools", "compatibility", "description", "license", "metadata", "name")


def validate(shared: Any, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    s3 = tables["S3"]
    check_keys(s3, {"level", "max_chars"}, "rules.S3")
    # The preset sets 1536, Claude Code's default `skillListingMaxDescChars`.
    max_listing = expect_int(s3.get("max_chars"), "rules.S3.max_chars")
    s13 = tables["S13"]
    check_keys(s13, {"level", "max_tokens"}, "rules.S13")
    # The preset sets 5000, what Claude Code keeps of each invoked skill when it compacts the conversation.
    max_tokens = expect_int(s13.get("max_tokens"), "rules.S13.max_tokens")
    effective = levels_only({rule_id: table for rule_id, table in tables.items() if rule_id not in ("S3", "S13")})
    effective["S3"] = {"max_chars": max_listing}
    effective["S13"] = {"max_tokens": max_tokens}
    return {"max_listing": max_listing, "max_tokens": max_tokens}, effective


def check(path: str, text: str, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    return _check(path, text, params["max_listing"]) + _compaction(path, text, params["max_tokens"])


# An inline link `[text](target)` or `[text](target "title")`, not escaped; the target may hold one
# level of parentheses. Images are cut out first, so the image inside a linked image is not read.
_TARGET = r"\(\s*<?((?:[^()\s<>]|\([^()\s]*\))+)>?(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)"
_LINK = re.compile(r"(?<![!\\])\[[^\]\n]*\]" + _TARGET)
_IMAGE = re.compile(r"!\[[^\]\n]*\]" + _TARGET)
# Not a path in the repository: a URL scheme, an anchor, a site-absolute path, a template placeholder.
_NOT_A_PATH = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:|[#/]|.*[{}<>$]")


def check_repo(ctx: Context, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    """S14: links out of a SKILL.md are how the skill sends an agent to its reference files; a target
    that is not tracked is a file the agent is told to read and cannot."""
    found: list[Finding] = []
    if levels["S14"] == "off":
        return found
    for path, text in ctx.family_files.get(FAMILY, {}).items():
        split = frontmatter.split(text)
        body_start = split[1] if split is not None else 0   # an unterminated block: the whole file is body
        directory = posixpath.dirname(path)
        # Only the body: a fence or comment opened inside the frontmatter says nothing about the body.
        body = "\n".join(text.split("\n")[body_start:])
        for offset, line in prose_lines(body):
            number = offset + body_start
            # A code span or an image becomes a blank, so the text around it is not joined into a link.
            for m in _LINK.finditer(_IMAGE.sub(" ", SPAN.sub(" ", line))):
                target = unquote(re.split(r"[#?]", m.group(1))[0])
                # A bare word (`[text](url)` in an example) is not taken for a file name.
                if not target or _NOT_A_PATH.match(m.group(1)) or ("/" not in target and "." not in target):
                    continue
                resolved = posixpath.normpath(posixpath.join(directory, target))
                if resolved == ".." or resolved.startswith("../"):
                    continue   # outside the repository: not ours to know
                if resolved == "." or resolved in ctx.dirs:
                    continue
                # A tracked entry named with a trailing slash must be a directory: a symlink to one or a submodule.
                if resolved in ctx.tracked_set and (not target.endswith("/") or (ctx.root / resolved).is_dir()):
                    continue
                # Below a tracked symlink or submodule, or in a directory a `--no-git` walk never
                # enters: the file list does not show what is there.
                if any(d in ctx.tracked_set for d in parent_dirs(resolved + "/x")) or SKIP_DIRS & set(resolved.split("/")):
                    continue
                found.append(Finding(path, number, "S14", f"link target `{target}` is not a tracked file or directory "
                                     f"(looked for {resolved}); an agent that follows the link finds nothing"))
    return found


def estimated_tokens(text: str) -> int:
    """A tokenizer-free estimate: four ASCII characters or one other character to a token. English
    prose and code run near four characters a token and CJK text near one; the real count depends
    on the model."""
    ascii_chars = sum(1 for c in text if c < "\x80")
    return (ascii_chars + 3) // 4 + len(text) - ascii_chars


def _compaction(path: str, text: str, max_tokens: int) -> list[Finding]:
    """S13 on the body, the text an invocation puts in the conversation (the frontmatter is not part of it)."""
    found = frontmatter.split(text)
    body = text if found is None or found[1] == 0 else "\n".join(text.split("\n")[found[1]:])
    tokens = estimated_tokens(body.strip())
    if tokens <= max_tokens:
        return []
    return [Finding(path, 0, "S13", f"body is about {tokens} tokens (estimated at 4 ASCII or 1 other character "
                    f"per token); after compaction Claude Code keeps only the first {max_tokens} tokens of an "
                    "invoked skill, so the end of this one is lost in a long session")]


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


def _check(path: str, text: str, max_listing: int) -> list[Finding]:
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
    if len(listing) > max_listing:
        key = "description" if "description" in data else "when_to_use"
        found.append(Finding(path, line(key), "S3", f"description and when_to_use are {len(listing)} characters; "
                             f"Claude Code cuts each skill's listing text at {max_listing}"))
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
