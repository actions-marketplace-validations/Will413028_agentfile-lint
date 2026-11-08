"""Shared test helpers: temporary git repos and subprocess runners."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
LEGACY = FIXTURES / "legacy-oracle" / "check-agents-md.py"
HAWKR_LIMITS = FIXTURES / "hawkr-limits.toml"


def make_repo(files: dict[str, str | bytes], track: bool = True, symlinks: dict[str, str] | None = None) -> Path:
    """Create a temp git repo. Files are written byte-exact; `symlinks` maps a link path to its
    target (as written into the link); `track` runs `git add -A`."""
    root = Path(tempfile.mkdtemp(prefix="il-test-"))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    # Hermetic: a machine-wide ignore file (core.excludesFile) must not decide what gets tracked.
    subprocess.run(["git", "-C", str(root), "config", "core.excludesFile", "/dev/null"], check=True)
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    for name, target in (symlinks or {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
    if track:
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return root


def run_new(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(REPO))
    return subprocess.run(
        [sys.executable, "-m", "agentfile_lint", *args],
        cwd=root, env=env, capture_output=True, text=True,
    )


FINDING_LINE = re.compile(r"^[^:]+(?::\d+)?: (error|warning): [^:\s]+: ")


def by_severity(r: subprocess.CompletedProcess) -> tuple[list[str], list[str]]:
    """The text-format findings on stdout as (warning lines, error lines). Every stdout line must be
    a finding, and findings never go to stderr (it is for usage and config problems only)."""
    warnings, errors = [], []
    for line in r.stdout.splitlines():
        m = FINDING_LINE.match(line)
        assert m, f"stdout line is not a text-format finding: {line!r}"
        (errors if m.group(1) == "error" else warnings).append(line)
    return warnings, errors


def run_legacy(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(LEGACY)], cwd=root, capture_output=True, text=True,
    )
