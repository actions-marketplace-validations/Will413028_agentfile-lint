# Changelog

All notable changes are listed here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.8.0] - 2026-11-05

### Changed (breaking)

- Override globs inherited through `extends` that match no analyzed instruction file are now a warning
  too, on the file that wrote them, naming `unset` as the fix (before, only the config the run loaded
  directly was checked). With `--warn-as-error` a shared config listing paths a repository lacks now
  fails until that repository unsets them.
- Lines are only ended by LF, CRLF or a lone CR, the way `grep -n` and editors count them. R1b's line
  count and the line numbers every rule reports no longer treat form feed, U+2028 or the other
  Unicode line breaks as line ends; a file with those characters may now report fewer lines and lower
  line numbers. Files without them are unchanged.

### Added

- `--format sarif` prints one SARIF 2.1.0 log for GitHub code scanning; the README shows how to upload
  it with `github/codeql-action/upload-sarif`. The action does not upload it.
- `--no-git` walks the current directory instead of listing git-tracked files, skipping `.git`,
  `node_modules` and similar directories by a fixed list; `.gitignore` is not read. The default is
  unchanged.
- Action input `working-directory` (default `.`) for a repository checked out to a subdirectory:
  `config` is relative to it and annotations point at the right file. Existing inputs are unchanged.

- `[discover] extend_globs` adds globs to `globs` instead of replacing them; the lists add up along
  `extends`.
- `[shared.duplicates] exclude` leaves files out of the R5a and R5b comparison entirely: an excluded
  file is neither reported nor used as the ancestor text. Both presets set `exclude = []`.
- `[[overrides]]` entries with `raise = true` raise a level (`error` or `warn`), from `off` too;
  entries without it still only lower, and lowering wins when both match a file (docs/adr/0006).
- `[[overrides]] unset = [globs]` with a `reason` removes globs from the overrides a config inherits
  through `extends`.
- Per-line directives `<!-- agentfile-lint-disable-next-line <ids> -- <reason> -->` drop the named
  rules' findings on the next line (docs/adr/0006). Ids and a reason are required; whole-file rules
  (`R1a`, `R1b`, `R1c`, `C1`) are not accepted. Suppressed findings do not count toward an allowlist
  entry's `count`.

### Changed

- `config --format json` adds `discover.extend_globs`, `shared.duplicates.exclude` and, on an override
  with `raise = true`, `"raise": true`; every 0.7.0 key is unchanged.
- `config --format json` prints the effective table each rule module returns from validation, the same
  `Config.rules` the engine reads levels from, so a defaulted key would show up for every id. The output
  of the default and strict presets is unchanged (a test compares it with the 0.7.0 output).
- `check-pins` numbers lines the same way.
- New pseudo rule `disable`, like `allowlist` outside every preset and every level setting: a malformed
  directive is an error (exit 1), a directive that suppresses nothing a warning. A line that starts with
  `<!-- agentfile-lint-disable` is now checked, so a repository with such a comment may see new findings.

### Fixed

- R1b no longer loses a line when a lone CR ends the line before an excluded block and an LF follows it.

## [0.7.0] - 2026-11-05

### Changed (breaking)

- One rule id is one check with one level (docs/adr/0005). R1 is split into `R1a` per-file bytes
  (`file-bytes`), `R1b` per-file lines (`file-lines`), `R1c` combined bytes on a path (`path-bytes`)
  and `R1d` line length (`line-length`); R4 into `R4a` dates and issue numbers (`dated-refs`) and
  `R4b` narrative words (`narrative-words`); R5 into `R5a` ancestor duplicates
  (`ancestor-duplicates`) and `R5b` sibling duplicates (`sibling-duplicates`). Findings keep their
  file, line and severity under the default and strict presets; only the id changes.
- The ids and aliases `R1`/`size`, `R4`/`rot` and `R5`/`duplicates` are a configuration error (exit
  2) in `[rules]`, allowlist entries and overrides; the message lists the new ids. They are not aliases
  for the group.
- Removed keys: `bytes_level`, `lines_level`, `path_limits` (now `R1c.limits`), `max_line_chars` (now
  `R1d.max_chars`), `narrative_level` and `sibling_level`; each fails with a message naming its
  replacement. Per-file limits move to `R1a.limits` (`{glob, max_bytes}`) and `R1b.limits`
  (`{glob, max_lines}`).
