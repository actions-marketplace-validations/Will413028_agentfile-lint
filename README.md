# agentfile-lint

A linter for agent instruction files (`AGENTS.md`, `CLAUDE.md`) that a team runs the same way in every
repository: rules are data in one TOML file, debt exceptions expire while permanent path scopes live in
the config with a required reason, and the runner is plain Python with nothing to install beyond
it (PyYAML is vendored inside), so the git hook, CI and a vendored copy give the same answer. It
checks `AGENTS.md`, `CLAUDE.md`, Claude Code's `.claude/rules/`, `SKILL.md` files, hooks settings and
`.mcp.json`.

```sh
uvx agentfile-lint        # in any git repository; no config needed
```

With no config it runs only checks whose findings are facts. From a demo repository:

```text
$ uvx agentfile-lint
AGENTS.md: warning: R1b: file is 211 lines, limit 200
AGENTS.md:9: warning: R3a: test `test_login_redirects` is not defined in any searched test file
services/api/AGENTS.md: error: R1c: file and its ancestors (AGENTS.md) total 34618 bytes, limit 32768
services/api/AGENTS.md:3: warning: R5a: line repeats AGENTS.md:8 ('Never edit generated files under `gen/`; change the schem...'); keep it in the ancestor only
$ echo $?
1
```

Codex stops reading `AGENTS.md` files on a path once they total 32 KiB (its default), so the total for
`services/api/AGENTS.md` is an error; the others are warnings. `extends = ["preset:strict"]` in
`.agentfile-lint.toml` adds the heuristic rules, which guess and are wrong more often (rates in
[`docs/rules.md`](docs/rules.md)). Same repository:

```text
$ printf 'extends = ["preset:strict"]\n' > .agentfile-lint.toml
$ uvx agentfile-lint
AGENTS.md: warning: R1b: file is 211 lines, limit 200
AGENTS.md:9: warning: R3a: test `test_login_redirects` is not defined in any searched test file
CLAUDE.md: warning: C1: CLAUDE.md must contain only the line '@AGENTS.md'
services/api/AGENTS.md: error: R1c: file and its ancestors (AGENTS.md) total 34618 bytes, limit 32768
services/api/AGENTS.md:3: warning: R5a: line repeats AGENTS.md:8 ('Never edit generated files under `gen/`; change the schem...'); keep it in the ancestor only
services/api/AGENTS.md:4: warning: R3b: path `src/legacy/router.py` not found from this file's directory, its ancestors, the repo root or base_dirs
services/api/AGENTS.md:5: warning: R4b: narrative word 'currently'; describe the current rule, not its history
services/api/AGENTS.md:5: warning: R6: possible copied constant '`MAX_RETRIES = 5`'; point to the code instead of repeating the value
```

| Rule | Default | `preset:strict` | What it checks |
|---|---|---|---|
| `R1a` | error | error | bytes per file: your own limits by glob (none by default) |
| `R1b` | warn | warn | lines per file: `AGENTS.md` or `CLAUDE.md` over 200 lines; your own limits by glob |
| `R1c` | error | error | `AGENTS.md` files on one path over 32 KiB in total |
| `R1d` | off | off | characters per line (`max_chars`) |
| `R1e` | warn | warn | characters per file Claude Code loads on demand (subdirectory `CLAUDE.md` and `CLAUDE.local.md`, `.claude/rules/`): over 40,000 |
| `R2` | warn | warn | file shape: required section headings in order, optional title, one-line purpose, bullet-only sections (needs config) |
| `R3a` | warn | warn | a test name in backticks is defined in a tracked test file |
| `R3b` | off | warn | a path in backticks exists (heuristic) |
| `R3c` | warn | warn | a `§N` reference matches a numbered heading in the mapped spec document (needs config) |
| `R4a` | off | warn | dates and issue numbers (heuristic) |
| `R4b` | off | warn | narrative words such as "currently" (heuristic) |
| `R5a` | warn | warn | identical lines in a same-name file of an ancestor directory; strict: any file in an ancestor or the same directory |
| `R5b` | off | warn | identical lines in sibling files |
| `R6` | off | warn | candidates for constants copied from code (heuristic, always a warning) |
| `C1` | off | warn | `CLAUDE.md` is only the line `@AGENTS.md` (`import-only`) or absent (`forbid`) |
| `S1`–`S4`, `S12` | warn | warn | `SKILL.md` for Claude Code: frontmatter is valid YAML, under 500 lines, `description` plus `when_to_use` within `[rules.S3] max_chars` (1536), `metadata` is a map, no character Claude Code refuses in `name` or the directory name |
| `S5`–`S11` | off | off | `SKILL.md` for claude.ai upload and the Skills API (`preset:agentskills`, below): frontmatter present, `name` and `description` limits, `name` equals its directory, only the specification's six keys |
| `allowlist` | error | error | exceptions: expired, no-longer-needed or miscounted (`count` above or below the findings) allowlist entries fail, entries warn before they expire; an override glob that matches no file warns |
| `disable` | error | error | per-line directives: a malformed one fails, one that suppresses nothing warns |

