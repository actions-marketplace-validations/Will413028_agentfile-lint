"""`--format sarif`: one SARIF 2.1.0 log, the version GitHub code scanning reads (docs/adr/0006).

Kept out of `finding.py` because the rule descriptors need `rules`, which imports `finding`.
"""
from __future__ import annotations

from typing import Iterable
from urllib.parse import quote

from . import __version__
from .engine import PSEUDO_RULES
from .finding import Finding, Fix, dump_json
from .rules import DESCRIPTIONS, NAMES, RULES

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/Will413028/agentfile-lint"


def _descriptors() -> list[dict]:
    rules = [{"id": r, "name": NAMES[r], "shortDescription": {"text": DESCRIPTIONS[r]}} for r in RULES]
    rules += [{"id": r, "shortDescription": {"text": text}} for r, text in PSEUDO_RULES.items()]
    return rules


def _uri(path: str) -> str:
    # A relative URI resolves against the checkout root; percent-encode everything but `/`. An
    # absolute path (a config file outside the repository) becomes a file URI.
    return "file://" + quote(path, safe="/") if path.startswith("/") else quote(path, safe="/")


def _fix(fix: Fix) -> dict:
    """SARIF has no applicability; an unsafe fix says so in its description (it starts with the text)."""
    changes: dict[str, list[dict]] = {}
    for e in fix.edits:
        changes.setdefault(e.path, []).append({
            "deletedRegion": {"startLine": e.start[0], "startColumn": e.start[1],
                              "endLine": e.end[0], "endColumn": e.end[1]},
            "insertedContent": {"text": e.text},
        })
    return {
        "description": {"text": fix.description},
        "artifactChanges": [
            {"artifactLocation": {"uri": _uri(path)}, "replacements": replacements}
            for path, replacements in changes.items()
        ],
    }


def _result(f: Finding) -> dict:
    location: dict = {"artifactLocation": {"uri": _uri(f.path)}}
    if f.line:  # a whole-file finding has no region
        location["region"] = {"startLine": f.line}
    result = {
        "ruleId": f.rule,
        "level": f.severity,  # `error` or `warning`, both SARIF levels
        "message": {"text": f.message},
        "locations": [{"physicalLocation": location}],
    }
    if f.fix is not None:
        result["fixes"] = [_fix(f.fix)]
    return result


def render(findings: Iterable[Finding]) -> str:
    log = {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "agentfile-lint",
                "version": __version__,
                "informationUri": INFORMATION_URI,
                "rules": _descriptors(),
            }},
            "results": [_result(f) for f in findings],
            "columnKind": "unicodeCodePoints",  # fix regions count columns as `finding.Edit` does
        }],
    }
    return dump_json(log)