- New top-level table `shared` for parameters several ids use: `[shared.size]` (`excluded_blocks`)
  and `[shared.duplicates]` (`ancestor_pairs`, `min_chars`, `ignore_headings`, `ignore_patterns`).
- Allowlist entries require `count`, the number of findings of that rule in that file they accept.
  More findings than `count`: none is suppressed and the entry reports an error; fewer: the entry
  reports an error asking to lower `count`. In 0.6.0 one entry hid every finding of its rule in the
  file, including an R1 path error behind a line-count exception.

### Graduated

- `R1a`: split from R1 (shipped at `error` since 0.1.0); per-file bytes, no default limit.
- `R1c`: split from R1 (shipped at `error` since 0.1.0); the 32 KiB combined size on a path.

## [0.6.0] - 2026-11-04

### Changed (breaking)

- Text output: every finding is `file:line: severity: rule-id: message`, with `severity` `error` or
  `warning`; a finding about a whole file is `file: severity: rule-id: message` (it used to print line
  `:0`). All findings go to stdout; errors used to go to stderr. Usage and configuration errors (exit
  2) stay on stderr, and exit codes do not change. A program that parses the text must accept both
  line shapes; `--format json` is meant for programs (docs/adr/0004).
- The pseudo rule `input` (an instruction file that is not valid UTF-8) is now `E0`. An allowlist entry
  may name it; `[rules]` cannot turn it off. `--list-rules` lists it.
- R1 single-file limits count the bytes on disk: a CRLF is two bytes (it was one), the unit
  `path_limits` already used, so a Windows-line-ending file under a `limits` `max_bytes` may now
  exceed it. `excluded_blocks` still drop out, with their raw bytes and a trailing LF, CRLF or CR. A long
  line after an excluded block reports its line number on disk; it used to subtract the block's lines
  (docs/adr/0004).
- The GitHub Action runs with `--format github`, so findings appear as annotations; its inputs do not
  change.

### Added

- `[[overrides]]`: permanent path scopes, each with `paths` (globs), `rules` (a rule id or alias mapped
  to `warn` or `off`) and a required `reason`. An override only lowers a level; for one file and rule
  the lowest applies. Under `extends` the lists concatenate (the one list that does not replace). A glob
  in the directly loaded config that matches no instruction file is an `allowlist` warning. This is the
  remedy for R5's translated and example copies short of turning R5 off (docs/adr/0004).
- Rule aliases: a rule's name from `--list-rules` (`size` for R1) works wherever its id does, in
  `[rules.<id>]`, an allowlist `rule` and override `rules` (`E0` and `allowlist` have no alias). Each config file is resolved before merging; one file naming
  a rule by both fails (exit 2). Findings still print the id.
- `--format json`: one document, `{"version": 1, "findings": [...]}`, each finding with `file`, `line`
  (`null` for a whole file), `level` (`error` or `warning`), `rule` and `message`. `version` goes up
  only when a field is removed or changes meaning.
- `--format github`: GitHub workflow commands (`::error` / `::warning` with `file`, `line` and `title`),
  escaped as `actions/toolkit` does; the message is the text-format line, so findings past GitHub's
  annotation limits still show their location in the log.
- `docs/field-report.md`: what 0.4.0, 0.5.0 and `preset:strict` report on 22 popular public
  repositories with no config, and what the real problems looked like.
- `docs/adr/0004-public-exceptions-output-ids.md`: the output format, permanent per-path exceptions,
  rule aliases and byte measurement planned for 0.6.0, and an amendment to ADR 0001.

### Changed

- `check-pins` (experimental) prints its findings on stdout in the text format above
  (`file:line: error: check-pins: message`) and its summary on stderr; with `--require-refs` and no
  reference found it prints `check-pins: error: no reference to … found` on stdout (exit 1, as before).
- `check-pins` is experimental: its output and options may change in any minor release. The README
  and `check-pins --help` mark it "(experimental)"; the upgrade notes in `docs/versioning.md` call it
  optional. `vendor` and `verify.py` stay part of the compatibility contract.
- Versioning before 1.0: a change to the output format, a rule id or a config key is a minor version,
  listed under `Changed (breaking)`; exit codes still change only in a major version
  (`docs/versioning.md`).
