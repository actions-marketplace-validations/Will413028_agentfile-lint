# ADR 0003: The default preset runs only objective checks

Status: accepted; the Claude Code constraint is corrected by the Amendment below. Supersedes the default values in decision 1 of ADR 0002 and its rejection of a
combined 32 KiB limit; the `limits` model of ADR 0002 stands.

## Context

Up to 0.4.0 every rule ran with no config: R1 at `error`, the others at `warn`. Running 0.4.0 with no
config on the root of popular public repositories (the twelve most-starred with an AGENTS.md or
CLAUDE.md, picked by `gh search repos "stars:>5000"`) gave mostly noise. Sampled false-positive rates
(false / (true + false), up to 20 findings per rule): R3b 18/19, R4 16/19, R5 20/20, R6 13/17. Every
C1 finding was a repository that keeps real content in CLAUDE.md, a convention of this tool rather
than an error. Seven of the twelve repositories exited 1 on R1, four of them only on limits with no
source (12000/6000 bytes, 500 characters per line).

Constraints:

- External: Codex reads at most 32 KiB of project docs (`project_doc_max_bytes`, a hard limit;
  https://learn.chatgpt.com/docs/agent-configuration/agents-md). Claude Code asks for fewer than 200
  lines per CLAUDE.md, reads AGENTS.md when no CLAUDE.md exists, and truncates nothing (wrong for
  files loaded on demand; see Amendment)
  (https://code.claude.com/docs/en/memory). A version number uploaded to PyPI cannot be reused.
  Existing users pin a SHA or a vendored copy, so a new default reaches them only when they upgrade.
- Inherited: "new rules enter at `warn`" (docs/versioning.md) still holds; it governs raising a rule,
  and this decision only lowers rules. R1 at `error` dates from 0.1.0; it still holds for the one
  limit that is a hard limit, not for guidance.

## Options considered

1. Baseline: default only checks whose findings are facts, put heuristics and conventions in a named
   opt-in group (ruff selects only `E4`, `E7`, `E9`, `F` by default; ESLint's `recommended` holds only
   likely errors; Clippy keeps `pedantic` off). Chosen, with the threshold below.
2. Turn a rule off when its sample false-positive rate exceeds 30%. Rejected: with 5 to 20 findings a
   sample rate cannot show a rate below 30%; five findings with no false positive still allow 43%
   (Wilson 95% upper bound).
3. Keep every rule at `warn` and tighten patterns. Rejected: meeting 30% would mean removing 92 to 100%
   of the false positives of R3b, R4 and R6 without losing their true findings.
4. R1 entirely at `warn`. Rejected: then no default ever fails CI, even for a file Codex cannot read
   in full.

## Decision

1. A rule is on by default only if it is objective, or if on a held-out sample of repositories (not
   used to tune it) 9 to 20 labelled findings give a Wilson 95% upper bound on its false-positive rate
   of at most 30% (in practice: at most one false positive in 20). Fewer than 9 findings: not on by
   default.
2. Default: R1, R2, R3a, R3c, and R5 for same-name ancestor pairs (`ancestor_pairs = "same-name"`,
   `sibling_level = "off"`). R3b, R4, R6 and C1 are `off`. `preset:strict` turns them on at `warn`
   and sets R5 to `any` pair and siblings to `warn`, the 0.4.0 behavior.
3. Every default `error` points to a hard limit in an agent's documentation. R1 default: AGENTS.md
   files on one path from the root that total over 32768 bytes are an error (`path_limits`, since the
   Codex limit is a total, and ADR 0002's reason to skip it, defaults that kept a path under 18000
   bytes, is gone with those defaults); AGENTS.md and CLAUDE.md over 200 lines are a warning. `limits`
   entries take `bytes_level` and `lines_level`; `max_line_chars` is optional. On 22 public repositories,
   a per-file check finds 3 files in 2 repositories; the combined check reports 16 files in 6.

R5 same-name pairs passed point 1: on a held-out sample of ten repositories, 0 of 13 findings were
false positives (upper bound 22.8%); a sample this small passes only with zero. Same-name ancestor
files are what one agent loads together (Codex reads AGENTS.md from the root down to the working
directory, Claude Code CLAUDE.md from the working directory up). Different names in one directory
are read by different agents, and siblings by none together.

## Rationale

The trade-off: with no config the tool now reports little (mostly R1, sometimes R5), so a first run
shows less of what the tool can do, in exchange for findings a stranger can trust. The value for teams
is in rules that need config anyway (R2 shapes, R3c spec references, expiring allowlist entries,
vendored copies); `preset:strict` is one line for anyone who wants the heuristics. Turning rules off
first is the cheap direction: turning one on later only adds warnings, while shipping it on and
turning it off later is noticed only by readers of the changelog.

## Consequences

- Repositories that relied on the 0.4.0 defaults add `extends = ["preset:strict"]` and, for the old R1
  limits, copy them from the CHANGELOG.
- `docs/rules.md` states each rule's measured false-positive rate and interval.
- The 13 R5 findings come from two repositories, and in the tuning sample the same class had 54 false
  positives in one repository (translated and example copies under `docs/<language>/` and `examples/`).
  Findings in one repository are not independent, so the interval is optimistic. This class of false
  positive is known and accepted for 0.5.0: R5 has no path exclusion, so such a repository turns R5
  off or lists the copies in the allowlist.

Revisit when:

- A heuristic rule passes point 1 on a new sample: move it into the default in a minor release.
- Users report R5 same-name findings on deliberate copies (translations, examples): add path
  exclusions or turn it off by default.
- Codex documents that it does not drop content past 32 KiB: lower that limit to `warn`.

## Amendment (0.6.0): Claude Code's character limit

The constraint "Claude Code truncates nothing" is wrong. Claude Code's memory documentation
(https://code.claude.com/docs/en/memory, read 2026-11-03) says a file it loads on demand (a
subdirectory CLAUDE.md, CLAUDE.local.md and its `@path` imports, path-scoped rules) is cut to its first
40,000 characters with a 200K context and more with a 1M context, with a note telling Claude to read
the rest; large files also get a warning at startup, at a size the documentation does not state.

0.6.0 does not add a character check; it corrects the documentation and states the blind spot in
docs/rules.md (R1). Reasons: on the 22-repository sample no CLAUDE.md is over 40,000 bytes (so none is
over 40,000 characters), and every file over 40,000 characters is a subdirectory AGENTS.md the 32 KiB
path limit already reports, so the check would find nothing new; and a character check needs a counting
contract (code points or UTF-16 units, HTML comments and frontmatter, CRLF, `excluded_blocks`) that
would follow Claude Code's versions. A new warn-level check can be added later in a minor release.

Revisit when an issue asks for a character limit, or a CLAUDE.md over the limit that the default misses
is reported; `.claude/rules/` and CLAUDE.local.md as file types go with it.

## Amendment (0.9.0): R1e, Claude Code's per-file character limit

0.9.0 widens the scope to the other files an agent reads (`SKILL.md`, hooks and `.mcp.json` checks)
and brings the file types Claude Code loads like CLAUDE.md into the default: `**/CLAUDE.local.md` and
`**/.claude/rules/**/*.md`. That is the decision the 0.6.0 amendment deferred, taken by the maintainer
before its trigger occurred: no issue has asked for a character limit and no miss has been reported.
The reason is coverage, not a reported failure: a linter for the files an agent reads should cover the
files Claude Code documents as truncated. With those files in scope, the character limit gets its own
id, R1e (`file-chars`), at `warn` in the default preset.

- Files: the ones Claude Code's memory documentation lists as loaded on demand (read 2026-11-06):
  CLAUDE.md and CLAUDE.local.md in a subdirectory, rules in a subdirectory's `.claude/rules/`, and
  path-scoped rules in the root `.claude/rules/`. Which root rules are path-scoped depends on their
  frontmatter (`paths`), so a limit entry may require a frontmatter key; files loaded at launch have
  no limit, since the documentation gives them whole up to 4 MiB.
- Count: code points, as the documentation's `wc -m` counts them (a CR included), of the text Claude
  Code measures: without the frontmatter and block-level HTML comments, trimmed (Claude Code 2.1.317
  and 2.1.319 code). Claude Code counts UTF-16 units; where the documentation and the code differ, the
  documentation wins, as for every default's source. `excluded_blocks` does not apply, as for R1c: the
  agent reads the blocks.
- Level: `warn`, not `error`. The limit is 40,000 characters with a 200K context and 150,000 or
  200,000 with a 1M context, and Claude can still read the rest with the Read tool, so 40,000 is a
  point where text may be dropped, not one where it always is.
- Measured: on the 22-repository sample no file R1e checks is over 13,370 characters, so R1e adds no
  finding there; it exists for the files the 0.6.0 amendment describes (long or non-ASCII lines under
  200 lines), which the default otherwise misses.

Consequences: a counting contract that follows Claude Code's versions; a change in Claude Code's
limit or count is a change to R1e's default (minor before 1.0, listed in the CHANGELOG).
