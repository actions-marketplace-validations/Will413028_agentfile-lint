# ADR 0004: Exceptions, output and rule ids for public use

Status: accepted. Amends decision 3 of ADR 0001 (permanent exceptions; the reason for rejecting
inline comments) and replaces parity with the legacy checker as the specification of R1 sizes
(`docs/design.md`). Decision 4 ("existing ids are not renamed") is amended by ADR 0005; decision 3 (overrides only lower) by ADR 0006 (`raise = true`, `unset`); decision 6 (no inline comments) by ADR 0006 (per-line directives). Planned for 0.6.0; until then the code on `dev` changes one part at a time.

## Context

ADR 0001 was written while one owner ran the tool on their own repositories. Three of its premises
stopped holding once the tool was published (a PyPI package and a public GitHub Action):

- One owner governs every consumer, so every exception is debt the owner will clean up: an allowlist
  entry names one rule and one file, needs an expiry date (by default at most 90 days ahead and at
  most 10 entries; a config can raise both) and fails once it is no longer needed. A public user also
  has permanent, legitimate exceptions that cover many files (translated or example copies of an
  instruction file under `docs/<language>/` or `examples/`, see ADR 0003): today that is one entry per
  file, each with a date to renew, or the rule turned off for the whole repository.
- The output is read in the owner's own CI logs. It is text only and severity is carried by the
  stream (errors on stderr, warnings on stdout): merged with `2>&1` the severity is lost. A whole-file
  finding prints line `0`, which neither the GNU format nor GitHub annotations have. There is no
  machine-readable format, while similar tools offer JSON, SARIF or GitHub annotations.
- R1 must give the same numbers as the checker it replaced. Per-file bytes are counted in text mode
  (CRLF counted as LF) after removing `excluded_blocks`, as that checker did; the combined
  `path_limits` count bytes on disk. One key, `max_bytes`, has two measurements.

Two smaller defects: the pseudo rule id `input` (a file that is not valid
UTF-8) cannot be named in the config, and rule ids are opaque codes (`R5`) although every rule has a
descriptive name (`duplicates`, printed by `--list-rules`).

Constraints:

