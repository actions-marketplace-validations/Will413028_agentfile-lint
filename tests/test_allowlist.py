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
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("sub/AGENTS.md:1: warning: R5a:", r.stdout)
        self.assertIn("sub/AGENTS.md:2: warning: R5a:", r.stdout)
        self.assertIn("has count 1 but the file has 2 findings", r.stdout)

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
        out = allowlist.apply([], [e], s, {"a/AGENTS.md"}, today)
        self.assertEqual([f.rule for f in out], ["allowlist"])


class ApplyCountTest(unittest.TestCase):
    S = allowlist.Settings(90, 10, 14)
    TODAY = datetime.date(2026, 6, 1)

    def apply(self, n, count, expires):
        e = allowlist.Entry("R1d", "a/AGENTS.md", count, "why", expires)
        fs = [allowlist.Finding("a/AGENTS.md", i + 1, "R1d", "x") for i in range(n)]
        return allowlist.apply(fs, [e], self.S, {"a/AGENTS.md"}, self.TODAY)

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
