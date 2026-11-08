"""A finding and the output formats (`docs/design.md`, Output and exit codes; docs/adr/0004)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Iterable

# Pseudo rule for an instruction file that is not valid UTF-8. No rule module and no `[rules]` level:
# it is always on, and only an allowlist entry can exempt a file.
INPUT_RULE = "E0"
# Config level -> printed severity. Configs say `warn`; output says `warning`, as gcc and GitHub do.
SEVERITY = {"error": "error", "warn": "warning"}
# Version of the JSON document: goes up only when a field is removed or changes meaning.
JSON_VERSION = 1


# Fix applicability, as ruff names it: `--fix` applies safe fixes, `--unsafe-fixes` adds unsafe ones.
SAFE = "safe"
UNSAFE = "unsafe"


@dataclass(frozen=True)
class Edit:
    """Replace the text from `start` up to (not including) `end` in file `path` with `text`.

    Positions are (line, column), both 1-based, columns in Unicode code points, lines as
    `rules._text.split_lines` counts them; `end` may be the line after the last one (end of file).
    `path` is relative to the repository root unless it is absolute (a config file outside it)."""

    path: str
    start: tuple[int, int]
    end: tuple[int, int]
    text: str


@dataclass(frozen=True)
class Fix:
    """Edits that resolve one finding, applied together or not at all (docs/design.md, Fixes)."""

    applicability: str  # SAFE | UNSAFE
    description: str
    edits: tuple[Edit, ...]


@dataclass(frozen=True)
class Finding:
    """One problem. `line` is 1-based; 0 means the finding is about the whole file."""

    path: str
    line: int
    rule: str
    message: str
    level: str = "error"  # error | warn
    # Not part of the finding's identity: equality, sorting and the text format ignore it.
    fix: Fix | None = field(default=None, compare=False)

    @property
    def severity(self) -> str:
        return SEVERITY[self.level]

    def format(self) -> str:
        """Text contract: `file:line: severity: rule-id: message`; a whole-file finding has no `:line`."""
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}: {self.severity}: {self.rule}: {self.message}"

    def sort_key(self) -> tuple:
        return (self.path, self.line, self.rule, self.message)


def _escape_data(text: str) -> str:
    # actions/toolkit packages/core/src/command.ts `escapeData`.
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    # actions/toolkit packages/core/src/command.ts `escapeProperty`.
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def format_github(f: Finding) -> str:
    """A GitHub workflow command. GitHub has no whole-file annotation; without `line` its API reports
    `start_line` 0.
    The message is the text line, so findings past GitHub's annotation limits keep their location in
    the log."""
    props = [f"file={_escape_property(f.path)}"]
    if f.line:
        props.append(f"line={f.line}")
    props.append(f"title={_escape_property(f.rule)}")
    return f"::{f.severity} {','.join(props)}::{_escape_data(f.format())}"


def dump_json(obj: object) -> str:
    """The one JSON encoding of every JSON output (findings and `config --format json`)."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _position(where: tuple[int, int]) -> dict[str, int]:
    return {"line": where[0], "column": where[1]}


def fix_json(fix: Fix | None) -> dict | None:
    if fix is None:
        return None
    return {
        "applicability": fix.applicability,
        "description": fix.description,
        "edits": [
            {"file": e.path, "start": _position(e.start), "end": _position(e.end), "text": e.text}
            for e in fix.edits
        ],
    }


def _render_json(findings: Iterable[Finding]) -> str:
    doc = {
        "version": JSON_VERSION,
        "findings": [
            {"file": f.path, "line": f.line or None, "level": f.severity, "rule": f.rule, "message": f.message,
             "fix": fix_json(f.fix)}
            for f in findings
        ],
    }
    return dump_json(doc)


def _per_line(one: Callable[[Finding], str]) -> Callable[[Iterable[Finding]], str]:
    return lambda findings: "".join(one(f) + "\n" for f in findings)


# `--format` value -> the complete stdout for a list of findings (`sarif` is added in `cli`).
RENDERERS: dict[str, Callable[[Iterable[Finding]], str]] = {
    "text": _per_line(Finding.format),
    "json": _render_json,
    "github": _per_line(format_github),
}
