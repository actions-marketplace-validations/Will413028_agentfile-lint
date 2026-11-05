"""Output contract (docs/design.md, Output and exit codes; docs/adr/0004 decision 1 and 2).

Text: `file:line: severity: rule-id: message`, or `file: severity: rule-id: message` for a whole-file
finding, all on stdout. `--format json` and `--format github` carry the same findings.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import helpers
from agentfile_lint.finding import Finding, format_github

# A line R5a reports (>= 40 characters) that holds every character GitHub escaping cares about in a message.
SHARED = "Use 100% of the budget: split it a, b and c across the files"
CONFIG = (
    '[rules.R1d]\nlevel = "error"\nmax_chars = 500\n'
    '[[rules.R1b.limits]]\nglob = "AGENTS.md"\nmax_lines = 1\n'
)
FILES = {
    "AGENTS.md": SHARED + "\n" + "y" * 600 + "\n",  # whole-file warning (2 lines) and a line error
    "a,b/AGENTS.md": SHARED + "\n",                  # R5a warning on a path with a comma
    ".agentfile-lint.toml": CONFIG,
}
R5_MESSAGE = f"line repeats AGENTS.md:1 ('{SHARED}'); keep it in the ancestor only"
TEXT = [
    "AGENTS.md: warning: R1b: file is 2 lines, limit 1",
    "AGENTS.md:2: error: R1d: line is 600 characters, limit 500",
    f"a,b/AGENTS.md:1: warning: R5a: {R5_MESSAGE}",
]


def run(files, *args):
    return helpers.run_new(helpers.make_repo(files), "--today", "2026-06-01", *args)


class TextFormatTest(unittest.TestCase):
    def test_every_finding_on_stdout_with_its_severity(self):
        r = run(FILES)
        self.assertEqual((r.returncode, r.stderr), (1, ""))
        self.assertEqual(r.stdout.splitlines(), TEXT)  # sorted by file, line, rule; errors and warnings mixed

    def test_warn_as_error_prints_error(self):
        r = run(FILES, "--warn-as-error")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.splitlines(), [x.replace(": warning: ", ": error: ") for x in TEXT])

    def test_format_text_is_the_default(self):
        self.assertEqual(run(FILES, "--format", "text").stdout, run(FILES).stdout)

    def test_non_ascii_output_survives_a_non_utf8_pipe(self):
        # A Windows runner pipes stdout as cp1252; findings quote file text (here an R5a line in CJK).
        line = "所有指令檔都必須通過檢查，否則持續整合會失敗並停止合併這個變更；例外要寫在設定檔並附上理由與期限"  # >= 40 chars
        root = helpers.make_repo({"AGENTS.md": line + "\n", "sub/AGENTS.md": line + "\n"})
        env = dict(helpers.os.environ, PYTHONPATH=str(helpers.REPO), PYTHONIOENCODING="cp1252")
        for fmt in ("text", "json", "github"):
            r = helpers.subprocess.run([helpers.sys.executable, "-m", "agentfile_lint", "--format", fmt],
                                       cwd=root, env=env, capture_output=True)
            self.assertEqual((r.returncode, r.stderr), (0, b""), fmt)
            self.assertIn(line[:20].encode("utf-8"), r.stdout, fmt)  # R5a quotes the start of the line

    def test_unknown_format_is_a_usage_error(self):
        r = run(FILES, "--format", "xml")
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("--format", r.stderr)


class PathPrefixTest(unittest.TestCase):
    """`--path-prefix` (the Action's `working-directory`): every format reports workspace-relative paths."""

    def test_github_annotations_get_the_prefix(self):
        r = run(FILES, "--format", "github", "--path-prefix", "sub")
        self.assertEqual([line.split(",")[0] for line in r.stdout.splitlines()],
                         ["::warning file=sub/AGENTS.md", "::error file=sub/AGENTS.md", "::warning file=sub/a%2Cb/AGENTS.md"])
        self.assertIn("::sub/AGENTS.md: warning: R1b:", r.stdout)

    def test_prefix_is_normalized(self):
        r = run(FILES, "--path-prefix", "./sub//x/")
        self.assertTrue(r.stdout.startswith("sub/x/AGENTS.md: warning: R1b:"), r.stdout)

    def test_absolute_or_escaping_prefix_is_a_usage_error(self):
        for bad in ("/home/runner/work/r", "../up", ".."):
            with self.subTest(bad):
                r = run(FILES, "--path-prefix", bad)
                self.assertEqual((r.returncode, r.stdout), (2, ""))
                self.assertIn("--path-prefix", r.stderr)

    def test_paths_outside_the_repo_keep_their_form(self):
        from agentfile_lint.cli import _prefixed
        self.assertEqual(_prefixed("sub", "../shared.toml"), "../shared.toml")
        self.assertEqual(_prefixed("sub", "/etc/x.toml"), "/etc/x.toml")
        self.assertEqual(_prefixed("sub", "a/AGENTS.md"), "sub/a/AGENTS.md")

    def test_dot_and_empty_change_nothing(self):
        plain = run(FILES).stdout
        self.assertEqual(run(FILES, "--path-prefix", ".").stdout, plain)
        self.assertEqual(run(FILES, "--path-prefix", "").stdout, plain)


class JsonFormatTest(unittest.TestCase):
    def test_document_and_fields(self):
        r = run(FILES, "--format", "json")
        self.assertEqual((r.returncode, r.stderr), (1, ""))
        self.assertEqual(json.loads(r.stdout), {
            "version": 1,
            "findings": [
                {"file": "AGENTS.md", "line": None, "level": "warning", "rule": "R1b", "message": "file is 2 lines, limit 1"},
                {"file": "AGENTS.md", "line": 2, "level": "error", "rule": "R1d", "message": "line is 600 characters, limit 500"},
                {"file": "a,b/AGENTS.md", "line": 1, "level": "warning", "rule": "R5a", "message": R5_MESSAGE},
            ],
        })

    def test_no_findings_is_still_a_document(self):
        clean = {"AGENTS.md": "ok\n"}
        for args in ((), ("README.md",)):  # a run skipped for irrelevant file names prints one too
            r = run({**clean, "README.md": "r\n"}, "--format", "json", *args)
            self.assertEqual((r.returncode, r.stderr), (0, ""), args)
            self.assertNotEqual(r.stdout, "", args)
            self.assertEqual(json.loads(r.stdout), {"version": 1, "findings": []}, args)

    def test_exit_code_follows_errors_not_the_format(self):
        warn_only = {k: v for k, v in FILES.items() if k != "AGENTS.md"}
        warn_only["AGENTS.md"] = SHARED + "\n"
        for fmt in ("text", "json", "github"):
            self.assertEqual(run(warn_only, "--format", fmt).returncode, 0, fmt)
            self.assertEqual(run(FILES, "--format", fmt).returncode, 1, fmt)


class GithubFormatTest(unittest.TestCase):
    def test_workflow_commands(self):
        r = run(FILES, "--format", "github")
        self.assertEqual((r.returncode, r.stderr), (1, ""))
        self.assertEqual(r.stdout.splitlines(), [
            # Whole file: no `line`, so GitHub shows it on line 1; the message keeps the text line.
            "::warning file=AGENTS.md,title=R1b::AGENTS.md: warning: R1b: file is 2 lines, limit 1",
            "::error file=AGENTS.md,line=2,title=R1d::AGENTS.md:2: error: R1d: line is 600 characters, limit 500",
            "::warning file=a%2Cb/AGENTS.md,line=1,title=R5a::a,b/AGENTS.md:1: warning: R5a: "
            + R5_MESSAGE.replace("%", "%25"),
        ])

    def test_message_escaping(self):
        # actions/toolkit escapeData: % \r \n; `:` and `,` stay as they are in a message.
        for raw, escaped in (("%", "%25"), ("\r", "%0D"), ("\n", "%0A"), (":", ":"), (",", ",")):
            with self.subTest(repr(raw)):
                out = format_github(Finding("f.md", 3, "R1", f"a{raw}b"))
                self.assertEqual(out, f"::error file=f.md,line=3,title=R1::f.md:3: error: R1: a{escaped}b")

    def test_property_escaping(self):
        # actions/toolkit escapeProperty: escapeData plus `:` and `,`.
        for raw, escaped in (("%", "%25"), ("\r", "%0D"), ("\n", "%0A"), (":", "%3A"), (",", "%2C")):
            with self.subTest(repr(raw)):
                out = format_github(Finding(f"d{raw}/f.md", 0, f"R{raw}1", "m", level="warn"))
                data = f"d{raw}/f.md: warning: R{raw}1: m".replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
                self.assertEqual(out, f"::warning file=d{escaped}/f.md,title=R{escaped}1::{data}")

    def test_action_passes_format_github(self):
        text = (helpers.REPO / "action.yml").read_text(encoding="utf-8")
        self.assertIn("args=(--format github)", text)

    def test_action_working_directory_is_an_input_and_the_run_step_uses_it(self):
        # No YAML parser in the standard library: check the lines that carry the meaning.
        lines = (helpers.REPO / "action.yml").read_text(encoding="utf-8").splitlines()
        setup = lines.index(next(x for x in lines if "actions/setup-python@" in x))
        self.assertEqual(lines[setup + 1:setup + 3], ["      with:", "        python-version: ${{ inputs.python-version }}"])
        self.assertEqual([x.strip() for x in lines if "working-directory:" in x],
                         ["working-directory:", "working-directory: ${{ inputs.working-directory }}"])
        self.assertIn("  working-directory:", lines)  # an input, at the inputs level
        self.assertIn('args+=(--path-prefix "$prefix")', "\n".join(lines))


class ActionRunScriptTest(unittest.TestCase):
    """The action's `run:` script, executed by bash the way the runner does: a repository checked out to
    `$GITHUB_WORKSPACE/sub` gets workspace-relative annotation paths; `working-directory` pointing inside
    the workspace's own repository adds nothing."""

    @staticmethod
    def script() -> str:
        lines = (helpers.REPO / "action.yml").read_text(encoding="utf-8").splitlines()
        start = lines.index("      run: |") + 1
        return "\n".join(x[8:] for x in lines[start:] if x.startswith("        ") or not x.strip())

    def run_in(self, workspace: Path, cwd: Path) -> str:
        shim = Path(tempfile.mkdtemp(prefix="il-shim-"))  # the runner's `python` is setup-python's
        (shim / "python").symlink_to(sys.executable)
        env = dict(os.environ, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}", GITHUB_WORKSPACE=str(workspace),
                   IL_ACTION_PATH=str(helpers.REPO), IL_CONFIG="")
        r = subprocess.run(["bash", "-e", "-c", self.script()], cwd=cwd, env=env, capture_output=True, text=True)
        self.assertEqual(r.stderr, "")
        return r.stdout

    def test_checkout_in_a_subdirectory_gets_the_prefix(self):
        workspace = Path(tempfile.mkdtemp(prefix="il-ws-"))
        repo = helpers.make_repo({"AGENTS.md": SHARED + "\n", "a/AGENTS.md": SHARED + "\n"})
        shutil.move(str(repo), workspace / "sub")
        out = self.run_in(workspace, workspace / "sub")
        self.assertIn("::warning file=sub/a/AGENTS.md,line=1,title=R5a::sub/a/AGENTS.md:1:", out)

    def test_subdirectory_of_the_workspace_repo_adds_no_prefix(self):
        repo = helpers.make_repo({"AGENTS.md": SHARED + "\n", "a/AGENTS.md": SHARED + "\n"})
        out = self.run_in(repo, repo / "a")
        self.assertIn("::warning file=a/AGENTS.md,line=1,title=R5a::", out)


    def test_git_root_above_the_workspace_adds_no_prefix(self):
        repo = helpers.make_repo({"AGENTS.md": SHARED + "\n", "w/AGENTS.md": SHARED + "\n"})
        out = self.run_in(repo / "w", repo / "w")  # `..` cannot be prefixed; the paths stay as git reports them
        self.assertIn("::warning file=w/AGENTS.md,line=1,title=R5a::", out)