- External: a GitHub workflow command is `::error file={name},line={line},title={title}::{message}`;
  `line` is optional and defaults to 1, so GitHub has no whole-file annotation
  (https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands). Escaping is
  not in that page; the reference is `escapeData` (`%`, `\r`, `\n`) and `escapeProperty` (also `:`
  and `,`) in `actions/toolkit`, `packages/core/src/command.ts`. The GNU format is
  `sourcefile:lineno: message`, or `program: message` when no source file is relevant; it has no form
  for a finding about a whole file (https://www.gnu.org/prep/standards/html_node/Errors.html).
  Claude Code strips block-level HTML comments from CLAUDE.md before loading it
  (https://code.claude.com/docs/en/memory). Codex concatenates AGENTS.md files from the root down and
  stops adding files at `project_doc_max_bytes` (32 KiB); its documentation describes no stripping,
  so comments presumably count toward the limit (inferred,
  https://learn.chatgpt.com/docs/agent-configuration/agents-md). SemVer: "Major version zero (0.y.z)
  is for initial development. Anything MAY change at any time." (https://semver.org/, item 4).
- Inherited and self-imposed: `docs/versioning.md` made every output change a major version even
  before 1.0. Existing users pin a commit SHA or a vendored copy, so a change reaches them only when
  they upgrade.

## Options considered

1. Output.
   - Keep the text format and add `--format json|github`. Rejected: severity by stream and the `:0`
     line would stay, and after 1.0 fixing them is a major version.
   - Severity in every line, one stream, a defined whole-file form, plus JSON and GitHub formats.
     Chosen (decisions 1 and 2). Baseline: ruff (`--output-format` with `json`, `github` and others,
     https://docs.astral.sh/ruff/settings/), agnix (`--format json|sarif|github`,
     https://github.com/agent-sh/agnix/blob/main/docs/CONFIGURATION.md).
   - As above, but a whole-file finding printed as `file:1:`. Rejected: in text and JSON, line 1
     would read as the location of the problem.
2. Permanent exceptions.
   - Allowlist only (ADR 0001). Rejected: an entry names one file and one rule, with no globs, and a
     permanent exception can only be written as a far-off expiry date, which hides that it is
     permanent.
   - Per-path rule levels in the config that only lower a rule, with a required reason; the allowlist
     stays for debt. Chosen (decision 3). Baseline: ruff `per-file-ignores` and agnix `[[overrides]]`
     (`paths`, `disabled_rules`) only turn rules off for matching files.
   - The same, but an override may also raise a level or turn a rule on under a path, as ESLint
     configuration objects with `files` can
     (https://eslint.org/docs/latest/use/configure/configuration-files). Not now: nobody has asked for
     it, it would end "the rule level caps a finding", and a shipped preset could raise a rule past
     the `Graduated` check in `tests/test_versioning.py`. It can be added later under a new key or
     value; giving `warn` the meaning "turn on" would change what existing overrides on an `off` rule
     do (today nothing).
   - A per-rule `exclude` glob list (like markdownlint-cli2 `ignores`, but per rule). Rejected: it
     cannot lower a rule to `warn` under a path.
   - Inline suppression comments. Rejected, decision 6.
3. Byte measurement.
   - Bytes on disk for every size check; `excluded_blocks` is an explicit deduction. Chosen
     (decision 5).
   - Keep both measurements and document them. Rejected: one key with two meanings would outlive 1.0.
4. Status of `check-pins` and `vendor`.
   - `vendor` in the contract, `check-pins` experimental. Chosen (decision 7).
   - Both experimental. Rejected: the vendored copy is a main difference from similar tools (README)
     and would lose its compatibility promise.
   - Both in the contract. Rejected: `check-pins` serves mainly someone who maintains many
     repositories; keeping it compatible costs more than it is used.

## Decision

1. Output.
   - Text: `file:line: severity: rule-id: message`, where `severity` is `error` or `warning`; a
     whole-file finding is `file: severity: rule-id: message`. All findings go to stdout. Usage and
     configuration errors (exit 2) stay on stderr as `agentfile-lint: message`.
   - `--format json`: one object `{"version": 1, "findings": [...]}`; each finding has `file`,
     `line` (`null` for a whole file), `level` (`error` or `warning`), `rule` and `message`. `level`
     says `warning`, as the text format and GitHub's `::warning` do, while configs keep `warn`.
     `version` goes up only when a field is removed or changes meaning, not when one is added.
   - `--format github`: `::error` or `::warning` with `file`, `line` (omitted for a whole file, which
     GitHub shows on line 1) and `title` set to the rule id; the message is the text-format line, as
     in ruff's GitHub format (`path:row:col: CODE message`), so findings past GitHub's annotation
     limits (10 errors and 10 warnings per step, 50 annotations per job; actions/toolkit
     `docs/problem-matchers.md`) still show their location in the log. Escaped like `escapeData` and
     `escapeProperty`. `action.yml` always passes `--format github`; its inputs do not change.
   - `check-pins` prints its findings in the same text format on stdout and has no `--format`; its
     summary goes to stderr; with `--require-refs` and no reference found it prints
     `check-pins: error: no reference to … found` on stdout and exits 1.
   - Exit codes stay `0` (no errors), `1` (at least one error) and `2` (usage or configuration).
2. Pseudo rule ids. `input` becomes `E0`. An allowlist entry may name it; `[rules]` and
   `[[overrides]]` may not turn it off. `--list-rules` lists it, as it lists `allowlist`. `allowlist`
   keeps its name: it checks the config itself and cannot exempt itself.
3. Permanent path scope: `[[overrides]]` entries, each with `paths` (globs), `rules` (a rule id or
   alias mapped to `warn` or `off`) and a required `reason`.
   - An override only lowers. It changes levels, never rule parameters, and never raises a finding
     above its rule's level. For one file and one rule, the lowest of the rule level and every
     matching override applies, so the order of entries does not matter.
   - An override applies to the findings reported on the files it matches, as an allowlist entry does.
     Those files stay in the input of cross-file rules (`path_limits` still counts what the agent
     reads).
   - Globs match the analyzed instruction files. In the config file the run loads directly
     (`.agentfile-lint.toml`, or the file given with `--config`), each glob that matches none of them
     is a warning (rule `allowlist`, a whole-file finding on that config file, naming the entry by its
     index in that file); like every warning it does not change the exit code unless
     `--warn-as-error` is given. Entries that arrive through `extends` (shared configs, presets) are
     not checked: a shared config serves many repositories, and not every repository has every path.
   - Under `extends`, override lists are concatenated. This is the one list that a child config does
     not replace; replacing it would silently drop the overrides of the config it extends. In return a
     child cannot undo an override it inherits, so the shipped presets carry no overrides (every
     config extends `preset:default`).
   - The allowlist stays for time-boxed debt, with its caps (90 days, 10 entries) as configurable
     defaults.
4. Rule aliases. A rule's descriptive name (the name `--list-rules` prints, such as `size` for R1) is
   accepted wherever a rule id is: `[rules.<id>]`, an allowlist `rule`, override `rules`. Aliases are
   resolved in each config file before merging; one file naming the same rule by both its id and its
   alias fails (exit 2). Existing ids are not renamed. Ids for future file types (`SKILL.md`, hooks,
   MCP config) get family prefixes, planned in `docs/rules.md`; `E` is reserved for input errors.
5. R1 sizes and positions. R1 reads bytes on disk, for `limits` and `path_limits` alike.
   `excluded_blocks` applies to the per-file checks (the bytes and lines of `limits`, and
   `max_line_chars`) and not to `path_limits`; it subtracts the bytes of each block on disk,
   including its line ending (`\n`, `\r\n` or `\r`). A per-file limit is the author's budget, and a block
   that a tool writes into the file is not the author's text, while `path_limits` model what the agent
   reads, blocks included. Lines inside a block are neither counted nor checked for length, but every
   R1 finding reports its line number in the file on disk, since that number is what an editor or a
   GitHub annotation points at.
   Parity with the replaced checker is no longer the specification: `tests/fixtures/legacy-oracle/`
   stays as it is, and `tests/test_contract.py` compares against it through a list of deliberate
   differences (CRLF bytes, line numbers after a block), each with its reason.
6. Inline suppression comments in instruction files stay rejected, for a corrected reason. Whether a
   comment is still needed can be checked (ruff RUF100, https://docs.astral.sh/ruff/rules/unused-noqa/;
   ESLint `reportUnusedDisableDirectives`, default `"warn"`,
   https://eslint.org/docs/latest/use/configure/rules), but a comment has no expiry date, and comments
   scatter exceptions over the instruction files instead of keeping them in one place to audit. They
   also cost the agents differently: Claude Code strips block-level HTML comments, while nothing
   documents that Codex discounts them from its 32 KiB. ADR 0001's reason ("no expiry and cannot be
   checked for staleness") was right about expiry and wrong about staleness.
7. Subcommands. `vendor` and the vendored `verify.py` are part of the contract. `check-pins` is
   experimental: its output and options may change in any minor release, it is marked
   "(experimental)" in the README and in its `--help`, and the upgrade notes call it optional. The
   `[check_pins]` table in the config is not experimental: the main command validates it like any
   other key (unknown keys fail), so it follows the rules for config keys.
8. Versions before 1.0. A change to the output format, a rule id or alias, or a config key is a minor
   version, listed under `Changed (breaking)` in the changelog; from 1.0 on it is a major version.
   Exit codes change only in a major version.

## Rationale

The cost of each of these changes grows with every user who adopts the tool, and before an
announcement it is lowest: existing users pin a SHA or a vendored copy, and no known consumer parses
the text output. Fixing the output contract, the exception model, the ids and the byte measurement now
costs one minor release; after an announcement each would be a breaking change for strangers.

Overrides and aliases are additive and could ship in any later minor release. They are in 0.6.0
because the announcement documents a known false-positive class of R5 (translated and example
copies), and a remedy short of turning R5 off should exist before strangers hit it: this handles ADR
0003's revisit condition ahead of the user reports it waits for. Aliases make config and override
entries readable (`duplicates` instead of `R5`).

The price: a program that parses the text output must handle two line shapes (with and without a line
number) instead of one; JSON is the format meant for programs. Overrides make permanent exceptions
cheap, which can also hide real problems; the required reason and a warning for a glob that matches
nothing keep them visible, but a stale override does not fail CI, and overrides inherited from a
shared config are not checked at all; a repository also cannot undo an override it inherits. With
`preset:strict`, R5 also compares sibling files and reports on every file of the group, so an
override on the copies (`docs/**`) does not silence the finding on an original outside those paths.
Bytes on disk make a CRLF file count one more byte per line against its `limits`.

## Consequences

- 0.6.0 is a minor release with `Changed (breaking)` entries for the text output, the `E0` id, R1
  bytes of CRLF files and R1 line numbers after an excluded block; the status of `check-pins` is
  listed under `Changed`.
- `tests/test_contract.py` compares R1 with the legacy checker except for recorded differences.
- `docs/versioning.md`, `docs/design.md`, `README.md`, `CONTRIBUTING.md` and the repository's
  `AGENTS.md` describe the contract above.

Revisit when:

- Most false-positive reports ask to silence single lines rather than paths: reconsider inline
  suppression (decision 6).
- Someone asks to feed results into code scanning: add SARIF.
- Users depend on `check-pins` (issues or pull requests about it): move it into the contract.
- Users ask to raise a level or turn a rule on under a path: add it under a new key or value (an
  existing `warn` override on an `off` rule keeps doing nothing), and make the `Graduated` check
  read the overrides of shipped presets.
- A stale override in a shared config causes a reported problem: check overrides that arrive through
  `extends` too.
- A repository reports that it cannot undo an override from a shared config: add a key that does.
- Users report R5 findings from sibling comparison with `preset:strict` on translated or example
  copies: give R5 a path exclusion that removes files from its comparison.
