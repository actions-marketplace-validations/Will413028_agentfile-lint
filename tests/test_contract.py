"""Contract: R1a to R1d against the legacy checker snapshot, with a list of deliberate differences.

Both tools run on the same synthetic git repos. Their outputs are normalised to sets of
(path, line or 0, kind size|line, measured, limit) and compared, together with exit codes.
Outside DIFFERENCES the sets must be equal; normalisation is deliberately dumb, so a mismatch means
one of the two tools is wrong. Each DIFFERENCES row pins both tools' exact sets and says why the new
one deliberately differs (docs/adr/0004: single-file bytes are the raw bytes on disk). The legacy
checker prints to stderr; the new one prints every finding to stdout as
`file:line: severity: rule-id: message` (`file: severity: ...` for a whole-file finding).
"""
from __future__ import annotations

import re
import unittest

import helpers

ROOT, SUB, NESTED, LINE = 12_000, 10_000, 6_000, 500
BLOCK_BEGIN = "<!-- BEGIN:nextjs-agent-rules -->"
BLOCK_END = "<!-- END:nextjs-agent-rules -->"

LEGACY_LINE = re.compile(r"^([^:]+)(?::(\d+))?: (.*)$")
LEGACY_SIZE = re.compile(r"^(\d+) bytes，上限 (\d+)$")
LEGACY_LONG = re.compile(r"^一行 (\d+) 字元，上限 (\d+)$")
NEW_LINE = re.compile(r"^([^:]+)(?::(\d+))?: (error|warning): ([A-Za-z0-9-]+): (.*)$")
NEW_SIZE = re.compile(r"^file is (\d+) bytes, limit (\d+)$")
NEW_LONG = re.compile(r"^line is (\d+) characters, limit (\d+)$")


def exact(n: int, filler: str = "x") -> str:
    """Text of exactly n bytes made of short lines (filler must be 1 byte)."""
    lines, left = [], n
    while left > 0:
        take = min(80, left)
        lines.append(filler * (take - 1) + "\n" if take > 1 else "\n")
        left -= take
    return "".join(lines)


def normalise_legacy(stderr: str) -> set[tuple]:
    out = set()
    for raw in stderr.splitlines():
        m = LEGACY_LINE.match(raw)
        assert m, f"unparsable legacy line: {raw!r}"
        path, line, msg = m.group(1), int(m.group(2) or 0), m.group(3)
        if s := LEGACY_SIZE.match(msg):
            out.add((path, line, "size", int(s.group(1)), int(s.group(2))))
        elif s := LEGACY_LONG.match(msg):
            out.add((path, line, "line", int(s.group(1)), int(s.group(2))))
        else:
            raise AssertionError(f"unknown legacy message: {raw!r}")
    return out


def normalise_new(stdout: str) -> set[tuple]:
    """R1a to R1d errors only: the legacy checker had no other rule, and the shared stdout also carries
    the R5a warnings the tier files trigger (the legacy comparison read errors from stderr before 0.6.0)."""
    out = set()
    for raw in stdout.splitlines():
        m = NEW_LINE.match(raw)
        assert m, f"unparsable new line: {raw!r}"
        path, line, severity, rule, msg = m.group(1), int(m.group(2) or 0), m.group(3), m.group(4), m.group(5)
        if rule not in ("R1a", "R1b", "R1c", "R1d"):
            continue
        assert severity == "error", f"R1a to R1d are at error in the fixture: {raw!r}"
        if s := NEW_SIZE.match(msg):
            out.add((path, line, "size", int(s.group(1)), int(s.group(2))))
        elif s := NEW_LONG.match(msg):
            out.add((path, line, "line", int(s.group(1)), int(s.group(2))))
        else:
            raise AssertionError(f"unknown new message: {raw!r}")
    return out


def tier_files(delta: int) -> dict[str, str]:
    return {
        "AGENTS.md": exact(ROOT + delta),
        "sub/AGENTS.md": exact(SUB + delta),
        "sub/deep/AGENTS.md": exact(NESTED + delta),
        "a/b/c/AGENTS.md": exact(NESTED + delta),
    }


def block(body: str) -> str:
    return f"{BLOCK_BEGIN}\n{body}\n{BLOCK_END}\n"


