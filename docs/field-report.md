# Field report: 22 public repositories with no config

What `agentfile-lint` reports on popular public repositories when nobody configured it, how that
changed from 0.4.0 to 0.5.0, and what the findings that were real looked like. Measured 2026-11-03 with
the releases from PyPI. Per-rule reasons and false-positive rates are in `docs/rules.md`.

0.6.0 was rerun on the same 22 commits on 2026-11-04 (`--format json`, with no config and with
`preset:strict`): every finding (file, line, rule, level) and every exit code is identical to 0.5.0.
0.5.0 was rerun alongside it and reproduced the 2026-11-03 totals exactly. 0.7.0 was rerun on
2026-11-05 the same way: every finding keeps its file, line and level and every exit code is the same
as 0.6.0; only the rule ids changed, since 0.7.0 gives each check its own id (`docs/adr/0005`). 0.8.0
was rerun the same way against 0.7.0: every finding and exit code is identical, including R1b (no
sample file contains the line breaks 0.8.0 stopped counting). The numbers below hold for 0.5.0 to 0.8.0
and use the 0.7.0 ids.

## Summary

- 0.5.0 with no config: 103 findings in 11 of 22 repositories; 6 repositories exit 1. 0.4.0 gave 1096
  findings in 19 and failed 12.
- Every 0.5.0 error is the same fact: the `AGENTS.md` files on one path add up to more than 32 KiB, the
  point where Codex stops reading (16 errors in 6 repositories). Only 2 of those files are over the
  limit on their own.
- The other 0.5.0 findings are 20 files over 200 lines and 67 lines repeated between a file and its
  same-name ancestor. In the held-out sample, 0 of 13 repeated lines were false positives.
- The heuristic rules (R3b, R4a, R4b, R6, C1 and R5b across names) were wrong 76% to 100% of the time on the
  tuning sample, so 0.5.0 runs them only with `preset:strict`.

## Sample

- Candidates: `gh search repos "stars:>5000" --sort stars -L 200`, run 2026-11-03, in star order; a
  repository qualifies when it has an `AGENTS.md` or `CLAUDE.md` at its root (95 of 200 did).
- The first 12 are the tuning sample: rules and defaults were adjusted while looking at them. The next 10
  are the held-out sample: used only to measure, after the defaults were fixed (`docs/adr/0003`).
- Each repository was cloned with `--depth 1` at a recorded commit and checked from its root with
  `python -I -m agentfile_lint` and no config file. They hold 1 to 37 tracked `AGENTS.md`/`CLAUDE.md`
  paths each (210 in all, symlinks included).
- Repositories are not named here. Not following this tool's conventions is not a fault, and a few
  thousand stars do not make a repository a test fixture. The commits are recorded privately so the
  numbers can be re-run.

## Findings by version

All 22 repositories, no config:

| | repos exit 1 | repos with findings | R1c error | R1b warn | R5a | R5b | R3b | R4a | R4b | R6 | C1 | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.4.0 | 12 | 19 | 339 (R1) | 0 | 278 (R5) | | 225 | 160 (R4) | | 40 | 54 | 1096 |
| 0.5.0 to 0.8.0 | 6 | 11 | 16 | 20 | 67 | off | off | off | off | off | off | 103 |
| 0.5.0 to 0.8.0 `preset:strict` | 6 | 19 | 16 | 20 | 87 | 87 | 222 | 108 | 51 | 40 | 50 | 681 |

0.4.0 had one id for each of R1, R4 and R5 and was not rerun per check: its counts for each group
are in the first column of the group. In 0.4.0 every R1 check (bytes per file, lines, line length)
was an `error`.

What changed, by cause:

- **R1, 339 errors to 16.** 0.4.0 failed a file over 12,000 bytes at the root or 6,000 bytes in a
  subdirectory, over 200 lines, or with a line over 500 characters, all at `error`; no agent documents
  the byte or character limits. 0.5.0 makes the error the combined size along a path, which Codex
  documents (32 KiB, `project_doc_max_bytes`), and keeps Claude Code's 200 lines as a warning. A per-file 32 KiB check would have caught 3 files in 2 repositories; the combined check
  catches 16 paths in 6.
- **R5, 278 to 67.** 0.4.0 treated a `CLAUDE.md` symlinked to `AGENTS.md` as a second file and compared
  the text with itself; in the tuning sample about half of the R5 findings came from that. 0.5.0 also
  compares only a file with its same-name ancestor by default, the pair one agent loads together.
- **R3b, R4, R6, C1 off by default.** Measured on the tuning sample: R3b 18 of 19 false positives, R4
  16 of 19, R6 13 of 17; C1 reports differences of convention, not errors. `preset:strict` keeps them
  for teams that want the candidates. Their patterns did not change; the strict counts are lower than
  0.4.0 only where 0.4.0 counted a symlink twice.

Run time with 0.5.0: at most 4.9 s, for the repository with 27 instruction files; 3.2 s for the one with
97,000 tracked files. Measured once each on a shared, busy machine, so treat them as upper bounds.

## What the real problems looked like

Paraphrased, with names and text changed, so the examples cannot be searched for.

**Text an agent never reads (R1c, error).** For example, a root `AGENTS.md` of about 20 KiB plus a
package `AGENTS.md` of about 13 KiB. Each file is reasonable alone; together they pass 32 KiB, so Codex
working inside that package reads the root file and only part of the package file, and does not say
so. This is the most common finding: 6 of 22 repositories. In 4 the total is a root file plus one or two
files below it, over by 0.3 KiB to 22 KiB; in 2 the root file alone is over, at 71 KiB and 213 KiB.

**Copies that have already drifted (R5a).** A package's `AGENTS.md` repeats eight lines of the root
file's "frontend quick reference". An agent in that package loads both. In two neighbouring lines the
copies already disagree (which icon library to use, how strict the typing rule is), so the agent gets
two versions of one rule. Another repository had a generated bootstrap file in a subdirectory that
repeats three lines of the root one.

**A known false positive (R5a).** One tuning repository keeps translated copies of its instruction files
under `docs/<language>/` and examples under `examples/`. All 54 same-name findings there are deliberate
copies. Since 0.6.0 such a repository turns the rule off for those paths with `[[overrides]]`
(`docs/rules.md`, R5a).

With `preset:strict`, the real ones among the sampled candidates:

- **A path that moved (R3b).** "Skills go in `skills/<name>/`", while that kind of skill now lives in
  another top-level directory.
- **History instead of a rule (R4a).** "PR #NNNN moved the internals; the compatibility layer is
  removed after its window ends": true when written, stale once the window passed.
- **A value copied from code (R6).** A file states the exact character limit and the dependency-age
  window that are set in the source and the build config; when the code changes, the file is wrong and nothing fails.

## Limits of this report

- 22 repositories, all popular and most of them AI tooling; smaller or older projects may differ.
- Labels are one reviewer's, with a second reviewer spot-checking; findings from one repository are not
  independent, so the intervals in `docs/rules.md` are optimistic.
- The checks ran at one commit per repository on 2026-11-03; the repositories have changed since.
