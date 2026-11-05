"""A finding and the output formats (`docs/design.md`, Output and exit codes; docs/adr/0004)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable

# Pseudo rule for an instruction file that is not valid UTF-8. No rule module and no `[rules]` level:
# it is always on, and only an allowlist entry can exempt a file.
INPUT_RULE = "E0"
# Config level -> printed severity. Configs say `warn`; output says `warning`, as gcc and GitHub do.
SEVERITY = {"error": "error", "warn": "warning"}
# Version of the JSON document: goes up only when a field is removed or changes meaning.
JSON_VERSION = 1


@dataclass(frozen=True)
class Finding:
    """One problem. `line` is 1-based; 0 means the finding is about the whole file."""

    path: str
    line: int
    rule: str
    message: str
    level: str = "error"  # error | warn

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


def _render_json(findings: Iterable[Finding]) -> str:
    doc = {
        "version": JSON_VERSION,
        "findings": [
            {"file": f.path, "line": f.line or None, "level": f.severity, "rule": f.rule, "message": f.message}
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