Every rule except `R1a` and `R1c` ships at `warn` or `off`; raise a rule to `error` in your own config once it is
clean. Why each rule exists, where its default comes from and its measured false-positive rate:
[`docs/rules.md`](docs/rules.md). What it found on 22 popular public repositories with no config, and
how that changed from 0.4.0: [`docs/field-report.md`](docs/field-report.md).

### Other instruction files

The default checks `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md` and the `.md` files under `.claude/rules/`,
at any depth (a rules file named `*.local.md` only through `extend_globs`). A `CLAUDE.local.md` is usually untracked, so only `--no-git` finds it. To add others, list
them in `[discover] extend_globs`:

```toml
[discover]
extend_globs = ["GEMINI.md", "**/GEMINI.md", ".github/copilot-instructions.md"]
```

- `extend_globs` adds to the default list; `globs` replaces it. `extend_globs` from `extends` files add up.
- With `preset:strict`, R5a compares files of different names too, so a `GEMINI.md` that copies the
  `AGENTS.md` next to it is reported line by line. The default compares only same-name files.

### Skills

`SKILL.md` files (`**/SKILL.md`) are checked by the S rules only; no R or C rule runs on them. Claude
Code and the Agent Skills specification read them differently: Claude Code ignores fields it does not
know and accepts a `name` that differs from the directory, while claude.ai upload and the Skills API
reject any key outside the specification's six. The default checks for Claude Code; if you also upload
your skills, add the checks for the second reader:

```toml
extends = ["preset:agentskills"]   # with preset:strict too: ["preset:strict", "preset:agentskills"]

[rules.S3]
max_chars = 1536                   # Claude Code's default skillListingMaxDescChars; match yours
```

