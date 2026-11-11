# Design

## Problem

Agent instruction files are loaded whole whenever an agent works in their directory, so they
need budgets, and they rot: duplicated text, stale references, one-off exceptions that nobody
decided to keep. A review checklist does not hold. A deterministic check that runs in the same way
locally and in CI does.

## Goals

- One rule file (TOML) plus a thin Python runner; nothing to install at run time. The only
  third-party code is PyYAML's pure-Python part, vendored unchanged in `agentfile_lint/_yaml/` for
  frontmatter and used only through `frontmatter.py` with `SafeLoader` (docs/adr/0007).
- The local hook and CI run the same program, the same rules, the same version.
- Three levels per rule: `error` (blocks), `warn` (prints), `off`.
- Debt exceptions are time-boxed: every allowlist entry has a reason and an expiry date, and the
  list can only shrink. Permanent path scopes (`[[overrides]]`) live in the config with a required
  reason and can only lower a level.
- Reproducible: same input and same injected date give the same output. No network, no telemetry.

## Non-goals

- No LLM in the gate (non-deterministic, paid, and the checked text is untrusted input).
- Not a Markdown style linter; it knows instruction-file semantics (tiers, budgets), not prose style.
- Local instruction files (`*.local.md`) are found only through a glob that names them; CI usually
  cannot see them, since they are rarely tracked (File discovery).
- No distribution channel the runner depends on. It ships as a git repository (pre-commit hook,
  composite action), a PyPI package (`uvx agentfile-lint`) and a pinned vendored copy for restricted
  environments (see Vendored copy); consumers pin a version or a full commit SHA.

## Model

```
preset (shipped) <- repo config (.agentfile-lint.toml, `extends`) -> effective config
effective config + git ls-files or the --no-git walk (full set) -> rules -> findings -> overrides -> per-line directives -> allowlist -> output + exit code
with --fix or --diff: findings with fixes -> edits in memory -> the same run on the edited texts (safety net 2) -> written (--fix) or printed (--diff)
```

The checker only reads files; `--fix` is the one way it writes to a checked repository (Fixes), and
the `vendor` subcommand writes its copy.

- Rules are data: a rule module reads parameters, and repo-specific behaviour is never a
  branch in code. Differences between repositories are config values.
- One rule id is one check with one level. A module may report several ids (R1a to R1e, R4a and R4b,
  R5a and R5b) from one computation; parameters those ids share live in `[shared.<group>]`, the rest
  in `[rules.<id>]` (docs/adr/0005).
- Layers: `preset:default` is applied once, first, under the file the run loads (or alone when there
  is none). Every other file, a shipped preset such as `preset:strict` or a shared file named in
  `extends`, is a change on top: it holds only the keys it sets, and naming `preset:default` in it
  has no further effect. A file's `extends` entries apply in order, then the file itself, so a later
  entry wins over an earlier one only on the keys it sets (docs/adr/0008).
- Merge: tables merge key by key (the child wins); every other value, lists included, is replaced.
  Two lists concatenate along the `extends` chain instead, parents first: `[[overrides]]`, because
  replacing them would silently drop the overrides of the config a file extends (a child removes an
  inherited glob with an `unset` entry, see Overrides), and the `discover.extend_*` lists
  (`extend_globs`, `extend_skill_globs`, `extend_hooks_globs`, `extend_mcp_globs`), each of which adds
  to its family's glob list the way ruff's `extend-select` adds to `select` (a child that replaces
  `globs` keeps every inherited `extend_globs`). The shipped presets carry no overrides: a path scope belongs to one
  repository's layout.
- Unknown keys, unknown rule ids and malformed allowlist entries fail the configuration (exit 2).
  A typo must not silently disable a check.

## File discovery

