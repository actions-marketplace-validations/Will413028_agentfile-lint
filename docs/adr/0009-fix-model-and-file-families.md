# ADR 0009: Fixes belong to findings; each file family has its own glob lists

Status: accepted. Implemented in 0.9.0 (`agentfile_lint/fix.py`, `toml_edit.py`, `discover.py`;
docs/design.md, Fixes and File families). Written after the release to record three decisions 0.9.0
was built on; nothing here changes behavior.

## Context

Up to 0.8.0 the checker only read files, and one glob list (`discover.globs`) decided which files every
rule ran on. 0.9.0 added checks for `SKILL.md`, Claude Code hook settings and `.mcp.json`, and was
asked to fix what it could. Both needed a decision about the model, not only about the first case.

## Fixes

Most findings here have no mechanical fix: a file that is too long has to be rewritten by a person,
and a repeated line may be the copy that should stay. What can be fixed safely is the tool's own
bookkeeping: an unused per-line directive, an allowlist `count` that is now too high, an entry for a
file that no longer violates its rule.

Options:

- A: `--fix` as allowlist maintenance only, with no general model.
- B: a fix model, plus deleting the lines R5a reports as repeated, as an unsafe fix.
- C: no fixes.
- D: move the counted exceptions into a tool-managed baseline file that is rewritten whole, as ESLint
  bulk suppressions and PHPStan's baseline do.
- E: a finding may carry a fix (text edits marked `safe` or `unsafe`); `--fix` applies the safe ones,
  `--unsafe-fixes` adds the others, `--diff` prints without writing; JSON and SARIF carry the fix. The
  first fixes are the bookkeeping above.

Decision: E. It is how ruff and clippy do it: the fix is part of the diagnostic, with an applicability
level, and the engine applies them in one place. Under A the next rule that wants a fix would build
the mechanism again and `--fix` would have to change meaning. B deletes text the tool cannot judge: in
a measured sample of 67 R5a findings, 54 were translated copies or examples that deleting the line
would break (docs/rules.md), and when two copies have drifted the tool cannot tell which one is
right (docs/field-report.md). D fits a repository that
swallows thousands of existing violations at once; here exceptions are few, each has a reason and an
expiry date (ADR 0001, 0005), and a second file and subcommand for at most ten entries is not worth
it. C was open, since every message already says what to change, but a model that later rules can use
costs little more than A.

How it is kept honest:

- A fix never widens what is suppressed: it does not raise a `count` or add an entry (ADR 0005), and
  n > `count`, expired entries and entries for files outside the run are reported, not fixed.
- The runner has no TOML writer (standard library only), so it edits the text of one
  `[[allowlist.entries]]` block. The edited text is parsed again, and when anything but the target
  differs the finding gets no fix.
- After each pass the run is repeated in memory; the suppressed findings and the effective allowlist
  entries may only shrink, otherwise nothing is written.
- Only the config file the run loads is edited, never one reached through `extends`.

Costs: `--fix` and the `fix` fields in JSON and SARIF are public contract from 0.9.0. Config spellings
the line-based locator cannot place (an inline array of entries, a header inside a string) get the
message but no fix. Every later rule that offers a fix has to say whether it is safe.

## File families

With one glob list, adding `**/SKILL.md` to it would run the instruction-file rules (size, commands,
references, repeated lines) on every skill file: 1695 of them in the 22-repository sample of ADR 0007.

Options:

- A: each rule module declares its family (instruction, skill, hooks, mcp); `[discover]` gets a glob
  list per family (`skill_globs`, `hooks_globs`, `mcp_globs`) and an `extend_*` list for each, with
  the meaning `globs` and `extend_globs` already have.
- B: the same families with fixed paths and no config keys.
- C: keep one `globs` list; each rule skips the files that are not its kind, by name.

Decision: A. Under C a user who narrows `globs` turns the S rules off without meaning to, and every R
and C rule needs a file-name test. Under B a monorepo that wants to leave some skill directories out
can only write one override per rule; adding keys later would not break anything, but the keys cost
little now and follow a pattern users already know. Cost: six more config keys, and a file both lists
match is in both families.

## Distribution

Options: A, no new channel, and document the ones that exist (PyPI with `uvx` or `pipx`, the
pre-commit hook, the GitHub Action); B, a Homebrew tap; C, an npm wrapper that calls `uvx`.

Decision: A. The three channels cover how Python command-line tools are usually installed. B and C
each add an account and a release step to maintain, C still needs `uv` on the machine, and nobody has
asked for either. Revisit when an issue asks for one.
