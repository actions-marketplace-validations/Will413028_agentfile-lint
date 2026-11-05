"""Command line entry point.

Output: every finding on stdout, by default one line each, `file:line: severity: rule-id: message`
(`file: severity: rule-id: message` for a whole-file finding); `--format json|github` in `finding.py`,
`--format sarif` in `sarif.py`.
Usage and config problems go to stderr. Exit codes: 0 no errors (warnings allowed), 1 at least one
error, 2 usage or config problem.
"""
from __future__ import annotations

import sys

if sys.version_info < (3, 11):  # checked before importing anything that needs tomllib
    sys.stderr.write(f"agentfile-lint needs Python >= 3.11, found {sys.version.split()[0]}\n")
    raise SystemExit(2)

import argparse
import datetime
import os
from pathlib import Path

from . import __version__
from . import config as config_mod
from . import discover, engine, sarif
from .errors import ConfigError
from .engine import PSEUDO_RULES
from .finding import RENDERERS, dump_json
from .rules import DESCRIPTIONS, NAMES, RULES


# `--format` value -> renderer; SARIF lives outside `finding.py` because it needs the rule table.
FORMATS = {**RENDERERS, "sarif": sarif.render}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentfile-lint", description="Lint agent instruction files.")
    p.add_argument("files", nargs="*", help="only decides whether to run; the full file set is always analyzed")
    p.add_argument("--config", help=f"config file (default: {config_mod.CONFIG_NAME} at the repo root, if present)")
    p.add_argument("--today", help="YYYY-MM-DD, replaces the current date (reproducible runs)")
    p.add_argument("--version", action="version", version=f"agentfile-lint {__version__}")
    p.add_argument("--list-rules", action="store_true", help="print the rules and their effective levels, then exit")
    p.add_argument("--warn-as-error", action="store_true", help="treat warnings as errors")
    p.add_argument("--format", choices=list(FORMATS), default="text",
                   help="output format for findings: text (default), json, github (workflow commands) or sarif (2.1.0)")
    p.add_argument("--no-git", action="store_true",
                   help="walk the current directory instead of listing git-tracked files (skips .git, node_modules and similar)")
    return p


def _relevant(files: list[str], root: Path, cwd: Path, globs: list[str]) -> bool:
    """argv names only decide whether to run at all (full-set semantics)."""
    for name in files:
        try:
            rel = Path(os.path.abspath(cwd / name)).relative_to(root).as_posix()
        except ValueError:
            continue
        if rel == config_mod.CONFIG_NAME or discover.matches(rel, globs):
            return True
    return False


def _config_main(argv: list[str]) -> int:
    """`agentfile-lint config --format json`: the effective (merged, validated) configuration."""
    p = argparse.ArgumentParser(prog="agentfile-lint config", description="Print the effective configuration.")
    p.add_argument("--format", choices=["json"], default="json", help="output format (only json)")
    p.add_argument("--config", help=f"config file (default: {config_mod.CONFIG_NAME} at the repo root, if present)")
    p.add_argument("--today", help="YYYY-MM-DD, used to validate allowlist expiry dates")
    args = p.parse_args(argv)
    try:
        today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    except ValueError:
        sys.stderr.write("agentfile-lint: --today must be YYYY-MM-DD\n")
        return 2
    try:
        cfg_path = Path(args.config) if args.config else None
        if cfg_path is None:
            try:
                root = discover.repo_root(Path.cwd())
            except discover.DiscoverError:
                root = None
            cfg_path = config_mod.default_config_path(root)
        cfg = config_mod.load(cfg_path, today)
    except ConfigError as exc:
        sys.stderr.write(f"agentfile-lint: {exc}\n")
        return 2
    sys.stdout.write(dump_json(config_mod.to_jsonable(cfg)))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "vendor":  # subcommand; any other first word keeps the check CLI
        try:
            from . import vendor
        except ImportError:
            sys.stderr.write("agentfile-lint: vendor is only available from a source checkout\n")
            return 2
        return vendor.main(argv[1:])
    if argv and argv[0] == "check-pins":
        from . import check_pins
        return check_pins.main(argv[1:])
    if argv and argv[0] == "config":
        return _config_main(argv[1:])
    args = _parser().parse_args(argv)
    try:
        today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    except ValueError:
        sys.stderr.write("agentfile-lint: --today must be YYYY-MM-DD\n")
        return 2
    cwd = Path.cwd()
    try:
        if args.no_git:
            root = cwd
        else:
            try:
                root = discover.repo_root(cwd)
            except discover.DiscoverError:
                if not args.list_rules:
                    raise
                root = None
        cfg_path = Path(args.config) if args.config else None
        if cfg_path is None:
            cfg_path = config_mod.default_config_path(root)
        cfg = config_mod.load(cfg_path, today)
    except (ConfigError, discover.DiscoverError) as exc:
        sys.stderr.write(f"agentfile-lint: {exc}\n")
        return 2

    if args.list_rules:
        for rule_id in RULES:
            print(f"{rule_id}  {cfg.rules[rule_id]['level']:<5}  {NAMES[rule_id]}: {DESCRIPTIONS[rule_id]}")
        for rule_id, text in PSEUDO_RULES.items():
            print(f"{rule_id}  error  {text}")
        return 0

    findings = []
    if not args.files or _relevant(args.files, root, cwd, cfg.all_globs):
        try:
            findings = engine.analyze(root, cfg, today, args.warn_as_error, use_git=not args.no_git)
        except discover.DiscoverError as exc:  # an unreadable directory in the --no-git walk
            sys.stderr.write(f"agentfile-lint: {exc}\n")
            return 2
    if hasattr(sys.stdout, "reconfigure"):  # findings quote file text; a cp1252 pipe must not crash
        sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(FORMATS[args.format](findings))  # an irrelevant run still prints valid JSON
    sys.stdout.flush()
    return 1 if any(f.level == "error" for f in findings) else 0
