# ADR 0007: Vendored PyYAML for frontmatter; SKILL.md rules grouped by reader

Status: accepted. Narrows the "no third-party dependencies at run time" goal of `docs/design.md` to "nothing
to install". The parser part is implemented in 0.9.0 (`agentfile_lint/_yaml/`,
`agentfile_lint/frontmatter.py`); the reader groups are implemented by S1 to S12, also in 0.9.0
(`agentfile_lint/rules/skill.py`, docs/rules.md).

## Context

0.9.0 checks `SKILL.md` files. The Agent Skills specification requires YAML frontmatter, and the
standard library has no YAML parser. A measurement over 1695 `SKILL.md` files from 22 public
repositories showed that a hand-written subset parser (plain and quoted scalars, block scalars, one
level of `metadata`) could not read 305 of them, which would hide the violations in exactly those
files. "Is the frontmatter valid YAML" is also the check with the most value: Claude Code still loads a
skill whose frontmatter does not parse, but silently drops every field.

The same measurement showed that the rules depend on who reads the file. Claude Code ignores unknown
fields and lets `name` differ from the directory; claude.ai upload and the Skills API reject keys
outside the specification's six. The reference validator rejected 929 of the 1695 files, most of them
for fields Claude Code accepts.

## Parser

Options:

- A: vendor the pure-Python part of PyYAML 6.0.3 (MIT) inside the package, unchanged, and parse with
  `SafeLoader`.
- B: write a subset parser and report files outside the subset as "not checked".
- C: depend on PyYAML (or another parser) as an installed dependency.

Decision: A. Nothing has to be installed, so the PyPI package, the action and the vendored copy keep
working the same way; a full parser can tell a broken file from an unusual but valid one. B gives up
the most valuable check and leaves a parser to maintain. C breaks the vendored copy, which must run
with nothing installed.

How it is kept honest:

- `agentfile_lint/_yaml/` holds every `lib/yaml/*.py` of the sdist except `cyaml.py` (the C binding),
  byte-identical, with the sdist's `LICENSE` and a `PROVENANCE` file that records the source URL,
  SHA-256 and the commands to compare. No line is changed: the package uses relative imports only, and
  its own `except ImportError` absorbs the missing `cyaml.py`.
- Only `agentfile_lint/frontmatter.py` imports it, and only with `SafeLoader` (plain data, no Python
  object tags); `tests/test_architecture.py` checks the first, a test with a `!!python/object` tag the
  second. The vendored code's own imports are not checked for direction.
- The S rules call it with `strings=True`: `SafeLoader` only composes the block (grammar, anchors and
  aliases, no constructor runs) and every scalar is its text. YAML 1.1 type resolution would make
  `description: yes` a boolean and fail on `version: 2026-02-30`; Claude Code's YAML 1.2 parser and
  the reference validator's strictyaml read both as strings, so S1 reports only what does not parse.
- `vendor` copies it with its `LICENSE` and `PROVENANCE`; the wheel ships both.

Costs: 5,789 lines of third-party code whose security fixes this project has to follow (an
upgrade replaces the directory and updates `PROVENANCE`), about 1,700 of them the dump side
(emitter, serializer, representer, dumper) that loading never runs, kept so the directory stays
byte-identical to upstream and an upgrade is a plain replacement; a larger vendored copy; PyYAML implements
YAML 1.1 (`yes` is `true`, `2026-11-06` is a date), so it may judge a few spellings differently from
the JavaScript parser Claude Code uses.

## Reader groups

Options:

- A: every `S` rule belongs to the reader groups it protects: `claude-code` (on by default),
  `agentskills` (claude.ai upload, the Skills API and the specification), or both when both readers
  break the same way (S1 YAML that does not parse, S2 the 500-line guidance); `[skills] targets`
  selects the groups, and a rule none of them reads does not run.
- B: one rule set for every reader, following the specification.

Decision: A, the way ESLint `env`, browserslist and `tsconfig` `target` check against a declared
target. B reports most Claude Code skills as broken. Cost: a user who uploads skills to claude.ai has
to add `agentskills`.