- Documentation: Claude Code does cut files it loads on demand (a subdirectory `CLAUDE.md`,
  `CLAUDE.local.md`, path-scoped rules) at 40,000 characters with a 200K context; 0.5.0's design notes,
  `docs/rules.md` and preset comment said it truncates nothing. R1 does not check characters;
  `docs/rules.md` states the blind spot and a byte limit that approximates it (docs/adr/0003,
  Amendment).

## [0.5.0] - 2026-11-03

### Changed (breaking)

- An allowlist entry whose `path` is a same-directory symlink (see Fixed) now fails as "no longer
  needed" (exit code 1), because that path is analyzed under its target. Remove the entry, or move it to
  the target path if the target still violates the rule.

### Added

- R1 `limits` entries accept `bytes_level` and `lines_level` (`error`, `warn` or `off`) to give the byte
  and the line limit of one entry their own level. Omitted, a limit follows the rule level, as before;
  an entry level never raises a finding above the rule level.
- R1 `path_limits`: `{glob, max_bytes, level}` entries that limit the combined size of a file and the
  files matching the same glob in its ancestor directories, reported on the file where the total first
  exceeds the limit. `path_limits = []` turns it off.
- R1 `max_line_chars` may be omitted; then line length is not checked. A config that sets it keeps the
  old behavior.
- R5 `ancestor_pairs`: `same-name` counts as ancestor and descendant only a file with the same name
  in a strict ancestor directory (`AGENTS.md` and `sub/AGENTS.md`, which one agent loads together);
  `any` also counts different names and two files in one directory, as before. Other pairs are
  siblings (`sibling_level`).
- `preset:strict` (`extends = ["preset:strict"]`): the default preset plus R3b, R4, R6 and C1 at
  `warn`, and R5 on any pair (`ancestor_pairs = "any"`) and between siblings at `warn`: the 0.4.0
  defaults, except R1.
- `docs/rules.md`: for each rule, why a finding is a problem, the source of its default, whether it is
  in the default preset or `preset:strict`, and its measured false-positive rate with a Wilson 95%
  interval. The README opens with a zero-config run, a `preset:strict` run, an example of adding other
  instruction files and a comparison with similar tools. `CONTRIBUTING.md` and issue templates (bug,
  false positive, rule proposal).

### Changed

- The GitHub Action (`action.yml`) sets up Python with `actions/setup-python` v7.0.0 instead of v5.6.0.
  Inputs are unchanged.
- The default preset runs only objective checks. R3b (path references), R4 (dates, issue numbers,
  narrative words) and R6 (copied constants) guess, and C1 checks a convention of this tool, so they
  are `off` by default. R5 by default reports only same-name ancestor pairs (`ancestor_pairs =
  "same-name"`): 0 of 13 such findings on ten held-out public repositories were false positives. Other
  pairs (different names, the same directory, siblings) are `off` by default; a config that set
  `[rules.R5] level = "error"` to stop a copied CLAUDE.md next to AGENTS.md now needs
  `ancestor_pairs = "any"` for that. On twelve popular
  public repositories with no config, 0.4.0's sampled false-positive rates were R3b 95%, R4 84%, R5
  100% and R6 76%, and every C1 finding was a difference of convention. To keep the 0.4.0 behavior,
  add `extends = ["preset:strict"]` to your config. See docs/adr/0003.
- R1 default limits use only limits that an agent's documentation states. AGENTS.md files on one path
  from the root that total over 32768 bytes are an error (`path_limits`): Codex reads AGENTS.md from the
  root down to the working directory and stops adding files at 32 KiB in total
  (`project_doc_max_bytes`). On 22 public repositories with no config, a per-file check finds 3 files in
  2 repositories; the combined check reports 16 files (where the overflow starts) in 6 repositories. AGENTS.md
  and CLAUDE.md over 200 lines are a warning: Claude Code asks for fewer than 200 lines per file and
  reads AGENTS.md when there is no CLAUDE.md, but truncates nothing. The 12000/6000-byte limits and the
  500-character line limit, which had no external source, are removed from the default. To keep the
  0.4.0 limits, copy them into your config:

  ```toml
  [rules.R1]
  max_line_chars = 500
  path_limits = []

  [[rules.R1.limits]]
  glob = "AGENTS.md"
  max_bytes = 12000
  max_lines = 200

  [[rules.R1.limits]]
  glob = "CLAUDE.md"
  max_bytes = 12000
  max_lines = 200

  [[rules.R1.limits]]
  glob = "**/AGENTS.md"
  max_bytes = 6000
  max_lines = 200

  [[rules.R1.limits]]
  glob = "**/CLAUDE.md"
  max_bytes = 6000
  max_lines = 200
  ```

