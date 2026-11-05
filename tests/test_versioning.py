"""Version process: no shipped preset sets a rule above warn unless the CHANGELOG lists it as graduated."""
import re
import tomllib
import unittest

import helpers
from agentfile_lint.rules import RETIRED

CHANGELOG = (helpers.REPO / "CHANGELOG.md").read_text(encoding="utf-8")
PRESETS_DIR = helpers.REPO / "agentfile_lint" / "presets"
PRESET = tomllib.loads((PRESETS_DIR / "default.toml").read_text(encoding="utf-8"))
ALL_PRESETS = {p.name: tomllib.loads(p.read_text(encoding="utf-8")) for p in sorted(PRESETS_DIR.glob("*.toml"))}


def graduated(text):
    """Rule ids named as bullets under any `### Graduated` heading, e.g. "- `R1`: reason"."""
    ids, inside = set(), False
    for line in text.splitlines():
        if line.startswith("#"):
            inside = line.strip() == "### Graduated"
        elif inside:
            m = re.match(r"- `([A-Za-z0-9]+)`", line)
            if m:
                ids.add(m.group(1))
    return ids


class VersioningTest(unittest.TestCase):
    def test_rules_not_graduated_stay_at_or_below_warn(self):
        # `off` is allowed: lowering a rule never needs a Graduated entry (docs/versioning.md).
        grad = graduated(CHANGELOG)
        self.assertIn("strict.toml", ALL_PRESETS)
        for name, preset in ALL_PRESETS.items():
            for rule_id, params in preset.get("rules", {}).items():
                if rule_id not in grad and "level" in params:
                    self.assertIn(params["level"], ("warn", "off"), f"{name}: {rule_id} is not listed under Graduated in CHANGELOG.md")

    def test_the_level_check_is_not_vacuous(self):
        self.assertEqual(PRESET["rules"]["R2"]["level"], "warn")  # at least one non-graduated rule is checked

    def test_graduated_rules_exist_in_the_preset(self):
        # A retired id (R1, split in 0.7.0) stays in the released sections; its successors are listed.
        self.assertTrue(graduated(CHANGELOG) - set(RETIRED) <= set(PRESET["rules"]))

    def test_the_lint_itself_detects_a_violation(self):
        text = "## [1.0.0]\n\n### Graduated\n\n- `R1`: shipped at error\n\n### Added\n\n- `R2` something\n"
        self.assertEqual(graduated(text), {"R1"})

    def test_version_strings_and_changelog_agree(self):
        version_line = (helpers.REPO / "agentfile_lint" / "__init__.py").read_text(encoding="utf-8")
        __version__ = re.search(r'__version__ = "([^"]+)"', version_line).group(1)
        pyproject = tomllib.loads((helpers.REPO / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["project"]["version"], __version__)
        released = re.findall(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", CHANGELOG, re.MULTILINE)
        self.assertEqual(released[0], __version__, "newest CHANGELOG section must be the current version")


if __name__ == "__main__":
    unittest.main()