`[discover] skill_globs` replaces the `SKILL.md` glob list and `extend_skill_globs` adds to it, as
`globs` and `extend_globs` do for instruction files. Details: [`docs/rules.md`](docs/rules.md#s1-to-s12-skillmd).

### Hooks and MCP settings

Claude Code settings files (`**/.claude/settings.json` and `**/.claude/settings.local.json`; the local
one is usually git-ignored, so only `--no-git` reaches it) are
checked by the H rules and the root `.mcp.json` by the M rules: that each is valid JSON, that hooks use
documented event names and handler types with their required fields, that a command hook has a
command, and that each MCP server has a known `type` and its `command` or `url`. These are the cases in
which Claude Code skips the file or the entry, often with no sign during a session. Optional fields
and other settings keys are not checked. `hooks_globs`/`extend_hooks_globs` and
`mcp_globs`/`extend_mcp_globs` in `[discover]` change the file lists. Details:
[`docs/rules.md`](docs/rules.md#h1-to-h6-hooks).

### Compared with similar tools

From each tool's own documentation, checked 2026-11-03; nothing here was installed or run. "Not
documented" means the documentation does not say, not that the feature is missing.

| | agentfile-lint | [agnix](https://github.com/agent-sh/agnix) | [ctxlint](https://github.com/YawLabs/ctxlint) | [agentlinter](https://github.com/seojoonkim/agentlinter) |
|---|---|---|---|---|
| Runs on | Python 3.11+, nothing to install (standard library plus a vendored copy of PyYAML) | Rust binary (npm, brew, pip, cargo) | Node (`npx`), no runtime dependencies | Node 18+ (`npx`) |
| Files | `AGENTS.md`, `CLAUDE.md`, `.claude/rules/`, `SKILL.md`, hooks, MCP; others by glob | `CLAUDE.md`, `AGENTS.md`, `SKILL.md`, hooks, MCP, Cursor, Copilot, more | context files of 16 tools, MCP config | `CLAUDE.md`, `AGENTS.md`, `SKILL.md`, Cursor, Copilot, more |
| Shared config | `extends` presets and files | `extend` base files | not documented | `extends` of the built-in preset |
| Exceptions | allowlist entries need a reason and an expiry date, expired or unneeded entries fail; path overrides need a reason and raise a level only with `raise = true`; per-line directives need a reason, unused ones warn | disabled rules, per-file overrides, inline comments | ignored rules with an optional reason; unused ones reported | ignored paths |
| Vendored copy | reproducible directory with a hash check | not documented | not documented | not documented |
| References checked | test names, `§N` spec sections; paths with `preset:strict` | import paths, commands, referenced files | paths, commands (against `package.json`, `Makefile`) | file references, imports |
| Duplicates between files | identical lines in a file and its ancestors | not documented | duplicate content across files | duplicate content; across files not documented |
| Auto-fix | allowlist entries and per-line directives only (`--fix`, `--diff`) | yes | broken paths | yes |
| Editor | no | LSP, IDE plugins | LSP | no |
| Output | `file:line: severity: rule-id: message`, JSON, GitHub, SARIF; exit 0/1/2 | GitHub, JSON, SARIF | text, JSON, SARIF; exit 0/1/2 | GitHub; 0-100 score |

Choose agnix for breadth (many file types, IDE plugins, auto-fix). Choose agentfile-lint to run one
small, pinned set of rules across many repositories: debt exceptions expire and permanent ones are
written down with a reason, the checker can be vendored
and verified, and the output and exit codes are a tested contract.

## Usage

```sh
python3 -m agentfile_lint            # from a git repository; analyzes tracked files only
agentfile-lint --no-git              # walk the current directory instead (no git needed)
agentfile-lint --list-rules          # rules and their effective levels
agentfile-lint --today 2026-01-31    # replace the current date (reproducible runs)
agentfile-lint --config path.toml    # explicit config instead of .agentfile-lint.toml
agentfile-lint --warn-as-error
agentfile-lint --format json         # or github (workflow commands) or sarif; default text
agentfile-lint --fix                 # apply safe fixes, then report what is left
agentfile-lint --diff                # print those fixes as a diff instead; add --unsafe-fixes for the rest
```

Fixes only touch what the tool asked you to write: an unused per-line directive is removed, an
allowlist entry's `count` is lowered to the findings left, and an entry whose file no longer violates
its rule is removed (only in the config file the run loads, never in one it extends). They never
edit instruction content and never widen an exception. Removing only some ids of a directive is
unsafe (its reason may be about them) and needs `--unsafe-fixes`. Before writing, `--fix` checks that
each TOML edit changes nothing but its target and that the edited files suppress no finding the
original did not; otherwise it leaves the file and the message stays as a suggestion. Exit codes
mean what they always do (`--diff` reports the findings as they are). The pre-commit hook does not
pass `--fix`; if you add it, it also edits files you have not staged.

Other commands:

```sh
agentfile-lint check-pins            # (experimental) every reference to this tool pins the same full commit SHA
agentfile-lint config --format json  # the effective merged configuration, sorted keys
agentfile-lint vendor --to DIR       # a pinned, self-contained copy (see below)
```

Experimental commands may change their output and options in any minor release; everything else
follows [`docs/versioning.md`](docs/versioning.md).

Findings go to stdout, one line each: `file:line: severity: rule-id: message`, where `severity` is
`error` or `warning`; a finding about a whole file has no line: `file: severity: rule-id: message`.
`--format json` prints one document, `{"version": 1, "findings": [...]}`, each finding with `file`,
`line` (`null` for a whole file), `level`, `rule`, `message` and `fix` (`null` or its edits); `--format github` prints GitHub
workflow commands; `--format sarif` prints one SARIF 2.1.0 log for code scanning, with `fixes`. Usage and configuration problems, and the `--fix` summary, go to stderr. Exit codes: `0` no errors, `1` at
least one error, `2` usage or configuration problem.

Files given on the command line are ignored; the full tracked set is always analyzed
(cross-file checks and allowlist checks need it). A `*.local.md` file is analyzed only through a glob
that names it, such as the default `**/CLAUDE.local.md`; `**/*.md` does not find `NOTES.local.md`. `--no-git` analyzes every file under the current directory
instead, with the same globs; it skips `.git`, `node_modules`, virtual environments and tool caches by
a fixed list and does not read `.gitignore`.

## Configuration

`.agentfile-lint.toml` at the repository root is applied on top of the default preset, and each
`extends` entry (a shipped preset or a path) is applied in order before it, each one changing only the
keys it sets. Unknown keys fail.

```toml
extends = ["preset:strict"]         # optional; other entries are paths relative to this file

[discover]
globs = ["AGENTS.md", "**/AGENTS.md"]

[shared.size]                       # parameters R1a, R1b and R1d share
excluded_blocks = [{ begin = "<!-- BEGIN:x -->", end = "<!-- END:x -->" }]

[rules.R1d]
level = "error"                     # error | warn | off; each rule id has one level
max_chars = 500                     # required unless R1d is off

# First matching glob wins; a file matching no entry has no limit.
[[rules.R1a.limits]]
glob = "AGENTS.md"
max_bytes = 12000

[[rules.R1a.limits]]
glob = "**/AGENTS.md"
max_bytes = 6000

[allowlist]
max_days = 90

[[allowlist.entries]]
rule = "R1a"
path = "docs/AGENTS.md"
count = 1  # findings of R1a in that file; more or fewer fail
reason = "split planned in the tracker"
expires = 2026-12-31

# Permanent path scope: translated copies duplicate the root file on purpose.
[[overrides]]
paths = ["docs/*/AGENTS.md"]
rules = { ancestor-duplicates = "off" }  # rule id or alias -> "warn" or "off"
reason = "translations of the root AGENTS.md"

# Raising takes `raise = true`: here R5b, off by default, is a warning under services/.
[[overrides]]
paths = ["services/**"]
rules = { R5b = "warn" }                 # with raise = true: "error" or "warn"
raise = true
reason = "service guides must not copy each other"
```

The allowlist is for debt with an end date; `[[overrides]]` is for paths that are meant to differ.
An override only lowers a rule's level unless it says `raise = true`; when entries that lower and
entries that raise both match a file, lowering wins. Entries from `extends` are added to the
repository's own; `[[overrides]] unset = ["docs/**"]` (with a `reason`) removes an inherited glob. A
glob that matches no instruction file is a warning on the config file that wrote it.

A single line can be exempted in the file itself, with the rule ids and a required reason:

```markdown
<!-- agentfile-lint-disable-next-line R5a -- the tool reads this file alone -->
Run make check before every push.
```

It covers the next line only and not the whole-file rules (`R1a`, `R1b`, `R1c`, `R1e`, `C1`); a directive that
suppresses nothing is a warning, a malformed one an error.

## Install and wire up

Every way to run it needs Python 3.11 or newer. To run it without installing, use `uvx` as above. To
install the `agentfile-lint` command for your user, in its own environment:

```sh
pipx install agentfile-lint                          # or agentfile-lint==<version> to pin
pipx install --python python3.12 agentfile-lint      # when the default python3 is older than 3.11
pipx upgrade agentfile-lint
```

pre-commit, in `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/Will413028/agentfile-lint
    rev: <tag or full commit SHA>
    hooks:
      - id: agentfile-lint
        # language_version: python3.12   # when pre-commit's default Python is older than 3.11
```

```sh
pre-commit install                     # run the hook on every commit
pre-commit run agentfile-lint          # run it once now
pre-commit autoupdate --freeze --repo https://github.com/Will413028/agentfile-lint   # newest tag, as a full SHA
```

`autoupdate` finds 0.9.0 and later; before 0.9.0 it picked 0.4.0, so set `rev:` by hand when moving
to a version older than 0.9.0.

Run on every commit and push: rules R3a, R3b and R3c read test files, source and docs, and cross-file
rules read the whole tracked set, so do not filter the hook, lefthook entry or workflow by instruction
files (no `files:`, `glob:` or `paths:` filters). The pre-commit hook sets `always_run: true`.

lefthook (no path filter):

```yaml
pre-commit:
  commands:
    agentfile-lint:
      run: python3 -m agentfile_lint
```

GitHub Actions (pin to a full commit SHA; no `paths:` filter, plus a weekly run so allowlist expiry
warnings appear even when nobody commits):

```yaml
on:
  push:
  pull_request:
  schedule:
    - cron: "0 6 * * 1"   # weekly

# steps:
- uses: actions/checkout@<sha>
- uses: Will413028/agentfile-lint@<sha>
```

The action runs with `--format github`, so findings appear as annotations on the pull request. GitHub
shows at most 10 errors and 10 warnings per step; the others stay in the log with their file and line.
When the repository is checked out to a subdirectory, set `working-directory: <dir>`; `config` is then
relative to it, and annotations still point at the right file.

Code scanning: the action does not upload anything. To see findings as code scanning alerts, write
SARIF and upload it yourself (the upload needs `security-events: write`):

```yaml
permissions:
  contents: read
  security-events: write
# steps:
- uses: actions/checkout@<sha>
- uses: actions/setup-python@<sha>
  with:
    python-version: "3.12"
- run: python -m pip install agentfile-lint==<version>
- run: agentfile-lint --format sarif > agentfile-lint.sarif || [ $? -eq 1 ]   # findings still upload
- uses: github/codeql-action/upload-sarif@9b3254085494b55a0f7c4c2b3d2d52cc712ce370 # v4.39.1
  with:
    sarif_file: agentfile-lint.sarif
    category: agentfile-lint
```

`R2` and `R3c` need configuration to check anything (section lists, spec mappings); the preset
documents every key. A rule at `error` can still emit some findings as warnings.
The review criteria for what no program can decide are in `rubric.md`, with a pull request snippet in
`docs/pr-template-snippet.md`; the release and upgrade process is in `docs/versioning.md`.

Development: `make check` runs the unit tests (needs Python 3.11+, override with `PYTHON=...`).
Design notes are in `docs/design.md`, decisions in `docs/adr/`.

## Vendored copy

For environments that cannot install from git, `agentfile-lint vendor --to <dir>` writes one
self-contained directory: the runner package with the default preset, an entry script
(`agentfile-lint.py`), `verify.py` and a `README.md` that records the upstream tag, the upstream
commit and a SHA-256 for every file. Options: `--ref-tag` / `--ref-commit` (default: the exact tag
and HEAD of the source checkout, else `untagged`), `--force` (replace a non-empty target).

- Run it from the repository root: `python3 <dir>/agentfile-lint.py` (Python >= 3.11, standard
  library only, no network). Its output and exit codes equal `python3 -m agentfile_lint`.
- The output is reproducible: same source and same two upstream values give a byte-identical tree
  (sorted order, fixed newlines, no timestamps, no machine paths or user names).
- `python3 <dir>/verify.py` recomputes the hashes and fails (exit 1, naming the file) on a
  modified, missing or unlisted file.
- `vendor` and `verify.py` are part of the compatibility contract (`docs/versioning.md`).

Known limitation: verification only detects accidental modification. A deliberate change can edit
the files and the manifest together, so it is not tamper-proof. The real gate is review of the
diff of the pull request that upgrades the vendored copy.

## License

MIT, see `LICENSE`.
