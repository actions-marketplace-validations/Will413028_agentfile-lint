# Versioning, changelog and upgrades

## Versions

Semantic versions as git tags (`v0.2.0`). The tag points at a commit; consumers pin the full
40-hex commit SHA and note the version in a comment. Before 1.0 (SemVer allows any change in 0.y.z),
a minor version may also change the output format, rename or remove a rule id or rule alias, or rename or remove a
config key; every such change is listed under "Changed (breaking)" in the changelog. Always read the
changelog before moving a pin.

| Change | Version part |
|---|---|
| Exit codes | major |
| Output format, the behavior of `vendor` or `verify.py`, a removed or renamed rule id, rule alias or config key | major from 1.0; minor before 1.0, under "Changed (breaking)" |
| A rule promoted from `warn` to `error`, a changed default limit, a new rule, a new option | minor |
| A bug fix in a rule or command, documentation | patch |

Experimental features are marked "(experimental)" in the README and in their `--help`. They are
outside this table: their output and options may change in any minor release, listed under `Changed`.
Today that is `check-pins` (docs/adr/0004). Its `[check_pins]` config table is not experimental: the
main command validates it, so it follows the rules for config keys.

## Changelog rules

`CHANGELOG.md` follows Keep a Changelog. Every user-visible change has an entry in the section of
the release that ships it (`Added`, `Changed`, `Fixed`, `Removed`).

- A new rule enters the default preset at `warn`, or `off` when it is a heuristic (docs/adr/0003) or
  checks for a reader the default does not target (docs/adr/0007). Whatever its specification calls
  the intended severity, the preset ships no higher than `warn`; a repository raises it with `level = "error"` after a clean run.
- Promoting a rule to `error` in the preset is a minor change and must be listed under a
  `### Graduated` heading, one bullet per rule starting with the rule id in backticks.
- `tests/test_versioning.py` fails when a rule in any shipped preset (`agentfile_lint/presets/*.toml`)
  is above `warn` and not listed under `Graduated` (`off` is allowed: lowering needs no entry), and when `pyproject.toml`, `__version__` and the newest
  changelog section disagree. The pseudo rules `E0`, `allowlist` and `disable` are not in
  any preset and have no level, so the warn-first policy does not apply to them.
- Changing a default value changes every consumer that did not override it: say so under `Changed`.

## Branches and releasing

Work lands on `dev` (pushed directly; CI runs on every push). `main` holds released code only and
changes through a pull request from `dev` with all required checks green. Merge `dev` into `main`
with a merge commit, never squash or rebase: a squashed `main` no longer contains the `dev` commits,
and the next release pull request conflicts with itself.

1. On `dev`: move the `Unreleased` entries under `## [x.y.z] - YYYY-MM-DD`, update the version in
   `pyproject.toml` and `agentfile_lint/__init__.py`; `make check`; push and wait for CI. For a
   minor release, first re-read the Claude Code pages docs/rules.md cites for H2 to H5, M3, M4 and A6 and
   update the lists when they changed.
2. Open a pull request `dev` -> `main` and merge it with a merge commit once checks are green.
3. Tag `vx.y.z` (annotated, signed) on the merge commit on `main` and note the full commit SHA for
   consumers.
4. Publish a GitHub release for the tag (notes from the changelog section). `publish.yml` then
   builds the sdist and wheel from the tag and uploads them to PyPI with Trusted Publishing (no stored
   token). PyPI holds the name and offers an install path; consumers still pin the full commit SHA.
5. Fast-forward `dev` to the merge commit (`git merge --ff-only origin/main` on `dev`, then push;
   if `dev` moved on after the pull request, `git merge origin/main` instead).
   `dev` is the repository's default branch, and `pre-commit autoupdate` takes the newest tag
   reachable from it; without this step it finds only tags made before the branch model (0.4.0).

## Upgrading a consumer

Pick one mechanism per consumer. Optionally, `check-pins` (experimental) checks that the references
agree.

- pre-commit: `pre-commit autoupdate --repo <url>` rewrites `rev:` to a tag; use
  `pre-commit autoupdate --freeze` to write the full commit SHA with the tag as a comment. It finds
  0.9.0 and later (see step 5 above); for an older version set `rev:` by hand.
- renovate: its pre-commit manager updates `rev:` in `.pre-commit-config.yaml`; actions and `uvx`
  references need their own rules or a manual edit. Dependabot's coverage of pre-commit files was not
  verified for this document; check the current documentation before relying on it.
- `uvx --from git+<url>@<sha>` and `uses: owner/agentfile-lint@<sha>`: edit by hand (or with
  renovate's regex manager) in one commit, so every reference moves together.
- Vendored copy: run `agentfile-lint vendor --to <dir> --force` from the new tag's checkout; the
  diff of that change is the review. `verify.py` detects accidental edits only.

After any upgrade run the normal check, and `agentfile-lint check-pins` if you use it; new `warn`
output after an upgrade is expected and is the point of the warn-first policy.

## `check-pins` (experimental)

Its output and options may change in a minor release (see Versions).

`agentfile-lint check-pins [--repo STRING] [--files GLOB ...] [--require-refs]` scans tracked
files (default: `.pre-commit-config.yaml`, `lefthook.y*ml`, `.github/workflows/*.y*ml`) for
references to this tool and fails when a reference is not a full 40-hex SHA or when two
references pin different SHAs. Findings are printed on stdout as `file:line: error: check-pins: message`
(exit 1) and the summary on stderr; with `--require-refs` and no reference found it prints
`check-pins: error: no reference to … found` on stdout and exits 1.
`[check_pins]` in the config sets `repo` and `files`. It reads lines, not YAML: anchors,
multi-line values and `${{ }}` expressions are not understood (an expression is reported as a non-SHA).
It checks consistency among the references it finds; it cannot prove it found all of them.
