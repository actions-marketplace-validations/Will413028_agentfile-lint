"""`agentfile-lint vendor --to DIR`: write a self-contained, reproducible copy of the runner.

The copy holds the package (python files and the default preset), an entry script, verify.py and
a README with the upstream tag, commit and a SHA-256 per file. Output depends only on the source
files and the two upstream values: no timestamps, paths or user names, fixed file order.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__

PKG = Path(__file__).resolve().parent
ENTRY_NAME = "agentfile-lint.py"
BEGIN = "<!-- manifest:begin -->"
END = "<!-- manifest:end -->"


def _git(args: list[str]) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(PKG.parent), *args], capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _upstream(ref_tag: str | None, ref_commit: str | None) -> tuple[str, str]:
    tag = ref_tag or _git(["describe", "--tags", "--exact-match"]) or "untagged"
    commit = ref_commit
    if commit is None:
        commit = _git(["rev-parse", "HEAD"]) or "unknown"
        if commit != "unknown" and _git(["status", "--porcelain", "--", "agentfile_lint"]):
            commit += "-dirty"  # the copy differs from the recorded commit
    return tag, commit


# Non-Python files of vendored third-party code that the copy must carry (license and source record).
VENDORED_NOTICES = ("_yaml/LICENSE", "_yaml/PROVENANCE")


def _package_files() -> dict[str, bytes]:
    """Relative path (posix) -> content, sorted. Excludes caches and the vendoring machinery."""
    out: dict[str, bytes] = {}
    for path in sorted(PKG.rglob("*")):
        rel = path.relative_to(PKG)
        if "__pycache__" in rel.parts or "_vendor" in rel.parts or not path.is_file():
            continue
        if rel.as_posix() == "vendor.py":
            continue
        if path.suffix not in (".py", ".toml") and rel.as_posix() not in VENDORED_NOTICES:
            continue
        out[f"agentfile_lint/{rel.as_posix()}"] = path.read_bytes()
    return out


def build(tag: str, commit: str) -> dict[str, bytes]:
    files = _package_files()
    for name, template in ((ENTRY_NAME, "entry.py.txt"), ("verify.py", "verify.py.txt")):
        files[name] = (PKG / "_vendor" / template).read_bytes()
    files = dict(sorted(files.items()))
    manifest = "\n".join(f"{hashlib.sha256(c).hexdigest()}  {n}" for n, c in files.items())
    readme = f"""# agentfile-lint (vendored copy)

A pinned copy of agentfile-lint. Standard library plus the vendored PyYAML in `agentfile_lint/_yaml/`
(MIT, see its LICENSE and PROVENANCE), Python >= 3.11, no network.

- Upstream tag: `{tag}`
- Upstream commit: `{commit}`

## Files

SHA-256 of every file in this directory except this README (same format as `sha256sum`).

{BEGIN}
```
{manifest}
```
{END}

## Run

From the root of the repository to check:

```
python3 {ENTRY_NAME} [--config FILE] [--today YYYY-MM-DD]
```

Check the copy itself with `python3 verify.py` (exit 0 when intact, 1 and the file name otherwise).

## What verification covers

`verify.py` only detects accidental modification. A deliberate change can edit the files and the
manifest above together, so it proves nothing about intent. The real gate is review of the diff
of the pull request that upgrades this copy.

## Upgrades

A maintainer regenerates this directory from a newer upstream tag with the tool's `vendor` command
and opens a pull request. The pull request diff is the review point. The repository keeps no
upgrade script.
"""
    files["README.md"] = readme.encode("utf-8")
    return files


def _check_target(target: Path, force: bool) -> str | None:
    if target.exists() and not target.is_dir():
        return f"{target} exists and is not a directory"
    src = PKG.parent.resolve()
    resolved = target.resolve()
    if resolved == src or resolved in src.parents or resolved == Path(resolved.anchor):
        return f"refusing to write over the source checkout or a parent of it: {target}"
    if target.is_dir() and any(target.iterdir()) and not force:
        return f"{target} is not empty (use --force to replace its contents)"
    return None


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="agentfile-lint vendor", description="Write a self-contained copy of the runner.")
    p.add_argument("--to", required=True, help="target directory (created if missing)")
    p.add_argument("--force", action="store_true", help="replace the contents of a non-empty target")
    p.add_argument("--ref-tag", help="upstream tag to record (default: exact tag of this checkout, else 'untagged')")
    p.add_argument("--ref-commit", help="upstream commit SHA to record (default: HEAD of this checkout)")
    args = p.parse_args(argv)
    target = Path(args.to)
    err = _check_target(target, args.force)
    if err:
        sys.stderr.write(f"agentfile-lint: {err}\n")
        return 2
    tag, commit = _upstream(args.ref_tag, args.ref_commit)
    files = build(tag, commit)
    if target.is_dir():
        for child in target.iterdir():
            shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    for name, content in files.items():
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    print(f"vendored {len(files)} files ({tag}, {commit})")
    return 0
