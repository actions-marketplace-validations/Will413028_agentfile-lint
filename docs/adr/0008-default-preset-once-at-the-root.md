# ADR 0008: The default preset is applied once, at the root of `extends`

Status: accepted. Implemented in 0.9.0 (`agentfile_lint/config.py`, `_load_raw`; docs/design.md,
Layers). Changes the merge described in ADR 0006 only where the default preset is concerned; the
override, `unset` and diamond rules of ADR 0006 are unchanged.

## Context

Since 0.1.0, every config file without `extends` was read as `extends = ["preset:default"]`: the
shipped presets (`preset:strict` since 0.5.0) and every shared file a repository names in `extends`.
Each file therefore carried the whole default, and a later `extends` entry reset every key an earlier
entry had set and the default also has. Measured on 0.8.0: with `extends = ["preset:strict",
"team.toml"]` and a `team.toml` that sets only `[rules.R1b] level`, R3b, R4a, R4b, R5b, R6 and C1
were `off` and `[shared.duplicates] ancestor_pairs` was back to `same-name`, as if strict were not
there; in the other order strict applied. A shared file's `[discover] globs` or `[allowlist]
max_entries` was reset the same way by any file after it. Nothing documented this, and 0.9.0 adds
a second preset meant to be combined with strict (ADR 0007, `preset:agentskills`).

## Options

- A: apply `preset:default` once, first, under the file the run loads, whether a file names it or
  not; every other file is a change on top, and the tree of `extends` is merged as before.
- B: linearize the `extends` tree so that every file is applied once (as Python's C3 method order
  does for classes). It changes the result for any shared file reached on two paths, and it would
  have to restate ADR 0006's rule that an `unset` on one path keeps a glob another path still inherits.
- C: apply only shipped presets once and keep the implicit default in shared files. The shared-file
  case above stays broken.
- D: document the order and tell shared files to write `extends = []`. Two shipped presets still
  cannot combine, and such a file fails when loaded alone.

## Decision

A. It is how ESLint, stylelint and markdownlint layer configs: a shareable config holds only what it
changes, entries apply in order and a later one wins on the keys it sets, and the defaults sit once at
the bottom. None of them deduplicates a config reached twice, so B goes further than they do, and
ADR 0006's diamond rule keeps working under A without a change.

Consequences:

- `preset:default` named in any file other than the default itself has no further effect; a file the
  run loads directly (also one given with `--config`) always starts from the default, so
  `extends = []` there no longer means "without the default". A complete file gives the same result.
- Listed under Changed (breaking) in 0.9.0, since a configuration that relied on a later entry
  resetting an earlier one changes. The known consumers pin 0.4.0.
- A shared file reached on two paths is still applied twice, as before; its tables merge again where
  the second path puts it. This changes only if a real case needs it applied once (option B).
