# Rules

For each rule: why a finding is a problem, where its default comes from, whether it runs by default or
only with `preset:strict`, and how often it was wrong when measured. Every key is documented in
`agentfile_lint/presets/default.toml`; `agentfile-lint --list-rules` prints the effective levels.

Every rule in the table except `allowlist` and `disable` has an id and an alias (the name after the level in
`--list-rules`); `allowlist`, `disable` and `E0` have only their id. The alias works wherever the id does:
`[rules.file-lines]` is `[rules.R1b]`, an allowlist entry may say `rule = "file-lines"`, and an override
may say `rules = { file-lines = "warn" }`. Each config file is resolved on its own before merging, so a
repo's `[rules.file-lines]` overrides a preset's `[rules.R1b]`; one file that names a rule both ways
fails (exit 2). Findings and error messages always print the id.

Fixes (`--fix`, docs/design.md, Fixes): only `allowlist` and `disable` findings carry one; no R, C, S,
H, M or E0 rule fixes anything, since its fix would rewrite instruction content or settings the tool
cannot judge. R5a in particular gets no fix and no suggestion: in a measured sample of 67 R5a findings,
54 were translated copies or examples that deleting the line would break, and telling them apart is a
path heuristic, not an objective check.

Each id is one check with one level (docs/adr/0005). The ids R1, R4 and R5 of 0.6.0 and their aliases
`size`, `rot` and `duplicates` were split in 0.7.0 and fail the configuration with a message naming the
new ids.

