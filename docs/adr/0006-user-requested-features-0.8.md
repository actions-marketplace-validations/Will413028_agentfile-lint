# ADR 0006: User-requested configuration, output and suppression features for 0.8.0

Status: accepted. Amends decision 3 of ADR 0004 (overrides only lower a level). Implemented in 0.8.0;
each section is written by the change that implements it.

## Context

Up to 0.7.0 several features users of similar linters expect were deferred until someone asked: adding
globs without repeating the defaults, leaving known copies out of duplicate checks, raising a level on a
path, undoing an inherited override, per-line suppression, SARIF output and scanning outside git. 0.8.0
adds them before the tool is announced, so the first public version has the configuration surface that
later versions keep.

## Overrides can raise a level, and an inherited override can be undone

ADR 0004 lets an override only lower a level, so a shared config reached through `extends` can never make
a path stricter by accident. It also leaves no way to turn a rule on for one path, and since overrides
concatenate under `extends`, no way to remove an inherited override that does not fit a repository.

Options:

- A: keep lowering as the default; an entry with `raise = true` only raises (from `off` too). When
  entries that lower and entries that raise both match a file, lowering wins. `[[overrides]] unset =
  [globs]` removes globs from inherited entries.
- B: an override sets any level and the last entry wins (ESLint `overrides`). ruff's `per-file-ignores`
  can only turn rules off.

Decision: A. An override that makes a path stricter is written as such, so the guarantee of ADR 0004
holds for every entry without `raise`. Lowering wins over raising because a lowering entry is the more
specific statement about a path that is meant to differ, and the result does not depend on entry order.
`unset` names a glob, not an entry index, so it survives reordering in the file it undoes, and a glob
that is in no inherited entry fails the configuration instead of doing nothing.

Consequences:

- A raised rule runs even when its level is `off`; its findings outside the raised paths are dropped.
- Inherited override globs are now checked for staleness too (a warning on the file that wrote them):
  with `unset` available, a repository can act on the warning.
- `discover.extend_globs` and `[shared.duplicates] exclude` are added in the same release: the first
  concatenates along `extends` like overrides do, the second removes files from the R5a and R5b input,
  which an override (which only changes levels on the files it matches) cannot do.

## Per-line directives

ADR 0004 (decision 6) kept inline suppression rejected because a comment has no expiry date and scatters
exceptions over the files, and named single-line reports as the trigger to reconsider. Per-line
suppression is one of the features users of similar linters expect (Context), and the config has no
tool for one line short of a time-boxed allowlist entry or an override for the whole path.

Options:

- A: `<!-- agentfile-lint-disable-next-line <ids> -- <reason> -->` only (markdownlint's
  `disable-next-line`, ESLint's `-- description` and `--report-unused-disable-directives`); ids and a
  reason required; whole-file rules not accepted.
- B: A plus `disable` / `enable` blocks. A forgotten `enable` silences the rest of the file and needs a
  check of its own.
- C: A without a required reason, unlike every other exception in this tool.

Decision: A. The smallest scope that answers the reports, with the same rule as the allowlist: every
exception says why. Whole-file rules already have the allowlist and overrides. Details:

- The directive goes in the file that reports the finding (for R5a and R5b, the copy, not the original);
  "next line" counts lines as every rule does (LF, CRLF, CR).
- Suppressed findings do not count toward an allowlist entry's `count`.
- The directive is text like any other: it counts toward R1a, R1b, R1c and R1d.
- A malformed directive is a problem in the instruction file, not the config, so it is an error under
  the pseudo rule `disable` (exit 1), not exit 2. A named rule with no finding on the next line is a
  warning. Like `allowlist`, `disable` is in no preset and no level setting changes it.

Consequences:

- The audit trail for one-line exceptions is the files themselves; there is no expiry.
- A comment line in `CLAUDE.md` costs nothing for Claude Code, which strips block-level HTML comments,
  but other agents may read it.

## SARIF output without a built-in upload

`--format sarif` prints SARIF 2.1.0, the version GitHub code scanning reads. The action does not
upload it: an upload input would make `github/codeql-action` a dependency of every action user and
need `security-events: write` on every workflow that runs the action. The README shows the upload as
two extra steps. Rejected: an upload input on the action (the dependency and permission above); SARIF
with no upload test and no README example (nothing would show that code scanning reads the file).

Consequences:

- Code scanning users run the CLI for SARIF and the action (or the CLI) for annotations.
- The rule descriptors come from the rule table, so a new rule appears in SARIF with no change here.

The action's `working-directory` input goes with it: a repository checked out below the workspace
has no git repository at the workspace root, so the action must run inside the checkout. Reported
paths are not prefixed with that directory: findings are relative to the git root, and both
annotations (the runner passes a relative `file=` through unchanged) and code scanning read paths from
the repository root. A live run with a `checkout/` prefix put annotations on `checkout/...`, a path
the repository does not have.

## Scanning outside git

`--no-git` walks the current directory with the same globs, never entering a fixed list of
version-control and dependency directories, and does not read `.gitignore`; git-tracked files stay the
default. Rejected: parsing `.gitignore` (nested files and negation are a reimplementation of git the
standard library does not offer); switching automatically outside a repository (the same command
would scan a different set depending on where it runs, and a misconfigured CI job would pass instead
of failing).

Consequences:

- Generated or ignored instruction files under the walked directory are analyzed; the fixed list is
  the only exclusion.
- Rules that look at the tracked set see every walked file.