SCENARIOS = {
    # name: (files, expected number of violations; guards against comparing two empty sets)
    "size equals limit": (tier_files(0), 0),
    "size limit minus 1": (tier_files(-1), 0),
    "size limit plus 1": (tier_files(1), 4),
    "line 500 chars": ({"AGENTS.md": "a" * 500 + "\n", "sub/AGENTS.md": "b" * 500}, 0),
    "line 501 chars": ({"AGENTS.md": "a" * 501 + "\n", "sub/AGENTS.md": "ok\n" + "b" * 501}, 2),
    "multibyte line within char limit": ({"AGENTS.md": "中" * 500 + "\n", "sub/AGENTS.md": "é" * 500}, 0),
    "multibyte line over char limit": ({"AGENTS.md": "中" * 501 + "\n"}, 1),
    "multibyte size: bytes differ from chars": (
        # 1995 CJK chars (3 bytes each) + 10 ASCII bytes = exactly 6000 bytes (nested limit),
        # 2005 chars only; adding one more CJK char gives 6003 bytes (over).
        {"x/y/AGENTS.md": ("中" * 399 + "\n") * 5 + "x" * 9 + "\n",
         "x/z/AGENTS.md": ("中" * 399 + "\n") * 5 + "x" * 9 + "\n" + "中"},
        1,
    ),
    "oversized inside block ignored": (
        {"AGENTS.md": "head\n" + block("x" * 400 + "\n" + ("y" * 90 + "\n") * 200) + "tail\n",
         "sub/AGENTS.md": "head\n" + block("z" * 900) + "tail\n"},
        0,
    ),
    "oversized outside block counted": (
        {"AGENTS.md": block("small") + exact(ROOT + 1),
         "sub/AGENTS.md": "q" * 501 + "\n" + block("small")},
        2,
    ),
    "size counted after block removal": (
        {"AGENTS.md": exact(ROOT - 10) + block("k" * 5000)},
        0,
    ),
    "crlf line endings": ({"AGENTS.md": b"a\r\n" + b"b" * 501 + b"\r\n"}, 1),
    "non-agents files ignored": ({"README.md": "x" * 20_000, "NOTES.local.md": "x" * 20_000}, 0),
}


CRLF_OVER = b"x" * 78 + b"\r\n"  # 80 bytes on disk, 79 after text-mode translation

DIFFERENCES = {
    # name: (files, legacy set, new set, reason)
    "crlf counted as two bytes": (
        # 151 lines: 11,929 bytes in text mode (under 12,000), 12,080 on disk (over).
        {"AGENTS.md": CRLF_OVER * 151},
        set(),
        {("AGENTS.md", 0, "size", 80 * 151, ROOT)},
        "single-file bytes are the bytes on disk; each CRLF line adds one byte over text mode (151 lines)",
    ),
    "line numbers are the lines on disk after a block": (
        {"sub/AGENTS.md": "one\n" + block("a\nb\nc") + "three\n" + "w" * 501 + "\n"},
        {("sub/AGENTS.md", 3, "line", 501, LINE)},
        {("sub/AGENTS.md", 8, "line", 501, LINE)},
        "a finding's line is where an annotation points; the block's 5 lines are no longer subtracted",
    ),
}


class ContractTest(unittest.TestCase):
    def test_scenarios(self):
        for name, (files, expected) in SCENARIOS.items():
            with self.subTest(name):
                root = helpers.make_repo(files)
                old = helpers.run_legacy(root)
                new = helpers.run_new(root, "--config", str(helpers.HAWKR_LIMITS))
                old_set, new_set = normalise_legacy(old.stderr), normalise_new(new.stdout)
                self.assertEqual(len(old_set), expected, f"legacy found unexpected count\n{old.stderr}")
                self.assertEqual(new.stderr, "", "findings go to stdout only")
                self.assertEqual(old_set, new_set, f"\nlegacy:\n{old.stderr}\nnew:\n{new.stdout}")
                self.assertEqual(old.returncode, new.returncode)
                self.assertEqual(new.returncode, 1 if expected else 0)

    def test_deliberate_differences(self):
        for name, (files, legacy, expected, _reason) in DIFFERENCES.items():
            with self.subTest(name):
                root = helpers.make_repo(files)
                old = helpers.run_legacy(root)
                new = helpers.run_new(root, "--config", str(helpers.HAWKR_LIMITS))
                old_set, new_set = normalise_legacy(old.stderr), normalise_new(new.stdout)
                self.assertEqual(old_set, legacy, f"legacy changed\n{old.stderr}")
                self.assertEqual(new_set, expected, f"\nnew:\n{new.stdout}")
                self.assertNotEqual(old_set, new_set, "not a difference any more: move it to SCENARIOS")


if __name__ == "__main__":
    unittest.main()
