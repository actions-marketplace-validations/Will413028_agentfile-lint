"""What cross-file rules may look at: the full tracked file set, never just the command-line files."""
from __future__ import annotations

from pathlib import Path, PurePosixPath


def normalize_newlines(raw: str) -> str:
    """CRLF and lone CR become LF, as Python's text mode reads a file."""
    return raw.replace("\r\n", "\n").replace("\r", "\n")


class Context:
    def __init__(self, root: Path, tracked: list[str], raw: dict[str, str]):
        self.root = root
        self.tracked = tracked          # every `git ls-files` entry, or every walked file with `--no-git`
        # Analyzed instruction files (valid UTF-8), read once by the engine: path -> text as stored on
        # disk (`raw`, for byte, line and line-length limits) and with newlines normalized (`files`).
        self.raw = raw
        self.files = {path: normalize_newlines(text) for path, text in raw.items()}
        self.tracked_set = set(tracked)
        self.dirs = {""}                # every directory that holds a tracked file ("" is the root)
        for path in tracked:
            for parent in PurePosixPath(path).parents:
                self.dirs.add("" if str(parent) == "." else str(parent))
        self._cache: dict[str, str | None] = {}

    def read(self, path: str) -> str | None:
        """Text of a tracked file, or None when it is missing or not valid UTF-8."""
        if path not in self._cache:
            try:
                self._cache[path] = (self.root / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                self._cache[path] = None
        return self._cache[path]
