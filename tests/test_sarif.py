"""`--format sarif` (docs/design.md, Output and exit codes; docs/adr/0006).

The log is checked against the official SARIF 2.1.0 schema (`fixtures/sarif-2.1.0.json`, from
oasis-tcs/sarif-spec) with a small standard-library validator: `$ref`, `type`, `required`,
`properties`, `additionalProperties: false`, `items`, `enum`, `minimum`, `anyOf` and `oneOf`, the
keywords that decide whether a field is present and has the right type.
"""
from __future__ import annotations

import json
import unittest

import helpers
from test_output import FILES, R5_MESSAGE, run

SCHEMA = json.loads((helpers.FIXTURES / "sarif-2.1.0.json").read_text(encoding="utf-8"))
TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}


def problems(value, schema: dict, where: str = "$") -> list[str]:
    if "$ref" in schema:
        schema = SCHEMA["definitions"][schema["$ref"].rsplit("/", 1)[1]]
    out: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        names = expected if isinstance(expected, list) else [expected]
        ok = any(isinstance(value, TYPES[n]) and not (n in ("integer", "number") and isinstance(value, bool)) for n in names)
        if not ok:
            return [f"{where}: expected {expected}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{where}: {value!r} not in {schema['enum']}")
    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        out.append(f"{where}: {value} below {schema['minimum']}")
    for key in ("anyOf", "oneOf"):
        if key in schema:
            passing = [s for s in schema[key] if not problems(value, s, where)]
            if not passing or (key == "oneOf" and len(passing) > 1):
                out.append(f"{where}: does not match {key}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        out += [f"{where}: missing {k}" for k in schema.get("required", []) if k not in value]
        for k, v in value.items():
            if k in props:
                out += problems(v, props[k], f"{where}.{k}")
            elif schema.get("additionalProperties") is False:
                out.append(f"{where}: unexpected {k}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            out += problems(item, schema["items"], f"{where}[{i}]")
    return out


class ValidatorTest(unittest.TestCase):
    """The validator itself must reject what it is meant to catch, or the schema test proves nothing."""

    def test_rejects_a_result_without_message(self):
        log = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "x"}}, "results": [{"ruleId": "R1"}]}]}
        self.assertTrue(any("missing message" in p for p in problems(log, SCHEMA)))

    def test_rejects_a_string_start_line(self):
        loc = {"physicalLocation": {"artifactLocation": {"uri": "a"}, "region": {"startLine": "1"}}}
        log = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "x"}},
                                             "results": [{"message": {"text": "m"}, "locations": [loc]}]}]}
        self.assertTrue(problems(log, SCHEMA))


class SarifFormatTest(unittest.TestCase):
    def setUp(self):
        self.r = run(FILES, "--format", "sarif")
        self.log = json.loads(self.r.stdout)

    def test_exit_code_and_stderr_as_other_formats(self):
        self.assertEqual((self.r.returncode, self.r.stderr), (1, ""))

    def test_valid_against_the_2_1_0_schema(self):
        self.assertEqual(self.log["version"], "2.1.0")
        self.assertEqual(problems(self.log, SCHEMA), [])

    def test_results_carry_rule_level_message_and_location(self):
        results = self.log["runs"][0]["results"]
        self.assertEqual(results, [
            {"ruleId": "R1b", "level": "warning", "message": {"text": "file is 2 lines, limit 1"},
             "locations": [{"physicalLocation": {"artifactLocation": {"uri": "AGENTS.md"}}}]},
            {"ruleId": "R1d", "level": "error", "message": {"text": "line is 600 characters, limit 500"},
             "locations": [{"physicalLocation": {"artifactLocation": {"uri": "AGENTS.md"}, "region": {"startLine": 2}}}]},
            {"ruleId": "R5a", "level": "warning", "message": {"text": R5_MESSAGE},
             "locations": [{"physicalLocation": {"artifactLocation": {"uri": "a%2Cb/AGENTS.md"}, "region": {"startLine": 1}}}]},
        ])

    def test_every_rule_id_in_results_has_a_descriptor(self):
        driver = self.log["runs"][0]["tool"]["driver"]
        self.assertEqual(driver["name"], "agentfile-lint")
        ids = {d["id"] for d in driver["rules"]}
        self.assertLessEqual({res["ruleId"] for res in self.log["runs"][0]["results"]}, ids)
        from agentfile_lint import allowlist, disable
        from agentfile_lint.finding import INPUT_RULE
        self.assertLessEqual({allowlist.RULE_ID, disable.RULE_ID, INPUT_RULE}, ids)

    def test_no_findings_is_still_a_valid_log(self):
        r = run({"AGENTS.md": "# ok\n"}, "--format", "sarif")
        log = json.loads(r.stdout)
        self.assertEqual((r.returncode, log["runs"][0]["results"]), (0, []))
        self.assertEqual(problems(log, SCHEMA), [])

    def test_fixes_are_valid_against_the_schema(self):
        directive = "<!-- agentfile-lint-disable-next-line R5a, R1d -- copied -->\n"
        dup = "Run make check before every push to the remote.\n"
        files = {"AGENTS.md": dup, "sub/AGENTS.md": directive + dup + "# T\n" + directive.replace("R5a, ", "") + "ok\n"}
        log = json.loads(run(files, "--format", "sarif").stdout)
        self.assertEqual(sum(len(r.get("fixes", [])) for r in log["runs"][0]["results"]), 2)
        self.assertEqual(problems(log, SCHEMA), [])

    def test_validator_rejects_a_fix_without_artifact_changes(self):
        log = json.loads(run({"AGENTS.md": "<!-- agentfile-lint-disable-next-line R1d -- x -->\nok\n"},
                             "--format", "sarif").stdout)
        (result,) = log["runs"][0]["results"]
        del result["fixes"][0]["artifactChanges"]
        self.assertTrue(any("missing artifactChanges" in p for p in problems(log, SCHEMA)))


if __name__ == "__main__":
    unittest.main()
