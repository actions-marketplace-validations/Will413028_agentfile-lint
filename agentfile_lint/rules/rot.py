"""R4a and R4b: text that rots (docs/adr/0005). Dates and issue numbers are state, not rules (R4a);
narrative words date a sentence (R4b).

File names that carry a date (a decision record, a plan) are not dates: an R4a match inside a token that
matches `ignore_token_patterns` (by default a token with `/`, a file extension or a date-prefixed slug)
is skipped.
"""
from __future__ import annotations

import re
from typing import Any

from ..errors import check_keys, expect_regex_list, expect_str_items, require_keys
from ..finding import Finding
from ._text import prose_lines

CHECKS = (
    ("R4a", "dated-refs", "dates and issue numbers"),
    ("R4b", "narrative-words", "narrative words that describe history instead of the current rule"),
)
_KEYS = {
    "R4a": {"date_patterns", "issue_patterns", "ignore_token_patterns"},
    "R4b": {"narrative_words"},
}
_REMOVED = {"narrative_level": "removed in 0.7.0; narrative words are R4b, with its own level (docs/adr/0005)"}


def validate(shared: None, tables: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    for rule_id, keys in _KEYS.items():
        where = f"rules.{rule_id}"
        moved = {k: f"belongs to {other} in 0.7.0 (docs/adr/0005)" for other, ks in _KEYS.items() if other != rule_id for k in ks}
        check_keys(tables[rule_id], keys | {"level"}, where, {**_REMOVED, **moved})
        require_keys(tables[rule_id], sorted(keys), where)
    a, b = tables["R4a"], tables["R4b"]
    params = {
        "date_patterns": expect_regex_list(a["date_patterns"], "rules.R4a.date_patterns"),
        "issue_patterns": expect_regex_list(a["issue_patterns"], "rules.R4a.issue_patterns"),
        "ignore_token_patterns": expect_regex_list(a["ignore_token_patterns"], "rules.R4a.ignore_token_patterns"),
        "narrative_words": expect_str_items(b["narrative_words"], "rules.R4b.narrative_words"),
    }
    effective = {rule_id: {key: params[key] for key in sorted(keys)} for rule_id, keys in _KEYS.items()}
    return params, effective


def _word(word: str) -> re.Pattern[str]:
    if word.isascii():
        return re.compile(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])", re.IGNORECASE)
    return re.compile(re.escape(word))


def _token(line: str, start: int, end: int) -> str:
    """The whitespace/backtick-delimited token around a match."""
    left = max(line.rfind(c, 0, start) for c in " \t`") + 1
    cuts = [i for i in (line.find(c, end) for c in " \t`") if i >= 0]
    return line[left:min(cuts) if cuts else len(line)]


def check(path: str, text: str, params: dict[str, Any], levels: dict[str, str]) -> list[Finding]:
    found: list[Finding] = []
    dates = [re.compile(p) for p in params["date_patterns"]] if levels["R4a"] != "off" else []
    issues = [re.compile(p) for p in params["issue_patterns"]] if levels["R4a"] != "off" else []
    ignore = [re.compile(p) for p in params["ignore_token_patterns"]]
    words = [(w, _word(w)) for w in params["narrative_words"]] if levels["R4b"] != "off" else []
    for number, line in prose_lines(text):
        for kind, patterns in (("date", dates), ("issue reference", issues)):
            for pattern in patterns:
                for m in pattern.finditer(line):
                    token = _token(line, m.start(), m.end())
                    if any(i.search(token) for i in ignore):
                        continue
                    found.append(Finding(path, number, "R4a", f"{kind} {m.group(0)!r} goes stale; state the rule, not the moment"))
        for word, pattern in words:
            if pattern.search(line):
                found.append(Finding(path, number, "R4b", f"narrative word {word!r}; describe the current rule, not its history"))
    return list(dict.fromkeys(found))
