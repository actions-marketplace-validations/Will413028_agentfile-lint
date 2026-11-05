# Review rubric for instruction files

`agentfile-lint` checks what a program can decide: size, shape, references that must resolve,
text that rots, duplicated lines (each rule and its measured false-positive rate: [docs/rules.md](docs/rules.md)).
This rubric covers what it cannot decide. It is for a human
reviewer or for an agent asked to audit an instruction file (for example an interactive prompt
audit), and it never runs as a CI gate: its answers are not deterministic and the text under review
is untrusted input.

Use it when a pull request changes an `AGENTS.md` or `CLAUDE.md` file. Paste the result (a short
list of findings, or "no findings") into the pull request; see `docs/pr-template-snippet.md`.

## How to review

1. Run `agentfile-lint` first. Do not re-report what it already prints.
2. Read the diff, then the whole changed file; most problems are in how a new line sits next to old ones.
3. For each criterion below, say "ok" or quote the line and say what is wrong. Prefer one concrete
   fix per finding. Stop at the findings that change what an agent would do.

## Criteria

**J1. Earns its place.** Remove the line mentally: would an agent working in this directory do
something different or worse? Delete lines that restate what the code, the tooling or the agent's
defaults already make obvious. Keep only what cannot be seen from the code and must be known before
acting. Enumerations that `ls` or a search already shows (file lists, lists of subdirectories or
modules) do not earn their place.

**J2. Right place.** A rule that applies to one subdirectory belongs in that directory's file; a rule
that applies everywhere belongs in the root file, once. Agents load subdirectory files differently:
some read a subdirectory's file when they touch files there, others read only the files from the
root down to the directory they started in, so a rule an agent must not miss when started at the
root stays in the root file. The linter catches only lines that are identical after collapsing whitespace and dropping list
markers, at least `min_chars` long (R5a and R5b, 40 by default), and skips headings by default; look for
paraphrases, short copies and repeated headings of the same rule at two levels.

**J3. Checkable.** A rule has a way to fail: a test, a CI step, or a command whose output is the
evidence. A rule that needs judgment fails in review instead: name who reviews it, or the criterion
in this rubric that catches it. A rule that nothing can contradict is a wish. Prefer pointing at the
guard by name over describing the behaviour again. A rule with no exceptions belongs in the guard
itself (a hook, a CI step, a test), with the file pointing to it; the file keeps the rules that need
judgment. Style and formatting rules belong in the formatter or linter configuration, not in prose.

**J4. Source of truth, not a copy.** A fact that lives in code, a schema or a spec is referenced, not
repeated. Copied values (limits, durations, lists of names) drift silently. The linter lists
numeric candidates (`R6`: numbers with a unit, numeric assignments, constant names followed by a
number); copied lists of
names are yours to find. Decide whether each one should become a pointer.

## Judgment checks

These are numbered J, not R, so they are never mistaken for a rule the linter runs.

**J5. Contradiction.** Do two instructions, in the same file or in a file and its ancestors, ask for
incompatible things? Does the new text conflict with a rule that is only implied elsewhere?

**J6. Stale or misleading claim.** Does the text assert something that is no longer true (a removed
command, a renamed module, a behaviour that changed)? Reference checks catch missing paths and test
names; they do not catch a sentence that is wrong while every name in it still exists.

**J7. Ambiguity.** Could two careful readers act differently on this line? Look for unscoped
words ("always", "never" with no condition), unstated exceptions, imperatives with no object, and
terms used with two meanings.

## Output format

```
instruction-file review: <path or PR>
J1 ok | J2 ok | J3 <finding> | J4 ok
J5 ok | J6 <finding> | J7 ok
Findings:
- <file>:<line>: <criterion>: <what is wrong>; <suggested fix>
```

Keep it to what the author can act on. "No findings" is a valid result.
