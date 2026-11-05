# ADR 0001: Rule model

Status: accepted. Decision 3 and the rejected inline-comment alternative are amended by ADR 0004
(see Amendment below); ADR 0005 adds a required `count` to allowlist entries; ADR 0006 allows per-line directives.

## Context

Several repositories need the same kind of check on their instruction files, but with
different numbers (budgets per directory depth, required sections). Copying one script per
repository makes the rules drift; hard-coding every repository's numbers into one program makes
the program full of per-repository branches.

## Decision

1. Mechanism and defaults live in this repository as a shipped preset; each consuming repository
   keeps a small tracked config (`.instruction-lint.toml`) that `extends` the preset and overrides
   single keys. Unknown keys fail.
2. Every rule has one of three levels: `error` (exit code 1), `warn` (printed, exit code 0),
   `off`. New rules arrive as `warn`.
3. Exceptions go through an allowlist in the config, never inline comments. Every entry has a
   `reason` and an `expires` date. An expired entry fails, an entry that is no longer needed
   fails, entries warn 14 days before expiry, expiry is capped at 90 days ahead, and at most 10
   entries are allowed. The "no longer needed" check and cross-file rules always look at the
   full tracked file set, not only the files named on the command line.
4. The runner uses only the Python standard library (3.11 or newer, for `tomllib`).

## Alternatives considered

- All numbers inside the shared program, consumers only switch rules on and off: rejected,
  repository-specific limits would become branches in shared code.
- A full copy of the rule file in every repository: rejected, that brings back drift.
- Per-file inline suppression comments: rejected, they have no expiry and cannot be checked
  for staleness.
- Only checking files passed by the hook: rejected, cross-file and allowlist checks would pass
  locally and fail in CI.

## Consequences

- A repository adopts the tool by adding one small config and one hook or workflow line.
- The allowlist forces cleanup but can turn a quiet repository red on the expiry date; the
  warning window and a scheduled CI run exist to soften that.
- Changing a default limit in the preset changes every consumer that did not override it, so
  such changes need a version bump and a changelog entry.

## Amendment (ADR 0004, 0.6.0)

This decision assumed one owner who treats every exception as debt. Once the tool was public, users
also had permanent exceptions (translated or example copies), so:

- Decision 3: the allowlist stays for time-boxed debt; permanent per-path rule levels go in
  `[[overrides]]`, each with a required reason (ADR 0004, decision 3).
- Rejected inline comments: still rejected, but the reason above is half wrong. Whether a comment is
  still needed can be checked (ruff RUF100, ESLint `reportUnusedDisableDirectives`); the remaining
  reasons are that a comment has no expiry date and that comments scatter exceptions over the
  instruction files instead of one place to audit (ADR 0004, decision 6).

## Amendment (ADR 0006, 0.8.0)

- Rejected inline comments: no longer rejected for single lines. Most false-positive reports are about
  one line, and fixing those through the config means an allowlist entry that expires or an override
  that silences a whole path. A per-line directive needs a reason, is reported when it suppresses
  nothing, and covers exactly one line, so it stays auditable (`rg agentfile-lint-disable`) without an
  expiry date. Whole-file exceptions still go in the config.
