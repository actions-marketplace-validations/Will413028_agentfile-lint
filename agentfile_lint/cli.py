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
from . import discover, engine, fix, sarif
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
    p.add_argument("--format", choices=list(FORMATS),
                   help="output format for findings: text (default), json, github (workflow commands) or sarif (2.1.0)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--fix", action="store_true", help="apply safe fixes, then report what is left")
    mode.add_argument("--diff", action="store_true",
                      help="print the fixes as a unified diff instead of writing them")
    p.add_argument("--unsafe-fixes", action="store_true", help="with --fix or --diff, include unsafe fixes")
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
        if rel == config_mod.CONFIG_NAME or discover.discovered(rel, globs):
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


def _plan_fixes(args, root: Path, cfg, cfg_path: Path | None, today: datetime.date, analysis) -> fix.Plan:
    """The fixes of this run, applied in memory and checked by a second run (fix safety net 2)."""
    config_key = engine.edit_path(root, cfg.source.path) if cfg.source else None

    def rerun(texts: dict[str, str]):
        again = cfg
        if config_key in texts:
            try:
                again = config_mod.load(cfg_path, today, texts[config_key])
            except ConfigError as exc:
                raise fix.Rejected(f"the edited config does not load ({exc})") from exc
            # Exceptions only shrink (docs/adr/0005): whatever the edit, the effective entries after it
            # must be among those before, none with a higher count (an inherited list that comes back
            # when the file's own goes is caught here).
            wider = fix.widened(cfg.entries, again.entries)
            if wider:
                raise fix.Rejected(f"the edited config would allow more exceptions ({', '.join(wider)})")
        result = engine.run(root, again, today, args.warn_as_error, use_git=not args.no_git,
                            replaced={p: t for p, t in texts.items() if p != config_key})
        return result.findings, result.suppressed, result.texts

    return fix.plan(analysis.findings, analysis.suppressed, analysis.texts, args.unsafe_fixes, rerun)


def _count(n: int, word: str, plural: str = "") -> str:
    return f"{n} {word}" if n == 1 else f"{n} {plural or word + 's'}"


def _report_fixes(outcome: fix.Plan, written: bool) -> None:
    """A summary on stderr, so stdout stays findings only (or the diff)."""
    for note in outcome.skipped:
        sys.stderr.write(f"agentfile-lint: {note}\n")
    if written and outcome.texts:
        sys.stderr.write(f"agentfile-lint: applied {_count(outcome.fixed, 'fix', 'fixes')} "
                         f"in {_count(len(outcome.texts), 'file')}\n")
    if outcome.held_unsafe:
        more = "1 more fix" if outcome.held_unsafe == 1 else f"{outcome.held_unsafe} more fixes"
        sys.stderr.write(f"agentfile-lint: {more} available with --unsafe-fixes\n")


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
    parser = _parser()
    args = parser.parse_args(argv)
    if args.unsafe_fixes and not (args.fix or args.diff):
        parser.error("--unsafe-fixes needs --fix or --diff")
    if args.diff and args.format not in (None, "text"):
        parser.error("--diff prints a diff, not findings; drop --format")
    args.format = args.format or "text"
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
    if not args.files or _relevant(args.files, root, cwd, cfg.all_globs()):
        try:
            analysis = engine.run(root, cfg, today, args.warn_as_error, use_git=not args.no_git)
            findings = analysis.findings
            if args.fix or args.diff:
                outcome = _plan_fixes(args, root, cfg, cfg_path, today, analysis)
        except discover.DiscoverError as exc:  # an unreadable directory in the --no-git walk
            sys.stderr.write(f"agentfile-lint: {exc}\n")
            return 2
    elif args.fix or args.diff:
        outcome = fix.Plan({}, 0, 0, [], None)
    if hasattr(sys.stdout, "reconfigure"):  # findings quote file text; a cp1252 pipe must not crash
        sys.stdout.reconfigure(encoding="utf-8")
    if args.diff:  # exit codes keep their meaning (docs/adr/0004): from the findings, nothing was fixed
        sys.stdout.write(fix.diff(outcome.texts))
        _report_fixes(outcome, written=False)
        return 1 if any(f.level == "error" for f in findings) else 0
    if args.fix:
        try:
            fix.write(root, outcome.texts)
        except OSError as exc:
            sys.stderr.write(f"agentfile-lint: {exc}\n")
            return 2
        _report_fixes(outcome, written=True)
        if outcome.findings is not None:
            findings = outcome.findings
    sys.stdout.write(FORMATS[args.format](findings))  # an irrelevant run still prints valid JSON
    sys.stdout.flush()
    return 1 if any(f.level == "error" for f in findings) else 0
