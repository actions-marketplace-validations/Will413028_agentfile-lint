import unittest

import helpers

TOML = (
    '[rules.R1d]\nlevel = "error"\nmax_chars = 500\n'
    '[[allowlist.entries]]\nrule = "R1d"\npath = "AGENTS.md"\ncount = 1\nreason = "temporary"\nexpires = 2026-03-10\n'
)


class DateInjectionTest(unittest.TestCase):
    def setUp(self):
        self.root = helpers.make_repo({"AGENTS.md": "z" * 600 + "\n", ".agentfile-lint.toml": TOML})

    def run_at(self, day):
        r = helpers.run_new(self.root, "--today", day)
        return r.returncode, r.stdout, r.stderr

    def test_same_date_same_output_repeatedly(self):
        for day in ("2026-03-01", "2026-03-20"):
            first = self.run_at(day)
            for _ in range(3):
                self.assertEqual(self.run_at(day), first)

    def test_output_follows_the_injected_date(self):
        self.assertEqual(self.run_at("2026-01-15")[0:2], (0, ""))               # 54 days: silent
        code, out, _ = self.run_at("2026-03-01")                               # 9 days: warn
        self.assertEqual(code, 0)
        self.assertIn("AGENTS.md: warning: allowlist: entry for R1d expires in 9 days", out)
        code, out, _ = self.run_at("2026-03-11")                               # expired
        self.assertEqual(code, 1)
        self.assertIn("AGENTS.md: error: allowlist: entry for R1d expired on 2026-03-10", out)


if __name__ == "__main__":
    unittest.main()
