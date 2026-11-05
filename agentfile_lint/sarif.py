"""`--format sarif`: one SARIF 2.1.0 log, the version GitHub code scanning reads (docs/adr/0006).

Kept out of `finding.py` because the rule descriptors need `rules`, which imports `finding`.
"""
from __future__ import annotations

from typing import Iterable
from urllib.parse import quote

from . import __version__
from .engine import PSEUDO_RULES
from .finding import Finding, dump_json
from .rules import DESCRIPTIONS, NAMES, RULES

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/Will413028/agentfile-lint"


def _descriptors() -> list[dict]:
    rules = [{"id": r, "name": NAMES[r], "shortDescription": {"text": DESCRIPTIONS[r]}} for r in RULES]
    rules += [{"id": r, "shortDescription": {"text": text}} for r, text in PSEUDO_RULES.items()]
    return rules


def _result(f: Finding) -> dict:
    # A relative URI resolves against the checkout root; percent-encode everything but `/`.
    location: dict = {"artifactLocation": {"uri": quote(f.path, safe="/")}}
    if f.line:  # a whole-file finding has no region
        location["region"] = {"startLine": f.line}
    return {
        "ruleId": f.rule,
        "level": f.severity,  # `error` or `warning`, both SARIF levels
        "message": {"text": f.message},
        "locations": [{"physicalLocation": location}],
    }


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
        }],
    }
    return dump_json(log)
