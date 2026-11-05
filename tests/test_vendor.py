import getpass
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import helpers

ENTRY = "agentfile-lint.py"


def vendor(dest, *extra):
    env = dict(os.environ, PYTHONPATH=str(helpers.REPO))
    return subprocess.run(
        [sys.executable, "-m", "agentfile_lint", "vendor", "--to", str(dest),
         "--ref-tag", "v9.9.9", "--ref-commit", "a" * 40, *extra],
        capture_output=True, text=True, env=env,
    )


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def verify(dest):
    return subprocess.run([sys.executable, "-I", str(Path(dest) / "verify.py")], capture_output=True, text=True)


class PackageDataTest(unittest.TestCase):
    def test_wheel_ships_the_vendored_notices(self):
        # The wheel carries non-Python files only through package-data; the copy and the wheel must agree.
        import tomllib
        from agentfile_lint.vendor import VENDORED_NOTICES
        data = tomllib.loads((helpers.REPO / "pyproject.toml").read_text(encoding="utf-8"))
        shipped = data["tool"]["setuptools"]["package-data"]["agentfile_lint"]
        for name in VENDORED_NOTICES:
            self.assertIn(name, shipped)
            self.assertTrue((helpers.REPO / "agentfile_lint" / name).is_file(), name)


class VendorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="il-vendor-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.a = self.tmp / "a"
        self.assertEqual(vendor(self.a).returncode, 0)

    def test_two_runs_are_byte_identical(self):
        b = self.tmp / "b"
        self.assertEqual(vendor(b).returncode, 0)
        self.assertEqual(tree(self.a), tree(b))

    def test_layout_and_no_machine_details(self):
        files = tree(self.a)
        self.assertIn(ENTRY, files)
        self.assertIn("verify.py", files)
        self.assertIn("agentfile_lint/presets/default.toml", files)
        self.assertFalse([n for n in files if "__pycache__" in n or n.endswith(".pyc")])
        self.assertNotIn("agentfile_lint/vendor.py", files)
        # The vendored PyYAML travels with its license and source record, byte for byte.
        for name in ("__init__.py", "loader.py", "LICENSE", "PROVENANCE"):
            self.assertEqual(files[f"agentfile_lint/_yaml/{name}"],
                             (helpers.REPO / "agentfile_lint" / "_yaml" / name).read_bytes(), name)
        self.assertNotIn("agentfile_lint/_yaml/cyaml.py", files)
        readme = files["README.md"].decode()
        self.assertIn("vendored PyYAML", readme)
        self.assertIn("`v9.9.9`", readme)
        self.assertIn("a" * 40, readme)
        self.assertIn("accidental modification", readme)
        self.assertIn("\n## Upgrades\n", readme)
        self.assertIn("pull request diff is the review point", readme)
        self.assertIn("keeps no\nupgrade script", readme)
        blob = b"\n".join(files.values())
        for needle in (str(self.tmp), str(helpers.REPO), tempfile.gettempdir()):
            self.assertNotIn(needle.encode(), blob, needle)
        # The vendored PyYAML is byte-identical to upstream (checked above); its English prose may
        # contain any short word, so the user-name and timestamp checks cover only our own files
        # (PROVENANCE is ours).
        upstream = {n for n in files if n.startswith("agentfile_lint/_yaml/") and not n.endswith("/PROVENANCE")}
        own = b"\n".join(c for n, c in files.items() if n not in upstream)
        for who in {getpass.getuser(), os.environ.get("USER", "")} - {""}:
            if len(who) > 3:
                self.assertNotIn(who.encode(), own, who)
        self.assertIsNone(re.search(rb"\b20\d\d-\d\d-\d\d[T ]\d\d:\d\d", own))

    def test_verify_passes(self):
        r = verify(self.a)
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_verify_fails_on_modified_file(self):
        for name in ("agentfile_lint/cli.py", "agentfile_lint/presets/default.toml", ENTRY, "verify.py",
                     "agentfile_lint/_yaml/LICENSE"):
            d = self.tmp / ("m-" + name.replace("/", "_"))
            shutil.copytree(self.a, d)
            with open(d / name, "ab") as fh:
                fh.write(b"\n# x\n")
            r = verify(d)
            self.assertEqual(r.returncode, 1, name)
            self.assertIn(name, r.stderr)

    def test_verify_fails_on_extra_file(self):
        (self.a / "agentfile_lint" / "extra.py").write_text("x = 1\n")
        r = verify(self.a)
        self.assertEqual(r.returncode, 1)
        self.assertIn("agentfile_lint/extra.py", r.stderr)

    def test_verify_ignores_pycache(self):
        cache = self.a / "agentfile_lint" / "__pycache__"
        cache.mkdir()
        (cache / "x.pyc").write_bytes(b"\0")
        self.assertEqual(verify(self.a).returncode, 0)

    def test_verify_fails_on_deleted_file(self):
        (self.a / "agentfile_lint" / "engine.py").unlink()
        r = verify(self.a)
        self.assertEqual(r.returncode, 1)
        self.assertIn("agentfile_lint/engine.py", r.stderr)

    def test_refuses_non_empty_target_without_force(self):
        r = vendor(self.a)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--force", r.stderr)

    def test_force_replaces_contents(self):
        (self.a / "stale.txt").write_text("old")
        self.assertEqual(vendor(self.a, "--force").returncode, 0)
        self.assertFalse((self.a / "stale.txt").exists())
        self.assertEqual(verify(self.a).returncode, 0)

    def test_refuses_the_source_checkout(self):
        r = vendor(helpers.REPO, "--force")
        self.assertEqual(r.returncode, 2)

    def test_vendored_copy_matches_module_run_offline(self):
        cases = [
            {"AGENTS.md": "ok\n"},
            {"AGENTS.md": "z" * 13000 + "\n", "sub/AGENTS.md": "y" * 600 + "\n"},
            {"AGENTS.md": "ok\n", ".agentfile-lint.toml": "bogus = 1\n"},
        ]
        for files in cases:
            root = helpers.make_repo(files)
            self.addCleanup(shutil.rmtree, root, True)
            ref = helpers.run_new(root, "--today", "2026-01-01")
            got = subprocess.run(
                [sys.executable, "-I", str(self.a / ENTRY), "--today", "2026-01-01"],
                cwd=root, capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "")},
            )
            self.assertEqual((got.returncode, got.stdout, got.stderr), (ref.returncode, ref.stdout, ref.stderr))
        self.assertEqual(verify(self.a).returncode, 0)  # running it left the tree intact (no bytecode written)

    def test_version_flag(self):
        r = helpers.run_new(self.tmp, "--version")
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"agentfile-lint \d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