### Fixed

- Two tracked instruction files in the same directory that are the same file (for example
  `CLAUDE.md -> AGENTS.md`) are now analyzed once, under the non-symlink path (the first in sort order
  when all are symlinks). Before, every rule checked the file again under its second name: R1 and R4
  reported each problem twice, and R5 reported the file as a duplicate of itself. A symlink to a file
  in another directory is still analyzed as its own file, because it is a separate place an agent
  loads; in an ancestor or descendant directory R5 reports the repeated lines.
- C1 (`import-only`) accepts a `CLAUDE.md` that is a symlink to the `AGENTS.md` next to it, as it
  accepts the `@AGENTS.md` import line. `forbid` still reports a symlinked `CLAUDE.md`.

## [0.4.0] - 2026-11-01

The project is renamed from `instruction-lint` to `agentfile-lint`. The name `instruction-lint` is already
taken on PyPI by an unrelated package, so a bare `uvx instruction-lint` or `pip install instruction-lint`
would install someone else's code. While the version is below 1.0, a minor release may carry breaking
changes; this one does. Read the upgrade recipe before moving a pin.

### Changed (breaking)

- Python package: `instruction_lint` is now `agentfile_lint`; run it as `python -m agentfile_lint`.
- Distribution name and console command: `agentfile-lint`.
- Repo config file: `.agentfile-lint.toml`. If only `.instruction-lint.toml` exists, the tool exits with
  code 2 and a message asking you to rename it; it does not read the old file. This check is removed at 1.0.
- pre-commit hook id and name: `agentfile-lint`.
- GitHub Action: name `agentfile-lint`; it runs `python -m agentfile_lint`.
- Vendored entry script: `agentfile-lint.py` (was `instruction-lint.py`); the vendored package directory is
  `agentfile_lint/`.
- `check-pins` looks for `agentfile-lint` by default (`check_pins.repo`).

Upgrade recipe:

1. `git mv .instruction-lint.toml .agentfile-lint.toml`.
2. Change every reference to the repository URL to `github.com/Will413028/agentfile-lint` (the old URL
   redirects, but `check-pins` matches the new name) and pin the new full commit SHA everywhere.
3. In `.pre-commit-config.yaml`, change the hook `id` to `agentfile-lint`.
4. Replace the command `instruction-lint ...` with `agentfile-lint ...` (or `python -m instruction_lint` with
   `python -m agentfile_lint`) in scripts, CI and `uvx --from git+...` lines.
5. Vendored copies: run `agentfile-lint vendor --to <dir> --force`, delete the old `instruction-lint.py` and
   `instruction_lint/`, and update the call sites to `agentfile-lint.py`.
6. Run `agentfile-lint check-pins` and the normal check.

## [0.3.1] - 2026-11-01

### Changed

- `rubric.md`: J1 also asks whether a line is needed before acting and drops enumerations that `ls` or a
  search already shows; J3 sends rules with no exceptions to their guard and style rules to the
  formatter or linter.
- `rubric.md`: the judgment checks R7-R9 are renamed J5-J7 so they cannot be mistaken for linter rule
  IDs; J3 states how a judgment rule can fail. The pull request snippet follows (J1-J7).
- `rubric.md`: J4 says `R6` finds numeric candidates only, so copied lists of names need a reviewer.
- `rubric.md`: the linter runs before the read-through; J2 notes that agents differ in when they load
  a subdirectory's file and that R5 skips lines shorter than `min_chars`.
- `rubric.md`: R5 is described as comparing normalized lines and skipping headings; R6 lists constant
  names only when a number follows them.

## [0.3.0] - 2026-10-31

While the version is below 1.0, a minor release may carry breaking changes; this one does (see
"Changed (breaking)"). Read the entry before moving a pin.

### Changed (breaking)

