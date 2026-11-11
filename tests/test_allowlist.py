import datetime
import unittest

import helpers
from agentfile_lint import allowlist, config
from agentfile_lint.errors import ConfigError

TODAY = "2026-06-01"
BIG = "x" * 600 + "\n"  # one line over the 500-char limit (R1_LINE) -> an R1d finding on line 1
R1_LINE = "[rules.R1d]\nlevel = \"error\"\nmax_chars = 500\n"  # the default checks no line length


def entry(path="AGENTS.md", expires="2026-06-30", rule="R1d", reason="cleanup tracked elsewhere", count=1):
    c = "" if count is None else f"count = {count}\n"
    return f'[[allowlist.entries]]\nrule = "{rule}"\npath = "{path}"\n{c}reason = "{reason}"\nexpires = {expires}\n'


def run(files, toml, *extra):
    root = helpers.make_repo({**files, ".agentfile-lint.toml": R1_LINE + toml})
    return helpers.run_new(root, "--today", TODAY, *extra)


class AllowlistTest(unittest.TestCase):
    def test_one_more_finding_than_count_reports_all_and_an_error(self):
        r = run({"AGENTS.md": BIG + BIG}, entry(expires="2026-08-01", count=1))
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGENTS.md:1: error: R1d:", r.stdout)
        self.assertIn("AGENTS.md:2: error: R1d:", r.stdout)
        self.assertIn("AGENTS.md: error: allowlist: entry for R1d has count 1 but the file has 2 findings", r.stdout)

    def test_new_duplicate_line_is_not_hidden_by_r5a_entry(self):
        dup = "Run make check before every push to the remote.\n"
        other = "Keep the release notes short and in the past tense.\n"
        files = {"AGENTS.md": dup + other, "sub/AGENTS.md": dup + other}
        toml = entry(rule="R5a", path="sub/AGENTS.md", expires="2026-08-01", count=1)
        r = run(files, toml)
        # R5a is a warning, so the entry's own note is one too.
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("sub/AGENTS.md:1: warning: R5a:", r.stdout)
        self.assertIn("sub/AGENTS.md:2: warning: R5a:", r.stdout)
        self.assertIn("sub/AGENTS.md: warning: allowlist: entry for R5a has count 1 but the file has 2 findings", r.stdout)

    def test_fewer_findings_than_count_suppresses_and_asks_to_lower(self):
        r = run({"AGENTS.md": BIG}, entry(expires="2026-08-01", count=3))
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("R1d: line is", r.stdout)
        self.assertIn("AGENTS.md: error: allowlist: entry for R1d has count 3 but the file has 1 finding; lower count to 1", r.stdout)

    def test_count_is_required(self):
        r = run({"AGENTS.md": BIG}, entry(expires="2026-08-01", count=None))
        self.assertEqual(r.returncode, 2)
        self.assertIn("missing key count", r.stderr)

    def test_count_must_be_at_least_one(self):
        for bad in ("0", "-1", "true", '"2"', "1.5"):
            with self.subTest(bad=bad):
                r = run({"AGENTS.md": BIG}, entry(expires="2026-08-01", count=bad))
                self.assertEqual(r.returncode, 2)
                self.assertIn("count: expected an integer >= 1", r.stderr)

    def test_live_entry_suppresses_violation(self):
        r = run({"AGENTS.md": BIG}, entry(expires="2026-08-01"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")

    def test_expired_entry_fails_and_does_not_suppress(self):
        r = run({"AGENTS.md": BIG}, entry(expires="2026-05-31"))  # yesterday
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGENTS.md: error: allowlist: entry for R1d expired on 2026-05-31", r.stdout)
        self.assertIn("AGENTS.md:1: error: R1d: line is 600 characters, limit 500", r.stdout)

    def test_entry_expiring_today_is_still_live(self):
        r = run({"AGENTS.md": BIG}, entry(expires="2026-06-01"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("expires in 0 days", r.stdout)

    def test_unneeded_entry_fails_when_file_is_clean(self):
        r = run({"AGENTS.md": "fine\n"}, entry(expires="2026-08-01"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGENTS.md: error: allowlist: entry for R1d is no longer needed", r.stdout)

    def test_unneeded_entry_fails_when_file_is_missing(self):
        r = run({"AGENTS.md": "fine\n"}, entry(path="gone/AGENTS.md", expires="2026-08-01"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("gone/AGENTS.md: error: allowlist: entry for R1d is no longer needed", r.stdout)

    def test_expiry_beyond_max_days_is_a_config_failure(self):
        r = run({"AGENTS.md": BIG}, entry(expires="2026-09-30"))  # 121 days
        self.assertEqual(r.returncode, 2)
        self.assertIn("more than 90 days", r.stderr)

    def test_max_days_is_configurable(self):
        toml = "[allowlist]\nmax_days = 200\n" + entry(expires="2026-09-30")
        r = run({"AGENTS.md": BIG}, toml)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_more_than_ten_entries_is_a_config_failure(self):
        toml = "".join(entry(path=f"d{i}/AGENTS.md", expires="2026-08-01") for i in range(11))
        r = run({"AGENTS.md": "fine\n"}, toml)
        self.assertEqual(r.returncode, 2)
        self.assertIn("11 entries exceed the limit of 10", r.stderr)

    def test_ten_entries_are_accepted_by_the_config(self):
        toml = "".join(entry(path=f"d{i}/AGENTS.md", expires="2026-08-01") for i in range(10))
        r = run({"AGENTS.md": "fine\n"}, toml)
        self.assertEqual(r.returncode, 1)  # unneeded entries, but the config itself loaded
        self.assertNotIn("exceed the limit", r.stderr)

    def test_warns_within_14_days_of_expiry(self):
        r = run({"AGENTS.md": BIG}, entry(expires="2026-06-15"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("AGENTS.md: warning: allowlist: entry for R1d expires in 14 days", r.stdout)

    def test_no_warning_at_15_days(self):
        r = run({"AGENTS.md": BIG}, entry(expires="2026-06-16"))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")

    def test_warn_as_error_promotes_the_expiry_warning(self):
        r = run({"AGENTS.md": BIG}, entry(expires="2026-06-15"), "--warn-as-error")
        self.assertEqual(r.returncode, 1)

    def test_missing_reason_is_a_config_failure(self):
        toml = '[[allowlist.entries]]\nrule = "R1d"\npath = "AGENTS.md"\ncount = 1\nexpires = 2026-06-30\n'
        r = run({"AGENTS.md": BIG}, toml)
        self.assertEqual(r.returncode, 2)
        self.assertIn("missing key reason", r.stderr)

    def test_unknown_rule_in_entry_is_a_config_failure(self):
        r = run({"AGENTS.md": BIG}, entry(rule="R99"))
        self.assertEqual(r.returncode, 2)

    def test_apply_unit(self):
        s = allowlist.Settings(90, 10, 14)
        today = datetime.date(2026, 6, 1)
        e = allowlist.Entry("R1d", "a/AGENTS.md", 1, "why", datetime.date(2026, 5, 31))
        out = allowlist.apply([], [e], s, {"a/AGENTS.md"}, today, level_of=lambda rule, path: "error")
        self.assertEqual([f.rule for f in out], ["allowlist"])


WARN_LINE = "[rules.R1d]\nlevel = \"warn\"\nmax_chars = 500\n"
OFF_LINE = "[rules.R1d]\nlevel = \"off\"\nmax_chars = 500\n"


def override(level, raise_=False):
    extra = "raise = true\n" if raise_ else ""
    return f'[[overrides]]\npaths = ["AGENTS.md"]\nrules = {{ R1d = "{level}" }}\nreason = "scope"\n{extra}'


def run_with(rule_line, files, toml, *extra):
    root = helpers.make_repo({**files, ".agentfile-lint.toml": rule_line + toml})
    return helpers.run_new(root, "--today", TODAY, *extra)


class EntryLevelTest(unittest.TestCase):
    """An entry's own notes have the level of its rule on its path: an entry is never stricter than
    the rule it excepts."""

    def test_more_than_count_on_a_warn_rule_is_a_warning(self):
        r = run_with(WARN_LINE, {"AGENTS.md": BIG + BIG}, entry(expires="2026-08-01", count=1))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("AGENTS.md:1: warning: R1d:", r.stdout)
        self.assertIn("AGENTS.md:2: warning: R1d:", r.stdout)
        self.assertIn("AGENTS.md: warning: allowlist: entry for R1d has count 1 but the file has 2 findings", r.stdout)

    def test_fewer_than_count_on_a_warn_rule_is_a_warning(self):
        r = run_with(WARN_LINE, {"AGENTS.md": BIG}, entry(expires="2026-08-01", count=3))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("R1d: line is", r.stdout)
        self.assertIn("AGENTS.md: warning: allowlist: entry for R1d has count 3 but the file has 1 finding; lower count to 1", r.stdout)

    def test_unneeded_entry_on_a_warn_rule_is_a_warning(self):
        r = run_with(WARN_LINE, {"AGENTS.md": "fine\n"}, entry(expires="2026-08-01"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("AGENTS.md: warning: allowlist: entry for R1d is no longer needed", r.stdout)

    def test_expired_entry_on_a_warn_rule_is_a_warning_and_does_not_suppress(self):
        r = run_with(WARN_LINE, {"AGENTS.md": BIG}, entry(expires="2026-05-31"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("AGENTS.md: warning: allowlist: entry for R1d expired on 2026-05-31", r.stdout)
        self.assertIn("AGENTS.md:1: warning: R1d: line is 600 characters, limit 500", r.stdout)

    def test_warn_as_error_promotes_the_entry_notes_of_a_warn_rule(self):
        r = run_with(WARN_LINE, {"AGENTS.md": BIG + BIG}, entry(expires="2026-08-01", count=1), "--warn-as-error")
        self.assertEqual(r.returncode, 1)
        self.assertIn("AGENTS.md: error: allowlist: entry for R1d has count 1", r.stdout)

    def test_entry_for_a_rule_that_is_off_is_an_unneeded_warning(self):
        r = run_with(OFF_LINE, {"AGENTS.md": BIG}, entry(expires="2026-08-01"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("AGENTS.md: warning: allowlist: entry for R1d is no longer needed", r.stdout)

    def test_override_that_lowers_the_rule_on_the_path_lowers_the_notes(self):
        for files, count, expect in (
            ({"AGENTS.md": BIG + BIG}, 1, "has count 1 but the file has 2 findings"),
            ({"AGENTS.md": "fine\n"}, 1, "is no longer needed"),
        ):
            with self.subTest(expect=expect):
                r = run_with(R1_LINE, files, entry(expires="2026-08-01", count=count) + override("warn"))
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn(f"AGENTS.md: warning: allowlist: entry for R1d {expect}", r.stdout)

    def test_override_that_raises_the_rule_on_the_path_raises_the_notes(self):
        for files, count, expect in (
            ({"AGENTS.md": BIG + BIG}, 1, "has count 1 but the file has 2 findings"),
            ({"AGENTS.md": "fine\n"}, 1, "is no longer needed"),
        ):
            with self.subTest(expect=expect):
                r = run_with(WARN_LINE, files, entry(expires="2026-08-01", count=count) + override("error", True))
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn(f"AGENTS.md: error: allowlist: entry for R1d {expect}", r.stdout)

    def test_entry_for_a_file_that_is_not_utf8_keeps_error_notes(self):
        root = helpers.make_repo({"AGENTS.md": "fine\n", ".agentfile-lint.toml": entry(rule="E0", expires="2026-08-01", count=2)})
        (root / "AGENTS.md").write_bytes(b"\xff\xfe bad\n")
        r = helpers.run_new(root, "--today", TODAY)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("AGENTS.md: error: allowlist: entry for E0 has count 2 but the file has 1 finding", r.stdout)

    def test_expired_entry_without_findings_on_a_warn_rule_is_a_warning(self):
        r = run_with(WARN_LINE, {"AGENTS.md": "fine\n"}, entry(expires="2026-05-31"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("AGENTS.md: warning: allowlist: entry for R1d expired on 2026-05-31", r.stdout)

    def test_unneeded_entry_for_a_missing_file_keeps_the_rule_level(self):
        for line, rc, severity in ((R1_LINE, 1, "error"), (WARN_LINE, 0, "warning")):
            with self.subTest(severity=severity):
                r = run_with(line, {"AGENTS.md": "fine\n"}, entry(path="gone/AGENTS.md", expires="2026-08-01"))
                self.assertEqual(r.returncode, rc, r.stdout + r.stderr)
                self.assertIn(f"gone/AGENTS.md: {severity}: allowlist: entry for R1d is no longer needed", r.stdout)

    def test_entry_for_a_rule_whose_findings_are_always_warnings_warns_at_error_level(self):
        # R6 at `error` still only warns, so its entry's notes do too, with findings or without.
        r6 = '[rules.R6]\nlevel = "error"\n'
        for text in ("Retry at most MAX_RETRIES = 5 times.\nWait TIMEOUT_SECONDS = 30 between tries.\n", "fine\n"):
            with self.subTest(text=text):
                r = run_with(r6, {"AGENTS.md": text}, entry(rule="R6", expires="2026-08-01", count=1))
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("AGENTS.md: warning: allowlist: entry for R6", r.stdout)
                self.assertNotIn("error:", r.stdout)

    def test_fix_lowers_the_count_of_a_warn_rule_entry(self):
        root = helpers.make_repo({"AGENTS.md": BIG, ".agentfile-lint.toml": WARN_LINE + entry(expires="2026-08-01", count=3)})
        r = helpers.run_new(root, "--today", TODAY, "--fix")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("count = 1\n", (root / ".agentfile-lint.toml").read_text())

    def test_apply_unit_takes_the_level_from_level_of(self):
        s = allowlist.Settings(90, 10, 14)
        today = datetime.date(2026, 6, 1)
        e = allowlist.Entry("R1d", "AGENTS.md", 1, "why", datetime.date(2026, 8, 1))
        for given, expect in (("error", "error"), ("warn", "warn"), ("off", "warn")):
            out = allowlist.apply([], [e], s, {"AGENTS.md"}, today, level_of=lambda rule, path: given)
            self.assertEqual([f.level for f in out], [expect])


class ApplyCountTest(unittest.TestCase):
    S = allowlist.Settings(90, 10, 14)
    TODAY = datetime.date(2026, 6, 1)

    def apply(self, n, count, expires):
        e = allowlist.Entry("R1d", "a/AGENTS.md", count, "why", expires)
        fs = [allowlist.Finding("a/AGENTS.md", i + 1, "R1d", "x") for i in range(n)]
        return allowlist.apply(fs, [e], self.S, {"a/AGENTS.md"}, self.TODAY, level_of=lambda rule, path: "error")

    def test_expired_entry_suppresses_nothing_even_within_count(self):
        out = self.apply(1, 2, datetime.date(2026, 5, 31))
        self.assertEqual(sorted(f.rule for f in out), ["R1d", "allowlist"])

    def test_over_count_still_warns_before_expiry(self):
        out = self.apply(2, 1, datetime.date(2026, 6, 5))
        self.assertEqual([f.rule for f in out].count("R1d"), 2)
        self.assertTrue(any(f.level == "warn" and "expires in 4 days" in f.message for f in out))

    def test_exact_count_suppresses_all(self):
        self.assertEqual(self.apply(3, 3, datetime.date(2026, 8, 1)), [])


class ParseTest(unittest.TestCase):
    def test_parse_rejects_non_list(self):
        with self.assertRaises(ConfigError):
            allowlist.parse({}, allowlist.Settings(90, 10, 14), {"R1d"}, datetime.date(2026, 6, 1))


if __name__ == "__main__":
    unittest.main()
