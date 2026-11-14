# ADR 0005: One rule id per check, and allowlist entries that count

Status: accepted; the level of decision 4's errors is changed by the Amendment below. Amends decision 4 of ADR 0004 ("existing ids are not renamed") and decision 3 of
ADR 0001 (the keys of an allowlist entry). Implemented in 0.7.0.

## Context

Up to 0.6.0 one rule id can stand for several checks with different levels:

- R1 (`size`) holds per-file bytes, per-file lines, the combined size on a path and line length, with
  `bytes_level`, `lines_level` and `path_limits.level` under one rule level.
- R4 (`rot`) holds dates and issue numbers at the rule level and narrative words at `narrative_level`.
- R5 (`duplicates`) holds ancestor duplicates at the rule level and sibling duplicates at
  `sibling_level`.

An allowlist entry and an override name a rule id and a path, and an allowlist entry hides every finding
of that rule in that file. With 0.6.0 this hides a hard limit behind a soft one: a repository that
allowlists a 200-line warning on an `AGENTS.md` also hides the 32 KiB path error on the same file, and
the run exits 0 instead of 1. The same holds for any new violation of the same rule in a file that
already has an entry: the entry says nothing about how many findings it was written for.

Similar tools give one id one check and one level (ruff, ESLint, markdownlint), and their baselines
record how many findings they accept per file and rule (ESLint `eslint-suppressions.json` keeps a
`count` per file and rule and reports unused or reduced suppressions; PHPStan's baseline keeps
`message`, `count` and `path` and reports unmatched entries). Path-wide ignores do not count (ruff
`per-file-ignores`), which is what `[[overrides]]` already are.

0.6.0 is not announced; every known consumer pins an older release, so no compatibility window is
needed.

## Options considered

1. Keep the ids and add a `check` key to allowlist entries and overrides. Keeps the config, but the
   sub-checks stay unnamed in output and `--list-rules`, and the sub-level keys stay.
2. Count allowlist entries without splitting ids. Stops new findings hiding, but a 200-line entry still
   needs a count that includes the path error, so one entry still covers two levels.
3. Split each multi-level rule into one id per check and give allowlist entries a required `count`.
   Breaks every config that names R1, R4 or R5 or their sub-level keys.

## Decision

1. One id, one check, one level. R1 becomes `R1a` per-file bytes (`file-bytes`), `R1b` per-file lines
   (`file-lines`), `R1c` combined bytes on a path (`path-bytes`) and `R1d` line length
   (`line-length`); R4 becomes `R4a` dates and issue numbers (`dated-refs`) and `R4b` narrative words
   (`narrative-words`); R5 becomes `R5a` ancestor duplicates (`ancestor-duplicates`) and `R5b`
   sibling duplicates (`sibling-duplicates`). The keys `bytes_level`, `lines_level`,
   `path_limits.level`, `narrative_level` and `sibling_level` are removed. R2, R3c and C1 keep one id:
   their parts share one level and one set of parameters. R6 stays `warn` only.
2. Detection parameters that several ids share live in a new top-level table per group:
   `[shared.size]` (`excluded_blocks`, for R1a, R1b and R1d) and `[shared.duplicates]`
   (`ancestor_pairs`, `min_chars`, `ignore_headings`, `ignore_patterns`, for R5a and R5b). A
   `[rules.<id>]` table holds the level and keys that belong to that id only. Unknown tables and keys
   under `shared` fail like any other key, and `shared` merges through `extends`.
3. Old ids and aliases (`R1`/`size`, `R4`/`rot`, `R5`/`duplicates`) are a configuration error (exit 2)
   wherever a rule id is accepted, with a message that lists the new ids; a removed key gets a message
   naming the id that replaces it. An old id is not an alias for its group: silently turning one
   allowlist entry into several would bring back the problem this ADR fixes.
4. Every allowlist entry has a required `count` (an integer of at least 1): the number of findings of
   that rule in that file it was written for. With n such findings after overrides:
   - n = count: all are suppressed.
   - n > count: none are suppressed, and the allowlist reports an error expecting `count` and
     finding n (the ESLint behaviour; reporting only "the extra ones" would need a stable identity for
     each finding, which line numbers are not).
   - 0 < n < count: all are suppressed, and the allowlist reports an error asking to lower `count`
     to n.
   - n = 0: the existing "no longer needed" error.
   Overrides do not count.
5. The behaviour of 0.6.0 under the default and strict presets does not change: every finding is
   reported at the same file, line and severity, under its new id.

## Rationale

- A level belongs to what a finding means. Exceptions name ids, so an id that spans levels makes an
  exception span levels; splitting the id is the only way the config can say "accept the warning, keep
  the error".
- The count closes the remaining gap inside one id (a second duplicate line in a file that already has
  one accepted) without per-finding fingerprints.
- Shared tables keep one fact in one place: block markers and the definition of an ancestor pair would
  drift if copied into each id's table (ESLint `settings` serves the same purpose).
- A clean break now is cheaper than a migration layer: there are no outside users yet.

## Consequences

- 0.7.0 is a minor release whose `Changed (breaking)` lists the new ids, the removed keys, `shared` and
  the required `count`; R1a and R1c are listed under `Graduated` as split from R1.
- `allowlist.max_entries` stays 10. One old R1 entry can become up to four entries and one R5 entry
  two; the cap exists to push fixes, not to fit old configs.
- `docs/design.md`, `docs/rules.md`, the presets, `README.md` and the field report use the new ids.

Revisit when:

- A repository upgrading to 0.7.0 needs more than 10 entries after the split, or an outside user
  reports it: reconsider `max_entries`.
- Users ask to name the whole old group at once: consider a group selector in addition to the ids,
  never as an alias.

## Amendment (0.10.0): an entry's notes have the level of its rule

Decision 4 made every count mismatch an error, and "no longer needed" and "expired" were errors
before it. For a rule at `warn` that made the exception stricter than the rule: a file with two
accepted warnings and an entry with `count = 2` failed the run on a third warning, or on the day one
was fixed, while the same file without the entry only printed warnings. A repository that used an
entry to keep known warnings quiet got a commit blocker instead, and the way out was to delete the
entry and let the warnings print on every run.

Changed: the notes an entry produces (n > count, n < count, no longer needed, expired) take the level
of the entry's rule on that path after overrides, where `off` gives `warn`, and so does a rule whose
findings are warnings at any level (R6). An entry for `E0` stays an error. What is suppressed does not change: n > count and an expired entry still
suppress nothing, so a new finding is never hidden.

Rejected: refusing entries for rules at `warn` (a config error). The counted entry is the only way
to say "these two are known, show me the third"; an override to `off` hides the third as well.

Cost: for a rule at `warn`, a stale or miscounted entry no longer fails CI unless `--warn-as-error`
is given. That is the same cost the rule's own findings already have.