- `R1` chooses its limits by path glob instead of depth tiers. `[rules.R1.max_bytes]` with `root`,
  `subproject` and `nested` is removed; a config that still sets `max_bytes` under `rules.R1` fails with
  exit code 2 and a message pointing here. Entries are `[[rules.R1.limits]]` tables, the first whose
  `glob` matches the file applies, each with `max_bytes`, `max_lines` or both. A file that matches no
  entry has no size limit. Globs use the same matcher as R2 shapes and R3c specs (`*` never crosses `/`,
  `**/` matches zero or more directories). A repository config that sets `limits` replaces the preset list.

  Migration (depth tiers 12000 / 10000 / 6000 become):

  ```toml
  [[rules.R1.limits]]
  glob = "AGENTS.md"        # was root
  max_bytes = 12000

  [[rules.R1.limits]]
  glob = "*/AGENTS.md"      # was subproject (depth 1)
  max_bytes = 10000

  [[rules.R1.limits]]
  glob = "**/AGENTS.md"     # was nested (depth 2 and deeper)
  max_bytes = 6000
  ```

  Repeat the entries for `CLAUDE.md` if you lint it.
- Default limits: root `AGENTS.md` / `CLAUDE.md` 12000 bytes and 200 lines; `**/AGENTS.md` / `**/CLAUDE.md`
  6000 bytes and 200 lines (was 8000 and 4000 bytes by depth). The 200-line limit follows Claude Code's
  guidance of fewer than 200 lines per CLAUDE.md file.
- The pre-commit hook now sets `always_run: true` and no longer filters by `files`: rules R3a, R3b and R3c
  read test files, source and docs, so a hook that only ran when an instruction file changed missed their
  breakage. The tool still analyzes the full tracked set.

### Added

- `R1` line limit: `file is N lines, limit L` (`max_lines` in a `limits` entry).
- README and design notes: run on every commit and push, plus a weekly scheduled CI run so allowlist
  expiry warnings appear without commits.

## [0.2.1] - 2026-10-31

### Changed

- The README written by `instruction-lint vendor` now has an "Upgrades" section that documents the upgrade
  path (regenerate from a newer tag, open a pull request, review the diff), so a vendored copy needs no hand edits.

## [0.2.0] - 2026-10-31

### Added

- Rule R2 (shape): required section headings, exact or ordered, plus optional title, one-line purpose,
  bullet-only sections and must-match patterns, per glob.
- Rule R3a (test-names): a backticked test name must be defined in a tracked test file (Go and Python
  patterns in the preset).
- Rule R3b (path-refs): a backticked path must exist; resolved against the file's directory, its
  ancestors, the root and configured `base_dirs` (heuristic).
- Rule R3c (spec-refs): `§N` references must match a numbered heading of the spec document mapped to the file.
- Rule R4 (rot): dates and issue numbers at the rule level, narrative words at `narrative_level`.
- Rule R5 (duplicates): identical lines in ancestor/descendant files at the rule level, in sibling
  files at `sibling_level`; always compares the full tracked set.
- Rule R6 (constants): copied-constant candidates, always warnings.
- Rule C1 (claude-md): `import-only` (default) or `forbid`.
- `instruction-lint check-pins`: every reference to this tool (pre-commit `rev:`, `uvx --from git+...@`,
  `uses: owner/instruction-lint@`) must pin the same full 40-hex SHA; reports `file:line`.
- `instruction-lint config --format json`: the effective merged configuration as deterministic JSON.
- `rubric.md` and `docs/pr-template-snippet.md` for the judgment checks that do not run in CI;
  `docs/versioning.md` for the release and upgrade process.
- Findings may carry their own level (a rule at `error` can still report some findings as warnings);
  the rule level only caps them.

### Changed

- All new rules enter the default preset at `warn`. A rule whose own spec says `error` (R2, R3a, R4
  dates and issue numbers, R5 ancestor/descendant, C1) is raised per repository with `level = "error"`.
- R1 output format, exit codes and limits are unchanged.

### Graduated

Rules above `warn` in the default preset. Everything not listed here must start at `warn`
(`tests/test_versioning.py` enforces it).

- `R1`: shipped at `error` in 0.1.0, before the warn-first policy.

## [0.1.0] - 2026-10-31

### Added

- Rule R1 (size): byte limit by path depth, per-line character limit, excluded marker blocks.
- Allowlist: time-boxed exceptions with a reason and an expiry date; expired, no-longer-needed and
  soon-to-expire entries are reported; `max_days` and `max_entries` bounds.
- Discovery: `git ls-files` entries matching configurable globs, never `*.local.md`; command-line
  file names only decide whether to run.
- `instruction-lint vendor --to DIR`: a reproducible, self-contained copy of the runner with an
  entry script, `verify.py` and a README manifest (upstream tag, commit, SHA-256 per file).
- `--version`, `--list-rules`, `--today`, `--warn-as-error`, `--config`.