class InputRuleTest(unittest.TestCase):
    """E0 (formerly `input`): an instruction file that is not valid UTF-8."""

    BAD = {"AGENTS.md": b"ok\n\xff\xfe\n"}

    def entry(self, rule):
        return f'[[allowlist.entries]]\nrule = "{rule}"\npath = "AGENTS.md"\ncount = 1\nreason = "binary for now"\nexpires = 2026-06-30\n'

    def test_reported_as_e0(self):
        r = run(self.BAD)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (1, "AGENTS.md: error: E0: file is not valid UTF-8\n", ""))

    def test_an_allowlist_entry_may_name_e0(self):
        r = run({**self.BAD, ".agentfile-lint.toml": self.entry("E0")})
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_the_old_name_input_is_unknown(self):
        r = run({**self.BAD, ".agentfile-lint.toml": self.entry("input")})
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown rule 'input'", r.stderr)

    def test_rules_cannot_turn_e0_off(self):
        r = run({**self.BAD, ".agentfile-lint.toml": '[rules.E0]\nlevel = "off"\n'})
        self.assertEqual(r.returncode, 2)
        self.assertIn("rules: unknown key(s) E0", r.stderr)

    def test_list_rules_lists_e0(self):
        r = run({"AGENTS.md": "ok\n"}, "--list-rules")
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"(?m)^E0  error  ")


if __name__ == "__main__":
    unittest.main()
