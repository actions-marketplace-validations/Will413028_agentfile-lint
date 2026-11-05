"""`agentfile-lint check-pins`: every reference to this tool in a repository pins the same full SHA.

A consumer references the tool from several places (a pre-commit hook, a lefthook command, CI
workflows). If they pin different commits, the local hook and CI quietly run different rules.

There is no YAML parser here (standard library only); the files are scanned line by line:

- pre-commit: a `repo:` line whose value contains the repo string starts an entry; the next `rev:`
  line before the following `repo:` line is its pin.
- anywhere else (lefthook, workflows): a line that contains the repo string and `@<ref>`, as in
  `uvx --from git+https://host/owner/agentfile-lint@<sha>` or `uses: owner/agentfile-lint@<sha>`.
  A `uses:`/`git+` line naming the repo with no `@<ref>` is reported as unpinned.

Limits: no anchors/aliases, no multi-line scalars, no expression expansion (`${{ ... }}` is not a SHA
and is reported), no references built from several variables, and a reference inside a comment is
still read. Anything the scan does not recognise is simply not seen: it checks consistency of what
it finds, it does not prove there is nothing else.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config as config_mod
from . import discover
from .errors import ConfigError
from .finding import Finding
from .rules._text import split_lines

SHA = re.compile(r"[0-9a-f]{40}")
_REPO_LINE = re.compile(r"^\s*(?:-\s+)?repo:\s*(\S+)")
_REV_LINE = re.compile(r"^\s*(?:-\s+)?rev:\s*(?P<q>['\"]?)(?P<ref>[^\s'\"#]*)(?P=q)")
_PIN_KEYWORDS = ("uses:", "git+", "--from")


@dataclass(frozen=True)
class Ref:
    path: str
    line: int
    ref: str  # "" when the reference carries no @ref / rev


def scan(path: str, text: str, repo: str) -> list[Ref]:
    refs: list[Ref] = []
    lines = split_lines(text)
    at_ref = re.compile(re.escape(repo) + r"[^\s'\"@]*@(?P<ref>[^\s'\"#]+)")
    in_entry = False
    entry_line = 0
    for number, line in enumerate(lines, start=1):
        m = _REPO_LINE.match(line)
        if m:
            if in_entry:  # previous entry never had a rev
                refs.append(Ref(path, entry_line, ""))
            in_entry = repo in m.group(1) and m.group(1) != "local"
            entry_line = number
            continue
        if in_entry:
            rev = _REV_LINE.match(line)
            if rev:
                refs.append(Ref(path, number, rev.group("ref")))
                in_entry = False
            continue
        if repo in line:
            found = at_ref.search(line)
            if found:
                refs.append(Ref(path, number, found.group("ref")))
            elif any(k in line for k in _PIN_KEYWORDS) and not line.lstrip().startswith("#"):
                refs.append(Ref(path, number, ""))
    if in_entry:
        refs.append(Ref(path, entry_line, ""))
    return refs


def evaluate(refs: list[Ref]) -> list[tuple[str, int, str]]:
    """Problems as (path, line, message): not a full SHA, or a SHA that differs from the first one."""
    problems: list[tuple[str, int, str]] = []
    first: Ref | None = None
    for r in refs:
        if not SHA.fullmatch(r.ref):
            shown = r.ref or "(none)"
            problems.append((r.path, r.line, f"reference is pinned to {shown!r}, not a full 40-hex commit SHA"))
        elif first is None:
            first = r
        elif r.ref != first.ref:
            problems.append((r.path, r.line, f"pinned to {r.ref}, but {first.path}:{first.line} pins {first.ref}"))
    return problems


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="agentfile-lint check-pins", description="(experimental) Check that every reference to this tool pins the same full commit SHA.")
    p.add_argument("--repo", help="string identifying this tool's repository in a reference (default: check_pins.repo from the config, else 'agentfile-lint')")
    p.add_argument("--config", help=f"config file (default: {config_mod.CONFIG_NAME} at the repo root, if present)")
    p.add_argument("--files", nargs="+", metavar="GLOB", help="files to scan, as globs relative to the repo root (default: check_pins.files)")
    p.add_argument("--require-refs", action="store_true", help="fail when no reference is found (default: report and pass)")
    args = p.parse_args(argv)
    try:
        root = discover.repo_root(Path.cwd())
        cfg_path = Path(args.config) if args.config else None
        if cfg_path is None:
            cfg_path = config_mod.default_config_path(root)
        import datetime
        cfg = config_mod.load(cfg_path, datetime.date.today())
    except (ConfigError, discover.DiscoverError) as exc:
        sys.stderr.write(f"agentfile-lint: {exc}\n")
        return 2
    repo = args.repo or cfg.check_pins["repo"]
    globs = args.files or cfg.check_pins["files"]
    refs: list[Ref] = []
    for path in discover.tracked_files(root):
        if any(fnmatch.fnmatchcase(path, g) for g in globs) and (root / path).is_file():
            try:
                text = (root / path).read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            refs.extend(scan(path, text, repo))
    problems = evaluate(refs)
    # Findings on stdout in the main command's text format; summaries on stderr (docs/adr/0004).
    for path, line, message in problems:
        print(Finding(path, line, "check-pins", message).format())
    if problems:
        return 1
    if not refs:
        if args.require_refs:
            print(f"check-pins: error: no reference to {repo!r} found")
            return 1
        print(f"check-pins: no reference to {repo!r} found in {len(globs)} file pattern(s)", file=sys.stderr)
        return 0
    print(f"check-pins: {len(refs)} reference(s) to {repo!r}, all pinned to {refs[0].ref}", file=sys.stderr)
    return 0