Files are `git ls-files` entries matching `discover.globs` (default `AGENTS.md`, `**/AGENTS.md`,
`CLAUDE.md`, `**/CLAUDE.md`, `**/CLAUDE.local.md`, `**/.claude/rules/**/*.md`) or `discover.extend_globs`
(default none), skipping files deleted in the working tree. A file ending in `.local.md` is personal
and usually untracked: only a glob that itself ends in `.local.md` finds it (`**/CLAUDE.local.md`, which
Claude Code loads beside CLAUDE.md), never a wider one such as `**/*.md`. Override paths, R5 exclusions
and the other path filters are plain globs and match it like any file. Two discovered paths in the same directory that are the same file (for example
`CLAUDE.md -> AGENTS.md`) are one file under two names, each loaded by a different agent: only the
non-symlink path is analyzed (the first in sort order when all are symlinks), so no rule reports the
same text twice. The same file in another
directory is a separate load location and is analyzed on its own; when it sits in an ancestor or
descendant directory, an agent working there loads both, and R5a reports the repeated lines. A
symlink to a file outside the discovered set is analyzed as its own file; a dangling one is skipped.

`--no-git` replaces `git ls-files` with a walk of the current directory, which becomes the root
(config lookup, reported paths); every walked file is what rules see as tracked. The walk never enters
`.git`, `.hg`, `.svn`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.tox`, `.mypy_cache`,
`.pytest_cache`, `.ruff_cache`, `.cache`, `.direnv`, `.gradle`, `.next` or `.terraform` at any depth, does not follow directory symlinks, and does not read
`.gitignore` (docs/adr/0006). Without the flag, running outside a git repository is still exit 2: the
scan never switches scope on its own.
### File families

Each rule module checks one family of files, and each family has its own glob lists (docs/adr/0009):

| Family | Globs | Default | Rules |
|---|---|---|---|
| instruction | `discover.globs`, `discover.extend_globs` | `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md` at any depth, `.md` under `.claude/rules/` | R1a to R6, C1 |
| skill | `discover.skill_globs`, `discover.extend_skill_globs` | `**/SKILL.md` | S1 to S12 |
| hooks | `discover.hooks_globs`, `discover.extend_hooks_globs` | `**/.claude/settings.json`, `**/.claude/settings.local.json` | H1 to H6 |
| mcp | `discover.mcp_globs`, `discover.extend_mcp_globs` | `.mcp.json` (root only) | M1 to M4 |

Rules of one family never see the files of another: R2 to R6 do not run on `SKILL.md`, and R5a does
not compare a `SKILL.md` with the `AGENTS.md` above it (one is loaded on demand, the other whenever an
agent works in the directory). A file both lists match is in both families. The `.local.md` exclusion,
the deleted-file skip, `--no-git`, the same-directory alias rule above and the E0 check apply to
every family. Per-line directives are read from instruction files only:
text in a `SKILL.md` body is skill content, and its frontmatter cannot hold an HTML comment, and JSON
has no comments, so S, H and M ids cannot be named in a directive (an allowlist entry or an override
covers them). An empty glob list turns its family off, except `globs`, which must stay non-empty.

Which S ids run is their level only. The default preset turns on the ids for Claude Code;
`preset:agentskills` adds the ids for claude.ai upload and the Skills API (docs/rules.md, S1 to S12;
docs/adr/0007). An empty `skill_globs` turns the skill family off (`globs` must stay non-empty).

File names given on the command line are not used to narrow the analysis: cross-file rules and the
allowlist "no longer needed" check need the whole set, and a partial view would make them pass locally
and fail in CI. They only decide whether to run at all: a run goes ahead when a name matches any
family's globs or is the config file. Hooks therefore use `pass_filenames: false`.

Trigger scope: R3a, R3b and R3c depend on test files, source and docs, not only on instruction files,
so a hook or workflow must not filter by instruction-file paths. The pre-commit hook sets
`always_run: true` and has no `files:`; lefthook and CI examples carry no path filters. Run on every
commit and push; cross-file rules read the whole tracked set. Add a weekly `schedule` in CI so allowlist
expiry warnings appear without commits.

## Rules R1a to R1e: size

Size is five rules, each with one level (docs/adr/0005): `R1a` per-file bytes (`file-bytes`), `R1b`
per-file lines (`file-lines`), `R1c` combined bytes on a path (`path-bytes`), `R1d` line length
(`line-length`) and `R1e` per-file characters (`file-chars`). They share `[shared.size]`; each `[rules.<id>]` holds its level and its own keys.

- `R1a.limits` (`{glob, max_bytes}`) and `R1b.limits` (`{glob, max_lines}`): ordered lists; the first
  entry whose glob matches the path applies, and a file that matches no entry has no limit. Globs use
  the matcher of R2 shapes and R3c specs: `*` and `?` never cross `/`, `**/` matches zero or more
  directories. Depth tiers are written as globs: `AGENTS.md`, `*/AGENTS.md`, `**/AGENTS.md`.
- `R1c.limits`: `{glob, max_bytes}` entries for the combined size of a file and the files matching the
  same glob in its strict ancestor directories; every entry applies (unlike R1a and R1b).
  Sizes are the bytes on disk, as the agent reads them: `excluded_blocks` and CRLF are not discounted.
  The finding is on the file where the total first exceeds the limit; files below it are not reported
  again, and a single file over the limit is reported the same way. The glob is meant to match one file
  per directory (`**/AGENTS.md`); Codex also loads `AGENTS.override.md` or fallback names instead of
  AGENTS.md, which the default does not model (revisit when an issue reports such a repository).
- `R1d.max_chars`: per-line limit in characters, required when R1d is not `off`.
- `R1e.limits` (`{glob, max_chars, frontmatter_key}`, `glob` required): ordered like R1a, first match
  wins. An entry without `max_chars` sets no limit for the files it matches; an entry with
  `frontmatter_key` matches only a file whose frontmatter parses (`frontmatter.py`) and has that
  top-level key, so a later entry may apply instead. The count is Claude Code's for its per-file limit:
  code points of the text on disk (a CR counts) without the frontmatter and block-level HTML comments,
  trimmed with JavaScript's whitespace set (docs/rules.md, R1e).
- Default preset: only limits an agent's documentation states. R1c at `error`: AGENTS.md files on one
  path that total over 32768 bytes; Codex reads AGENTS.md from the root down to the working directory
  and stops adding files at 32 KiB in total (`project_doc_max_bytes`,
  https://learn.chatgpt.com/docs/agent-configuration/agents-md). R1b at `warn`: `**/AGENTS.md` and
  `**/CLAUDE.md` over 200 lines; Claude Code asks for fewer than 200 lines per CLAUDE.md file and reads
  AGENTS.md when there is no CLAUDE.md (https://code.claude.com/docs/en/memory). R1e at `warn`: a
  file Claude Code loads on demand (CLAUDE.md and CLAUDE.local.md in a subdirectory, a subdirectory's
  `.claude/rules/`, path-scoped rules in the root `.claude/rules/`) over 40,000 characters, where it
  gives Claude only the start of the file with a 200K context; the limit grows with a 1M context, so
  a warning. R1a at `error` with no limits, R1d `off`. Every default error must point to such a hard limit
  (docs/adr/0003).
- Old ids, aliases and keys (`R1`, `size`, `bytes_level`, `lines_level`, `path_limits`,
  `max_line_chars`, the old `max_bytes` tier table) fail the configuration with a message naming what
  replaces them.
- `[shared.size] excluded_blocks`: marker pairs; the text from a begin marker through the end marker
  (and one trailing LF, CRLF or CR) does not count toward R1a, R1b or R1d (a line wholly inside a block
  is never reported). It does not apply to R1c or R1e. The split is deliberate: a single-file limit is the
  author's budget, and a block a tool writes into the file is not the author's; R1c models what the
  agent actually reads, block included.
- Exact semantics: the engine reads each file once as bytes; R1a to R1e see the text without newline
  translation, so bytes are the bytes on disk (a CRLF counts two) minus the blocks' raw bytes, the same
  unit R1c uses; lines are counted on the text outside the blocks; line length is in characters; a
  limit is exceeded when `measured > limit` (equal passes); a finding's line number is the line on
  disk, where an annotation points. Other rules see the text with newlines normalized.
- One line definition for every rule: only LF, CRLF and a lone CR end a line (`rules/_text.py`
  `split_lines`), as `grep -n` and editors count them. Form feed, U+2028 and the other breaks
  `str.splitlines` knows are characters inside a line, for R1b's count and for every reported line
  number. A contract test
  compares R1a to R1d with the checker they replaced and lists the deliberate differences (CRLF bytes,
  line numbers after a block; docs/adr/0004).

## Rules R2 to R6 and C1

The default preset runs only objective checks: R2, R3a, R3c and R5a (same-name ancestor pairs) at
`warn`; R3b, R4a, R4b, R5b and R6 guess and C1 checks a convention, so they are `off` and
`preset:strict` turns them on at `warn`, with R5a and R5b on any pair (docs/adr/0003). New rules enter at `warn` (see Versioning);
the severity named below is what a repository gets with `level = "error"`. Each rule reads its parameters from the config, and the
preset documents every key. Cross-file rules (`check_repo`) always see the full tracked set.
Fenced code blocks and HTML comments are ignored by every text rule.

- R2 shape: per glob (first match wins), `sections` must be the file's headings of `heading_level`,
  `exact` (no others, in order) or `ordered` (extras allowed). Optional `title` (starts with a level-1
  heading), `purpose` (a one-line paragraph after it), `bullets_only` (sections that hold only list
  items) and `must_match` (regexes that must match the file). Empty `shapes` means inactive.
- R3a test names: a backticked token that fully matches a `test_defs[].name` regex must be defined in a
  tracked file matching `files`, found with the `definition` template (`{name}` is the placeholder).
  A language with no matching tracked file is skipped. Presets: Go `func TestX(`, Python `def test_x(`.
- R3b path references (heuristic, `warn` by design): a backticked path-like token is tried against the
  file's directory and every ancestor, the repo root, the `base_dirs` (entries may contain `*`), each
  also under `source_roots` and with `resolve_extensions`. Existence means a tracked file or the
  directory of one. Skipped: spaces and `<>*{}$=|()[]?`, URLs, `@`/`~`/`-`/`/` prefixes, matches of
  `ignore_patterns`, lines with an `ignore_negated_words` word, and bare file names unless
  `check_bare_names`. On twelve popular public repositories with no config, 18 of the 19 sampled
  findings that could be judged were false positives (external or placeholder paths, paths relative to each
  package), so it is `off` by default and `warn` in `preset:strict`.
- R3c spec references: `specs` maps instruction files to a spec document (`{1}` is what the glob's first
  `*` matched); each `ref_pattern` match must match a numbered heading (`heading_pattern`; a heading
  2.1 also makes section 2 valid). Skipped: references qualified by an ASCII word other than
  `plain_words` (`other-doc §3`) and text matched by `ignore_before`. Empty `specs` means inactive.
- R4a dated references (`dated-refs`): dates (ISO, `date_patterns`) and issue references
  (`issue_patterns`). R4b narrative words (`narrative-words`): `narrative_words`. A match inside a
  token that has a path separator, a file extension or a date-prefixed slug is a name, not a date
  (`ignore_token_patterns`, R4a).
- R5a and R5b duplicates (`ancestor-duplicates`, `sibling-duplicates`): lines of at least `min_chars`
  characters, compared after collapsing whitespace and removing a list marker; headings and table
  rules are skipped. Both read `[shared.duplicates]` (`ancestor_pairs`, `min_chars`,
  `ignore_headings`, `ignore_patterns`). The same line in a file and in an ancestor file is R5a,
  reported on the descendant. `ancestor_pairs = "same-name"` (default) counts only a file with the same
  name in a strict ancestor directory, the pair one agent loads together (Codex reads AGENTS.md from
  the root down to the working directory, Claude Code CLAUDE.md from the working directory up); `any`
  (strict) also counts different names and two files in one directory. Every other pair is R5b
  (default `off`, strict `warn`). Files are grouped once: a line that matches an ancestor is not also
  reported as a sibling duplicate, even with R5a `off`. Exact matches only. Always the full set (a
  partial view would pass locally and fail in CI).
- R6 constants: candidate patterns for values copied from code; findings are always warnings.
- C1 CLAUDE.md: any tracked file named `CLAUDE.md`, whatever `discover.globs` says. `import-only`:
  exactly one non-blank line, `import_line`, and an AGENTS.md next to it; a symlink to that AGENTS.md
  counts as the import. `forbid`: must not exist (a symlink included).

Each rule id has one level, and every finding of that id is reported at it (docs/adr/0005); R6 is
the exception, its findings are always warnings.

## Overrides

Each entry: `paths` (globs), `rules` (rule id or alias -> level), `reason`, optional `raise`
(docs/adr/0004, docs/adr/0006).

- An override changes levels only, never rule parameters. Without `raise` it only lowers (`warn` or
  `off`; `error` fails the configuration). With `raise = true` it only raises (`error` or `warn`; `off`
  fails), from `off` too: the rule then runs, and its findings on the other files stay at the rule level
  (dropped when that is `off`). For one file and one rule: when a lowering entry matches, the lowest of
  the rule level and the matching lowering entries applies, whatever raising entries match (lowering
  wins); otherwise the highest of the rule level and the matching raising entries. Entry order does not
  matter. `E0`, `allowlist` and `disable` cannot be overridden.
- An entry `{ unset = [globs], reason }` (no other keys) removes those globs from the overrides the
  file inherits through `extends`; an inherited entry left with no glob is dropped. A glob that is in no
  inherited entry fails the configuration. It does not touch the file's own entries. When one config
  is inherited through two `extends` branches, a glob stays while any branch still inherits it.
- It applies to the findings reported on the files it matches; those files stay in the input of
  cross-file rules (R1c still counts them, R5a and R5b still compare them), so a finding on a file
  outside the paths is still reported.
- Overrides run before the allowlist: an allowlist entry for a finding an override drops is no longer
  needed.
- Each glob of an entry (after `unset`) must match an analyzed file of any family; otherwise a warning
  (rule `allowlist`, whole file, on the config file that wrote the entry: repo-relative inside the
  repository, as given outside it, naming `overrides[i]` by its index in that file). An entry reached
  through `extends` says `(inherited through extends)` and points at `unset`: a shared config serves
  repositories that do not all have every path, and each one removes what it does not have.
- A same-directory alias (a `CLAUDE.md` symlink to `AGENTS.md`) is not analyzed, so an override names
  the target file; a glob that matches only the alias gets the stale warning.

## Allowlist

Each entry: `rule`, `path`, `count`, `reason`, `expires` (docs/adr/0005).

- `count` (required, an integer of at least 1) is the number of findings of that rule in that file the
  entry accepts. With n findings of that rule in that file after overrides:
  - n = count: a live entry suppresses all of them.
  - n > count: none is suppressed, and an error reports that the entry expected `count` and found n.
  - 0 < n < count: all are suppressed, and an error asks to lower `count` to n.
  - n = 0 (the file does not violate the rule, or is not an analyzed file): error, no longer needed.
- Expired (`expires` before today): error, and the findings are not suppressed. An entry that
  expires today is still live.
- Within `warn_days` (default 14) of expiry: warning "expires in N days".
- `max_days` (default 90): an `expires` later than today plus `max_days` fails the configuration.
- `max_entries` (default 10): more entries fail the configuration.
- Renewal means editing the config and writing a new reason.

## Per-line directives

`<!-- agentfile-lint-disable-next-line <ids> -- <reason> -->` drops the findings of the named rules on
the next line of the same file (docs/adr/0006).

- The directive is a line of its own (up to three spaces of indent, as four make an indented code
  block), outside fenced code and HTML comments, which every text rule skips the same way. Any such line
  starting with `<!-- agentfile-lint-disable` is parsed as one.
- One directive per target line: a directive right above another directive is an error, since it would
  cover the directive line; name every rule in the one right above the target.
- `<ids>`: one or more rule ids or aliases, separated by commas or spaces. A reason after ` -- ` is
  required.
- "Next line" counts lines the way every rule does: only LF, CRLF and a lone CR end a line.
- It goes in the file that reports the finding: for R5a and R5b, the file with the repeated line, not
  the ancestor or sibling it repeats.
- Rules whose findings are about the whole file (R1a, R1b, R1c, C1) and rules of other file families
  (S1 to S12) are not accepted; use an allowlist entry or an override.
- The directive is ordinary text for the other rules: it counts toward R1a, R1b, R1c and R1d.
- Directives run after overrides and before the allowlist, so a suppressed finding does not count
  toward an entry's `count`.
- Pseudo rule `disable`: a malformed directive (no id, no reason, an unknown or retired id, a whole-file
  rule, a stacked directive, or a line that starts like a directive but is not one) is an error on the
  directive's line (exit 1; exit 2 stays for configuration errors); a rule a directive names with no finding of it on the next line is a
  warning, also when the rule is off. No level or override changes `disable`.

Because expiry depends on the date, a repository with no commits can turn red. Run CI on a
weekly schedule so warnings appear before that happens.

## Fixes

A finding may carry a fix: edits to file text, marked `safe` or `unsafe` as ruff does (docs/adr/0009). The checker
writes nothing unless asked: `--fix` applies the safe fixes and then reports the findings that are
left, `--unsafe-fixes` (only with `--fix` or `--diff`) adds the unsafe ones, and `--diff` prints the
same edits as a unified diff without writing (split at LF, as `git apply` reads it). Exit codes keep
their meaning (docs/adr/0004): after `--fix` they come from the findings left, with `--diff` from the
findings as they are, and `2` when a file cannot be written. `--fix` and `--diff` exclude each
other, and `--diff` takes no `--format`. The action and the pre-commit hook do not pass `--fix`;
added to a hook, it edits any file it fixes, staged or not, since the full set is always analyzed.

A fix can uncover another (a directive stacked on an unused one suppresses nothing once that one is
gone; a lowered `count` can follow), so, as in ruff, the fixes are applied again to the result until
none is left, at most 10 passes. Two fixes whose deletions overlap (neighbouring entries sharing a
blank line) merge into one deletion; a deletion that reaches the end of the file also takes the
blank lines before it.

Fixes edit only what the tool asked the user to write, never instruction content:

- A directive none of whose rules suppresses anything: the line is removed (safe).
- A directive some of whose rules are still in use: the unused ids are removed and the reason stays
  (unsafe, since the reason may be about a removed id).
- An allowlist entry with n < `count`: `count` becomes n (safe).
- An allowlist entry whose file no longer violates its rule (n = 0 for an analyzed file): the entry is
  removed (safe), unless no rule ran on it (it is not valid UTF-8, `E0`). When removing every
own entry would leave the file with none while a file it extends has entries (they would come back),
the last one stays, with its message as the suggestion.

Not fixed, the message stays the suggestion: n > `count` (a new violation; raising `count` would hide
it, docs/adr/0005), an expired entry (a person fixes the file or renews it with a new reason), and an
entry for a file the run did not analyze (that depends on git tracking, `--no-git` and the globs, not
on the file). A fix never widens what is suppressed.

Only the config file the run loads is edited. `allowlist.entries` is a list, so a file's own list
replaces the inherited one as a whole along `extends`; when the file has none, its entries come from a
file it extends and get no fix. The runner has no TOML writer, so an entry is found by its
`[[allowlist.entries]]` header line (`toml_edit.py`); an inline array, a quoted key or a header
inside a string makes the header count differ from the entry count, and then no entry gets a fix.

Two safety nets, each the only path:

1. A TOML edit is parsed again with `tomllib`; when anything but the target (the entry's `count`,
   or the entry) differs, the finding gets no fix (a multi-line string that fools the line-based
   locator ends here).
2. After each pass of edits, the run is repeated on the edited texts in memory. The findings it suppresses (by
   directive or allowlist entry, compared by file, line moved by the edits, and rule) must be among
   those suppressed before, and the effective allowlist entries must be among those before with no
   higher `count`; otherwise nothing is written and stderr names the findings or entries (lines as
   numbered on disk). Removing an unused directive can turn a directive stacked on it into one that
   suppresses the next line.

Edits are applied to the texts the run read, and keep line endings and every other byte. Every file
to edit must be writable before the first is written, so a run writes all of them or none. `--fix`
writes a short summary to stderr (how many fixes it applied in how many files, fixes it skipped,
unsafe fixes left), so stdout stays findings only.
Positions in JSON and SARIF are 1-based lines and columns, columns in Unicode code points, the end
exclusive.

## Output and exit codes

Every finding goes to stdout, sorted by file, line, rule (docs/adr/0004).

- Text (default): `file:line: severity: rule-id: message`, one finding per line. `severity` is
  `error` or `warning` (configs say `warn`). A finding about the whole file drops the line field:
  `file: severity: rule-id: message`. (GNU has `sourcefile:lineno: message`, and `program: message`
  when no source file is relevant; it has no form for a whole file.)
- `--format json`: one document `{"version": 1, "findings": [...]}`; each finding has `file`, `line`
  (`null` for the whole file), `level` (`error` or `warning`), `rule`, `message` and `fix`: `null`, or
  `{"applicability": "safe" | "unsafe", "description", "edits": [...]}`, each edit with `file`,
  `start` and `end` (`{"line", "column"}`) and the replacement `text` (Fixes). `version` goes up
  only when a field is removed or changes meaning, not when one is added.
- `--format github`: one workflow command per finding, `::error` or `::warning` with `file`, `line`
  (omitted for the whole file; GitHub has no whole-file annotation, and its API then reports
  `start_line` 0) and `title` set to the rule id,
  escaped like `escapeData` and `escapeProperty` in actions/toolkit `packages/core/src/command.ts`.
  The message is the text-format line, so a finding past GitHub's annotation limits (10 errors and 10
  warnings per step, 50 per job) keeps its location in the log. `action.yml` passes this format.
- `--format sarif`: one SARIF 2.1.0 log (the version GitHub code scanning reads): one run, the tool
  driver with a descriptor for every rule and pseudo rule, and one result per finding with `ruleId`,
  `level` (`error` or `warning`), `message.text` and a physical location whose `uri` is the
  percent-encoded relative path; `region.startLine` is omitted for a whole-file finding. A finding
  with a fix has `fixes` (one fix: `description`, and `artifactChanges` with a `deletedRegion` and
  `insertedContent` per edit); SARIF has no applicability, so an unsafe fix says so in its
  description. The run sets `columnKind` to `unicodeCodePoints`. The action does not upload it
  (docs/adr/0006).

The action's `working-directory` input only changes where it runs. Reported paths stay relative to
the git root: the runner passes a relative `file=` through unchanged and GitHub reads it from the
repository root (actions/runner `ActionCommandManager.cs`, `IssueCommandExtension`), and code scanning
reads a relative SARIF `uri` the same way.

The pseudo rule `E0` reports an instruction file that is not valid UTF-8; it is always on, and only an
allowlist entry can exempt a file; the pseudo rule `disable` reports per-line directives (Per-line
directives). Usage and configuration errors go to stderr (configuration
errors as `agentfile-lint: message`; argparse prints its own usage message), and so does the
`--fix` summary. Exit `0`: no errors; `1`: at least one error; `2`: usage or configuration
problem. `--warn-as-error` promotes warnings. The formats and exit codes are part of the
contract; which version part a change to them needs is in `docs/versioning.md`.

## Subcommands

- `agentfile-lint check-pins` (experimental: outside the compatibility contract, mainly for someone
  who maintains many repositories; docs/adr/0004): every reference to this tool (pre-commit `rev:`,
  `uvx --from git+...@<sha>`, `uses: owner/agentfile-lint@<sha>`) must be a full 40-hex SHA and all
  must be equal; findings on stdout as `file:line: error: check-pins: message` with exit 1, the summary
  on stderr. Line scanning, no YAML parser;
  limits are listed in `docs/versioning.md` and the module docstring.
- `agentfile-lint config --format json`: the effective merged configuration (preset, extends,
  repo config, defaults filled in) as JSON with sorted keys, so another program (a test in a language
  without a TOML parser) can read the same values the linter uses. Exit 2 on an invalid config.
- `agentfile-lint vendor`: see Vendored copy. It and the copy's `verify.py` are part of the contract.

## Judgment checks

What a program cannot decide (contradictions, stale claims, ambiguity, whether a line earns its place)
is not in the linter and not in CI: `rubric.md` lists the criteria for a human or an agent reviewer,
and `docs/pr-template-snippet.md` is the pull request prompt that asks for the result.

## Verification strategy

- Unit tests per component (config, discovery, allowlist, CLI).
- Contract test: a frozen snapshot of the legacy checker runs next to the new tool on
  generated git repositories with boundary cases (limit, limit +/- 1 per tier, 500/501
  character lines, multibyte text, marker blocks). Both outputs are normalised to
  `(path, line, kind, measured, limit)` sets and compared together with exit codes. A mismatch
  means one of the two tools is wrong; the normalisation is not adjusted to hide it.
- Rule tests: every rule has passing and violating fixtures in `tests/test_rules.py`, checked by
  mutation (neutralizing the rule must fail its tests); `tests/test_check_pins.py` covers `check-pins`
  and the JSON config; `tests/test_versioning.py` fails when a rule above `warn` is not listed as
  graduated in the changelog.
- The temporary checkout leg also runs every rule at its specified level on the pinned checkout,
  writes the report, and pins the set of error-level hits that were judged by hand.
- Timing test: a full scan of 46 synthetic files finishes in under a second.
- Date-injection test: the same `--today` gives byte-identical output.
- CI matrix: Python 3.11 to 3.13 on Linux and macOS; the repository checks its own instruction
  files through the composite action.

## Vendored copy

For environments that cannot install from git, `agentfile-lint vendor --to <dir>` writes one
self-contained directory: the runner package with the default preset, an entry script
(`agentfile-lint.py`), `verify.py` and a `README.md` that records the upstream tag, the upstream
commit and a SHA-256 for every file. Options: `--ref-tag` / `--ref-commit` (default: the exact tag
and HEAD of the source checkout, else `untagged`), `--force` (replace a non-empty target).

- Run it from the repository root: `python3 <dir>/agentfile-lint.py` (Python >= 3.11, standard
  library plus the vendored PyYAML, no network). Its output and exit codes equal `python3 -m agentfile_lint`.
- The output is reproducible: same source and same two upstream values give a byte-identical tree
  (sorted order, fixed newlines, no timestamps, no machine paths or user names).
- `python3 <dir>/verify.py` recomputes the hashes and fails (exit 1, naming the file) on a
  modified, missing or unlisted file.

Known limitation: verification only detects accidental modification. A deliberate change can edit
the files and the manifest together, so it is not tamper-proof. The real gate is review of the
diff of the pull request that upgrades the vendored copy.

## Versioning

Semantic versions as git tags. New rules enter as `warn`; promoting a rule to `error` is a minor
change with a changelog entry under `Graduated`; renaming or removing a rule id is a major change
from 1.0, and before 1.0 a minor one listed under `Changed (breaking)`.
Consumers pin a full commit SHA with the version in a comment. The process (changelog rules, release,
how consumers upgrade) is in `docs/versioning.md`.