| Rule | Alias | Checks | Kind | Default | `preset:strict` |
|---|---|---|---|---|---|
| [R1a](#r1a-to-r1e-size) | `file-bytes` | bytes per file | objective | error, no limit set | same |
| [R1b](#r1a-to-r1e-size) | `file-lines` | lines per file | objective | warn (200 lines) | same |
| [R1c](#r1a-to-r1e-size) | `path-bytes` | combined bytes of the files on a path | objective | error (32 KiB) | same |
| [R1d](#r1a-to-r1e-size) | `line-length` | characters per line | objective | off | off |
| [R1e](#r1a-to-r1e-size) | `file-chars` | characters per file Claude Code loads on demand | objective | warn (40,000 characters) | same |
| [R2](#r2-shape) | `shape` | required headings and file shape | objective, needs config | warn | warn |
| [R3a](#r3a-test-names) | `test-names` | a backticked test name is defined | objective | warn | warn |
| [R3b](#r3b-path-references) | `path-refs` | a backticked path exists | heuristic | off | warn |
| [R3c](#r3c-spec-references) | `spec-refs` | a `§N` reference matches a spec heading | objective, needs config | warn | warn |
| [R4a](#r4a-and-r4b-rot) | `dated-refs` | dates and issue numbers | heuristic | off | warn |
| [R4b](#r4a-and-r4b-rot) | `narrative-words` | narrative words | heuristic | off | warn |
| [R5a](#r5a-and-r5b-duplicates) | `ancestor-duplicates` | lines a file repeats from an ancestor file | objective match, heuristic intent | warn (same-name pairs) | warn (any pair) |
| [R5b](#r5a-and-r5b-duplicates) | `sibling-duplicates` | lines repeated in other files | heuristic | off | warn |
| [R6](#r6-copied-constants) | `constants` | values copied from code | heuristic | off | warn |
| [C1](#c1-claudemd) | `claude-md` | `CLAUDE.md` only imports `AGENTS.md` | convention | off | warn |
| [S1](#s1-to-s12-skillmd) | `skill-yaml` | `SKILL.md` frontmatter is valid YAML and a mapping | objective | warn | same |
| [S2](#s1-to-s12-skillmd) | `skill-lines` | `SKILL.md` has fewer than 500 lines | objective | warn | same |
| [S3](#s1-to-s12-skillmd) | `skill-listing-chars` | `description` plus `when_to_use` fit `max_chars` (1536) | objective | warn | same |
| [S4](#s1-to-s12-skillmd) | `skill-metadata-map` | `metadata` is a map | objective | warn | same |
| [S5](#s1-to-s12-skillmd) | `skill-frontmatter` | `SKILL.md` has frontmatter | objective, for upload (`preset:agentskills`: warn) | off | off |
| [S6](#s1-to-s12-skillmd) | `skill-name-length` | `name` is 1 to 64 characters | objective, for upload (`preset:agentskills`: warn) | off | off |
| [S7](#s1-to-s12-skillmd) | `skill-name-chars` | `name` characters | objective, for upload (`preset:agentskills`: warn) | off | off |
| [S8](#s1-to-s12-skillmd) | `skill-name-dir` | `name` equals the directory name | objective, for upload (`preset:agentskills`: warn) | off | off |
| [S9](#s1-to-s12-skillmd) | `skill-description` | `description` is 1 to 1024 characters | objective, for upload (`preset:agentskills`: warn) | off | off |
| [S10](#s1-to-s12-skillmd) | `skill-compatibility` | `compatibility` is 1 to 500 characters | objective, for upload (`preset:agentskills`: warn) | off | off |
| [S11](#s1-to-s12-skillmd) | `skill-keys` | only the specification's six frontmatter keys | objective, for upload (`preset:agentskills`: warn) | off | off |
| [S12](#s1-to-s12-skillmd) | `skill-name-refused` | no character Claude Code refuses in `name` or the directory name | objective | warn | same |
| [H1](#h1-to-h6-hooks) | `settings-json` | a settings file is valid JSON and an object | objective | warn | same |
| [H2](#h1-to-h6-hooks) | `hooks-event` | hook event names are documented ones | objective | warn | same |
| [H3](#h1-to-h6-hooks) | `hooks-shape` | `hooks`, event lists, matcher groups and handler lists have the documented shape | objective | warn | same |
| [H4](#h1-to-h6-hooks) | `hooks-type` | every hook handler has a documented `type` | objective | warn | same |
| [H5](#h1-to-h6-hooks) | `hooks-required` | every hook handler has its type's required fields | objective | warn | same |
| [H6](#h1-to-h6-hooks) | `hooks-empty-command` | a command hook's `command` is not empty | objective | warn | same |
| [M1](#m1-to-m4-mcpjson) | `mcp-json` | `.mcp.json` is valid JSON and an object | objective | warn | same |
| [M2](#m1-to-m4-mcpjson) | `mcp-servers` | servers sit under an `mcpServers` object | objective | warn | same |
| [M3](#m1-to-m4-mcpjson) | `mcp-type` | every server entry is an object with a documented `type` | objective | warn | same |
| [M4](#m1-to-m4-mcpjson) | `mcp-required` | every server has `command` (stdio) or `url` | objective | warn | same |
| [allowlist](#allowlist) | — | exceptions are current and still needed | objective | error | error |
| [disable](#disable) | — | per-line directives are well formed and still needed | objective | error | error |

## How the rates were measured

A rule runs by default only if its findings are facts, or if on a held-out sample of repositories (not
used to tune it) 9 to 20 labelled findings give a Wilson 95% upper bound on the false-positive rate of
at most 30% (docs/adr/0003). The rates below come from that measurement (2026-11-03):

- Sample: the most-starred public repositories with an `AGENTS.md` or `CLAUDE.md` at the root, in star
  order from `gh search repos "stars:>5000" --sort stars`. The first 12 are the tuning sample, the next
  10 the held-out sample. Each was cloned at a recorded commit and checked with no config.
- Labels: up to 20 findings per rule, drawn at random, each labelled true problem, false positive or
  undecidable by one reviewer with a second reviewer spot-checking. Rate = false / (true + false);
  undecidable findings are listed apart.
- Interval: Wilson score interval, 95%. Findings from one repository are not independent, so every
  interval here is optimistic. Repositories are not named (they did nothing wrong by not using this
  tool's conventions).
- Heuristic rules were labelled on the tuning sample with 0.4.0. Their patterns have not changed since;
  0.5.0 only stops counting a same-directory symlink as a second file, which removed findings that were
  all false positives.

## R1a to R1e size

Why: agents read these files every session, and some stop reading past a limit. Codex reads `AGENTS.md` from the repository root
down to the working directory and stops adding files once their combined size reaches
`project_doc_max_bytes`, 32 KiB by default; text past that is silently not read
([Codex: AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)). Claude Code asks for
fewer than 200 lines per `CLAUDE.md`, because longer files use more context and reduce adherence, and
reads `AGENTS.md` when there is no `CLAUDE.md`
([Claude Code: memory](https://code.claude.com/docs/en/memory)). Claude Code also gives only the start
of a file it loads on demand when the file is over 40,000 characters with a 200K context (150,000 with
a 1M context, 200,000 on Claude Opus 4.6 and Sonnet 4.6), with a note telling Claude to read the rest
with the Read tool, and warns at startup about large files (same page, "Claude ignores the end of my
subdirectory CLAUDE.md", read 2026-11-06).

Default: `AGENTS.md` files on one path that total over 32768 bytes are an error (R1c, reported on the
file where the total first exceeds the limit); `AGENTS.md` and `CLAUDE.md` over 200 lines are a warning
(R1b); a file Claude Code loads on demand over 40,000 characters is a warning (R1e). All three are
limits an agent's documentation states; R1c drops text, R1b is guidance, and R1e's limit depends on
the session's context window, so the smallest one is the default and R1e is a warning. Per-file byte limits (R1a `limits`) and a per-line character limit (R1d `max_chars`) are yours
to add. Each id has its own level, so an allowlist entry for the 200-line warning does not hide the
32 KiB error on the same file. Lines are counted, and every rule's line numbers given, by LF, CRLF and a lone
CR only, as `grep -n` counts them; form feed and U+2028 do not end a line.

R1e, the files and the count:

- Files (`[[rules.R1e.limits]]`, first match wins): the ones the page lists, at their default
  globs: `CLAUDE.md` and `CLAUDE.local.md` in a subdirectory (`*/**/CLAUDE.md`,
  `*/**/CLAUDE.local.md`), rules in a subdirectory's `.claude/rules/` (`*/**/.claude/rules/**/*.md`),
  and path-scoped rules in the root `.claude/rules/` (`.claude/rules/**/*.md` with
  `frontmatter_key = "paths"`: the entry applies only when the frontmatter parses and has a `paths`
  key, whatever its value; Claude Code loads a rule without one, or with frontmatter it cannot parse,
  at launch, so the next entry, `.claude/rules/**/*.md` without `max_chars`, sets no limit for it; the
  two come before `*/**/CLAUDE.md`, which would otherwise match `.claude/rules/x/CLAUDE.md`).
  The root `CLAUDE.md`, `.claude/CLAUDE.md` (an entry with no `max_chars`, which sets no limit) and the
  root `CLAUDE.local.md` load at launch and are given whole up to 4 MiB, so they have no limit. "Root"
  is the repository root, where a session usually starts; a session started in a subdirectory loads
  that directory's files at launch instead. A file must also be an instruction file (`[discover]
  globs`): the default globs include `**/CLAUDE.local.md` and `**/.claude/rules/**/*.md`.
- Count: characters as `wc -m` counts them (code points; a CR is a character, so CRLF counts two),
  after removing the frontmatter (a first line `---` to the next line `---`) and block-level HTML
  comments, then trimming whitespace at both ends, as Claude Code measures the text it loads (its
  code, 2.1.317 and 2.1.319; the page says only `wc -m`, and Claude Code itself counts UTF-16 units, so
  a character outside the Basic Multilingual Plane, such as an emoji, counts one here and two there).
  A comment block is a line that starts, after up to 3 spaces and outside a fenced code block, with
  `<!--`, through the end of the line holding `-->` and the empty lines after it; its comments are
  removed and any other text on those lines stays. An inline comment, one in a code block and an
  unclosed one count. A comment line indented by up to 3 spaces inside a list item is removed here but
  kept by Claude Code, so such a file counts a few characters less; one after a block quote's `>` is
  kept, as by Claude Code. `[shared.size] excluded_blocks` does not apply:
  Claude reads those blocks.
- 1M context: set your own limit, for example `max_chars = 150000` in each entry; the limits list
  replaces the preset's as a whole.
- Not checked: files brought in with `@path` imports (each counts against the limit on its own; R1e
  sees only discovered files), `~/.claude/rules/`, and the combined size of all instruction files,
  which Claude Code warns about at a total the page does not state. A rules file named `*.local.md`
  is found only with `extend_globs = ["**/.claude/rules/**/*.local.md"]` (the `.local.md` rule of
  File discovery), and rules reached through a directory symlink under `.claude/rules/` are not
  found. A subdirectory `CLAUDE.md` that is a symlink to the `AGENTS.md` beside it is analyzed as
  that `AGENTS.md` (one file, two names), which R1e's default does not list; at 40,000 characters it
  is at least 40,000 bytes, so the default R1c reports it as an error. R1b's 200 lines covers
  `AGENTS.md` and `CLAUDE.md` only, not `CLAUDE.local.md` or rules files.

Blind spot: R1e covers only the files above. A root `CLAUDE.md` under 200 lines with long or non-ASCII
lines passes, and the 32 KiB path limit covers only `AGENTS.md`; a byte or character limit for other
files is yours to add with R1a or R1e.

Measured: objective, so no false-positive rate. With no config, 22 public repositories gave 16 errors
in 6 repositories (all combined sizes over 32 KiB; 2 single files were over on their own) and 20
warnings (files over 200 lines). A per-file 32 KiB check would have found 3 files in 2 repositories.
R1e: on the same sample (2026-11-06) the default checks 42 files and the largest is 13,370 characters, so it reports none; the two globs added in 0.9.0 find 7 rules files in 2 repositories, and no other rule reports anything on them.

## R2 shape

Why: when every module's file has the same sections in the same order, an agent (and a reviewer) knows
where to look, and a missing section is visible.

Default: on, but `shapes` is empty, so it checks nothing until a repository lists its shapes.

Measured: not measured; nothing to check with no config.

## R3a test names

Why: a test named as a guard ("keep `test_login_redirects` green") that no longer exists sends the agent
looking for it, and the guard the line promises is gone.

Default: on at `warn`, for Go (`func TestX(` in `*_test.go`) and Python (`def test_x(` in `test_*.py`,
`*_test.py`). A language with no tracked test file is skipped.

Measured: objective, so no false-positive rate. 0 findings on 22 public repositories.

## R3b path references

Why: a path that no longer exists points the agent at the wrong place.

Default: off. Telling a path in this repository from an example, a placeholder, a path in another
repository or a path relative to each package is a guess; `base_dirs`, `source_roots` and
`ignore_patterns` help once you know your layout.

Measured (tuning sample, 0.4.0): 18 of 19 false positives, 95% (Wilson 95%: 75.4% to 99.1%); 1
undecidable. False positives were external or placeholder paths, paths relative to each package, build
output and negated examples ("not `src/__tests__/`").

## R3c spec references

Why: `§3.2` in an instruction file stops pointing anywhere once the spec is renumbered.

Default: on, but `specs` is empty, so it checks nothing until a repository maps instruction files to
their spec document.

Measured: not measured; nothing to check with no config.

## R4a and R4b rot

Why: dates, issue numbers and words like "currently" or "recently" describe history. The file should
state the rule that holds now; history belongs in the changelog or the commit, where it cannot go stale
in front of an agent.

Default: off. Dates and issue numbers (R4a) are also used as citations, and narrative words (R4b) have
ordinary meanings ("used to produce"). `preset:strict` turns both on at `warn`.

Measured (tuning sample, 0.4.0): 16 of 19 false positives, 84% (Wilson 95%: 62.4% to 94.5%); 1
undecidable. Most false positives were issue numbers cited as the source of a rule ("(#1234)"); the true
problems described change history ("PR #1234 moved ...").

## R5a and R5b duplicates

Why: an agent that loads a file and its ancestor reads a duplicated line twice, and the two copies drift
apart (one gets edited, the other does not).

Default: R5a on at `warn`, only for a file and a same-name file in an ancestor directory (`AGENTS.md`
and `sub/AGENTS.md`), the pair one agent loads together (`[shared.duplicates] ancestor_pairs =
"same-name"`). Lines must be at least 40 characters and identical after collapsing whitespace and
dropping list markers; headings are skipped. `preset:strict` also compares different names and files in
one directory (`ancestor_pairs = "any"`) and turns on R5b, sibling files, at `warn`.

Measured, default pairs (held-out sample): 0 of 13 false positives (Wilson 95%: 0% to 22.8%), from two
repositories; one false positive would have failed the 30% bar. Known false-positive class: in the
tuning sample, all 54 same-name findings came from one repository and were deliberate copies
(translations under `docs/<language>/`, `examples/`). Such a repository turns R5a and R5b off for those
paths with `[[overrides]]` (`paths = ["docs/**", "examples/**"]`, `rules = { R5a = "off", R5b = "off" }`).
An override silences the findings on the files it matches: with `preset:strict`, R5b still reports the
original outside those paths, since its finding is on that file. To leave copies out of the comparison
altogether, list them in `[shared.duplicates] exclude` (globs, default none): an excluded file is
neither reported nor used as the ancestor text, so the original is not reported either.

Measured, strict pairs (tuning sample, 0.4.0): 20 of 20 false positives. 11 of them were a file compared
with its own symlink, fixed in 0.5.0; the other 9 were translations, templates and examples, 9 of 9
(Wilson 95%: 70.1% to 100%).

## R6 copied constants

Why: a value copied from code (a limit, a timeout, a retry count) drifts silently when the code changes;
a pointer to the code does not.

Default: off. Findings are always warnings, at any level: they are candidates, not proof.

Measured (tuning sample, 0.4.0): 13 of 17 false positives, 76% (Wilson 95%: 52.7% to 90.4%); 0
undecidable. Most false positives were how to set an environment variable (`NAME=1`) and performance
targets.

## C1 CLAUDE.md

Why: with `CLAUDE.md` containing only `@AGENTS.md` (or being a symlink to it), Claude Code and every
other agent read the same text, kept in one place.

Default: off. It is this tool's convention, not an error: many repositories keep real content in
`CLAUDE.md` on purpose. `mode = "forbid"` requires that there is no `CLAUDE.md` at all.

Measured: not a false-positive rate. On the tuning sample 0.4.0 reported 30 findings, all differences
of convention: a `CLAUDE.md` with its own content, or a `CLAUDE.md` symlinked to `AGENTS.md`, which 0.4.0
did not recognize as the import. 0.5.0 with `preset:strict` reports 26 of them.

## allowlist

Why: a debt exception without an end date becomes permanent without anyone deciding so. Every allowlist
entry has a reason and an expiry date at most `max_days` (90) ahead; an expired entry, or one that no
longer suppresses anything, fails. A path that is meant to differ for good goes in `[[overrides]]`
instead, with a required reason; each glob of an override that matches no analyzed file is
a warning on the config file that wrote it (an inherited one is removed with `unset`), so a stale
override shows up without failing CI unless `--warn-as-error` is given.

Default: on, from your config only; with no entries it reports nothing. Entries warn `warn_days` (14)
before they expire, so run CI on a weekly schedule.

Fix (safe, entries written in the config file the run loads): lower `count` to n; remove an entry
whose file no longer violates its rule. No fix for n > `count`, an expired entry, or an entry for a
file the run did not analyze.

Measured: objective, so no false-positive rate.

## disable

Why: a false positive on one line should be fixable next to that line, but an exception without a
reason or one that no longer applies is as bad as an allowlist entry without them.
`<!-- agentfile-lint-disable-next-line R5a -- reason -->` on a line of its own drops the named rules'
findings on the next line (docs/design.md, Per-line directives). A malformed directive (no id, no
reason, an unknown id or a whole-file rule: `R1a`, `R1b`, `R1c`, `R1e`, `C1`) is an error; a named rule with no
finding on the next line is a warning.

Default: on; with no directives it reports nothing. No level or override changes it.

Fix: a directive whose every rule suppresses nothing is removed (safe); unused ids of a directive
that still suppresses something are removed and the reason stays (unsafe, `--unsafe-fixes`).
Malformed directives get no fix.

Measured: objective, so no false-positive rate.

## S1 to S12 SKILL.md

Why: a `SKILL.md` has two kinds of reader, and they disagree. Claude Code ignores a frontmatter field
it does not know, takes a `name` that differs from the directory (or no `name` at all), and when the
YAML does not parse it still loads the skill, with no fields set, so Claude cannot match the
`description`
([Claude Code skills](https://code.claude.com/docs/en/skills), "Frontmatter reference", "Skill not
triggering"). claude.ai upload, the Skills API and `package_skill.py` follow the
[Agent Skills specification](https://agentskills.io/specification) and fail with a hard error on any
key outside its six (`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`)
(the same page, "Using skill frontmatter outside Claude Code"). So every S id belongs to the readers
it protects, and the default preset turns on the ids for Claude Code:

| Id | Reader (on in) | Finding | Source |
|---|---|---|---|
| S1 | both (default) | the frontmatter is not valid YAML (reported at the parse error's line), has no closing `---`, or is not a mapping | Claude Code: "If the YAML between the markers doesn't parse, the skill still loads with no fields set"; specification: "must contain YAML frontmatter" |
| S2 | both (default) | the file has 500 lines or more (whole file, counted like R1b) | both: "Keep `SKILL.md` under 500 lines" |
| S3 | Claude Code (default) | `description` and `when_to_use` together are more than `max_chars` (default 1536) characters | Claude Code: "the combined `description` and `when_to_use` text is truncated at 1,536 characters in the skill listing" |
| S4 | Claude Code (default) | `metadata` is present and not a map | Claude Code: "drops a value that isn't a map" |
| S5 | upload (`preset:agentskills`) | no frontmatter: the first line is not `---` | specification: "must contain YAML frontmatter" |
| S6 | upload (`preset:agentskills`) | `name` is missing, not a string, empty, or longer than 64 characters | specification: "Must be 1-64 characters" |
| S7 | upload (`preset:agentskills`) | `name` is not lowercase, has a character other than a letter, digit or `-`, starts or ends with `-`, or contains `--` | specification, `name` field |
| S8 | upload (`preset:agentskills`) | `name` differs from the name of the directory that holds the file (not checked for a `SKILL.md` at the repository root, whose directory name depends on the checkout) | specification: "Must match the parent directory name" |
| S9 | upload (`preset:agentskills`) | `description` is missing, not a string, blank, or longer than 1024 characters | specification: "Must be 1-1024 characters" |
| S10 | upload (`preset:agentskills`) | `compatibility` is present and not a string of 1 to 500 characters | specification: "Must be 1-500 characters if provided" |
| S11 | upload (`preset:agentskills`) | a top-level key outside the six | Claude Code, "Using skill frontmatter outside Claude Code" |
| S12 | Claude Code (default) | `name`, or the name of the directory that holds the file, has a character Claude Code refuses: `<` or `>`; a control or format character (zero-width, direction-changing); a private-use or unassigned character; a blank other than a plain space; a space at the start or end or two in a row | Claude Code, "Characters a skill name can't hold": a refused `name` is not shown in the `/` menu and does not invoke the skill; a refused directory name keeps the skill from loading, except in a plugin's `skills/`, where the characters become hyphens |

Default: S1 to S4 and S12 at `warn`, S5 to S11 `off` (Claude Code accepts what they report). A
repository that uploads its skills to claude.ai or the Skills API adds
`extends = ["preset:agentskills"]`, which sets S5 to S11 to `warn` and combines with `preset:strict`
in either order; a single id can also be turned on with its level or a raising override, and an id
for a reader you do not write for can be turned off. `[discover] skill_globs = []` stops discovering
`SKILL.md` files.

Readings:

- YAML is parsed by the vendored PyYAML 6.0.3 (docs/adr/0007), and every scalar is read as its text,
  without YAML 1.1 type resolution: `description: yes` is the string `yes` and `version: 2026-02-30`
  is not an error, as YAML 1.2 parsers read them; `name: 12` is the name `12`, as `skills-ref`'s
  strictyaml reads it (YAML 1.1 and the YAML 1.2 core schema read the number 12). Merge keys (`<<`)
  are applied. A duplicate key is S1, as YAML 1.2 parsers and strictyaml reject it; a mapping key
  that is not a scalar (`[a, b]: 1`) is S1 too, without a claim about Claude Code, since readers
  differ on it. A block-scalar `name` (`name: |`) is read without its final line break. Flow collections (`[a, b]`) are valid YAML, read by both readers, and not
  reported; `skills-ref` rejects them because strictyaml does. An empty frontmatter block is no
  fields, not an error.
- Lengths count Unicode characters (code points) after YAML parsing. S6 to S8 compare `name` after
  stripping surrounding blanks and NFKC normalization.
- S7 follows `skills-ref` rather than the specification's `a-z` example: the specification says
  "unicode lowercase alphanumeric characters (a-z, 0-9)", which reads two ways, and `skills-ref`
  accepts any Unicode lowercase letter or digit (`données` passes).
- S3's limit is `[rules.S3] max_chars`, default 1536, Claude Code's default for its
  `skillListingMaxDescChars` setting; this tool does not read Claude Code settings, so a repository
  that changed the setting sets the same value here.
- S10 also reports an empty string, which the specification excludes and `skills-ref` accepts.
- S12 follows the documented list; which code points count as unassigned follows the Unicode version
  of the Python that runs the check.
- Not checked: the types of `metadata` values (`skills-ref` does not check them and neither reader
  breaks on them); fields only Claude Code reads.

Per-line directives cannot name S ids (docs/design.md, File families); use an allowlist entry or an
override.

Measured: objective, so no false-positive rate. On the 22-repository sample of docs/field-report.md
(1695 `SKILL.md` files, 2026-11-06): with the default preset, S1 reports 1 file, S2
199 files in 8 repositories and S12 none; with `preset:agentskills`, S5 reports 4, S7 30, S8 29, S10 3 and S11 877
files. Compared file by file with `skills-ref` (which fails 929 files), 1435 files get the same
verdict and the same checks; the other 260 all use a flow collection that strictyaml rejects (S1
there, valid YAML here, so those files show only their other findings, mostly S11). R and C findings
on the sample are the same as 0.8.0's.

## H1 to H6 hooks

Why: Claude Code reads hooks from the `hooks` key of its settings files, and a hook it cannot load
does not run, usually without a sign during the session: Claude Code reports it at startup or in
`claude doctor` and goes on without it
([settings](https://code.claude.com/docs/en/settings), "Fix a broken settings file"). Files:
`[discover] hooks_globs`, default `**/.claude/settings.json` and `**/.claude/settings.local.json`
(Claude Code reads `.claude/settings.json` from the directory a session starts in, so a nested project
directory has its own; `settings.local.json` is usually git-ignored and is then reached only with
`--no-git`). `extend_hooks_globs` adds to the list; `hooks_globs = []` turns the family off. Only the H
rules run on these files.

| Id | Finding | Source | What Claude Code does (`claude doctor`, 2.1.318) |
|---|---|---|---|
| H1 | the file is not valid JSON (reported at the error's line), or its top-level value is not an object | settings, "Fix a broken settings file": "invalid JSON" is a Settings Error | does not apply the file ("Invalid or malformed JSON") |
| H2 | a key of `hooks` is not a documented event name (names are case-sensitive) | [hooks reference](https://code.claude.com/docs/en/hooks), "Hook lifecycle": 33 events | ignores that event's hooks ("Unknown hook event … was ignored") |
| H3 | `hooks` is not an object; an event's value is not an array; a matcher group is not an object, has no `hooks` array, or has a `matcher` that is not a string; a handler is not an object | settings reference, `hooks`: "object keyed by hook event; each value is an array of `{ "matcher", "hooks" }` groups" | ignores that level |
| H4 | a handler has no `type`, or one other than `command`, `http`, `mcp_tool`, `prompt`, `agent` | hooks reference, "Common fields": `type` required | ignores the handler |
| H5 | a handler lacks a field its type marks required, or has it as a non-string: `command` (command), `url` (http), `server` and `tool` (mcp_tool), `prompt` (prompt, agent) | hooks reference, "Hook handler fields" tables | ignores the handler |
| H6 | a command hook's `command` is empty or blank | hooks reference, `command`: "Shell command to execute" | loads it without a warning; it runs no program |

Under `PreToolUse` and `PermissionRequest`, an H3 to H5 failure is wider: `claude doctor` says such a
hook "may be what guards the permissions declared beside it, so nothing it sits in is applied until the
entry is fixed or removed", and the message says so. An unknown event (H2) is not checked further.

Readings:

- JSON is read as Claude Code reads it (measured): a leading UTF-8 byte order mark is accepted, an
  empty or blank file is no settings, and `NaN`, `Infinity`, comments and trailing commas are invalid
  (JavaScript's `JSON.parse` rejects them). A file nested too deeply for Python's parser is H1 with a
  message that it was not checked.
- Positions are JSON paths in the form `claude doctor` prints (`hooks.PreToolUse.0.hooks.1`); the line
  is the whole file except for H1's syntax error.
- Not checked: the types of optional fields (`timeout`, `async`, `args`, `if` and the rest; Claude Code
  drops a handler whose optional field has the wrong type, but following every optional field is a
  key table that changes with each Claude Code release), whether an http hook's `url` is a URL Claude
  Code accepts (it ignores the hook when not, an empty `url` included; URL parsing is not a required-field
  check), empty `prompt`, `server` or `tool` (Claude Code loads them), other settings keys, `matcher`
  syntax, and hooks in plugin `hooks/hooks.json`, skill or subagent frontmatter.

Per-line directives cannot name H ids (JSON has no comments); use an allowlist entry or an override.

Keeping current: the event names (H2), handler types (H4) and required fields (H5) are those of the
hooks reference as read on 2026-11-06 (Claude Code 2.1.318), and Claude Code adds events in minor releases. They
are re-read before every minor release of this tool (docs/versioning.md), and a finding on a name the
current hooks reference documents is a bug fixed in a patch release.

Measured: objective, so no false-positive rate. On the 22-repository sample of docs/field-report.md
(2026-11-06), the default globs find 5 settings files in 4 repositories, all valid, with H findings
in none; R, C and S findings are the same as before the H rules.

## M1 to M4 .mcp.json

Why: a project's `.mcp.json` is how a team shares MCP servers, and Claude Code skips a server it
cannot read, or the whole file, reporting it only in `claude mcp list` and `/mcp`
([MCP](https://code.claude.com/docs/en/mcp), "Project scope", "Configuration warnings"). Files:
`[discover] mcp_globs`, default `.mcp.json` at the repository root only: Claude Code reads project MCP
servers from there, and a plugin's `.mcp.json` has another format (servers at the top level, no
`mcpServers` key), so adding plugin paths with `extend_mcp_globs` reports M2 on each.
`mcp_globs = []` turns the family off. Only the M rules run on these files.

| Id | Finding | Source | What Claude Code does (`claude mcp list`, 2.1.318) |
|---|---|---|---|
| M1 | the file is not valid JSON (reported at the error's line), or its top-level value is not an object | MCP, "Project scope": the file's format | loads no server from it ("MCP config is not a valid JSON") |
| M2 | no `mcpServers` object: missing, another type, or servers under `servers` (VS Code's format) | [debug your config](https://code.claude.com/docs/en/debug-your-config): servers under `servers` "never load" | loads no server from the file |
| M3 | a server entry is not an object, or its `type` is not `stdio`, `http`, `streamable-http`, `sse` or `ws`; `"sdk"` is named separately | MCP, "Add a remote WebSocket server" and the transports; `"sdk"`: "Claude Code skips a `"type": "sdk"` entry in `.mcp.json`" | skips the server |
| M4 | a stdio server (no `type`, or `"stdio"`) has no non-empty string `command`, or a remote server has no string `url`; an entry with a `url` and no `type` says to add one | MCP: "A JSON entry that has a `url` but no `type` is a configuration error"; the required fields are what `claude mcp list` reports | skips the server ("command: expected string", "Command cannot be empty", "url: expected string") |

Readings:

- JSON is read as for H1. Positions are JSON paths (`mcpServers.<name>`).
- M4's required fields are measured, not stated in the MCP docs, which show them in every example.
- Keeping current: the server types (M3) and required fields (M4) are re-read with the H rules' sources
  before every minor release; a finding on a type the current MCP page documents is a bug.
- Not checked: optional fields and their types (`args`, `env`, `headers`, `timeout` and the rest),
  blank values Claude Code only warns about (a `command` of spaces, an empty `url`), reserved server
  names, unset `${VAR}` references, and `.mcp.json` files in plugins.

Measured: objective, so no false-positive rate. On the 22-repository sample (2026-11-06), the default
glob finds 2 root `.mcp.json` files, both valid, with M findings in none; a third `.mcp.json` in the
sample sits in a plugin directory, in the plugin format, and is not matched.

## Rule ids for other files

Rules for other file types get an id prefix per family, so ids stay unique as checks are added: `S` for
`SKILL.md`, `H` for hooks in settings files and `M` for `.mcp.json` (above). `R` and `C` stay with
instruction files, and `E` is reserved for input errors such as `E0`.
