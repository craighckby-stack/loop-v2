# Etiquette: how loop-v2 may be used

This document is normative. The tool enforces every rule here in code
(`loop/etiquette/guards.py`); this page explains the reasoning and the
social contract behind them.

## The problem

A tool that autonomously proposes changes to other people's repositories
can easily become a nuisance: spam PRs, noise in review queues, wasted
maintainer time. Several bot ecosystems have already been blocked wholesale
by maintainers for exactly this. loop-v2 is built so that cannot happen.

## Rule 1: consent is required, always

The loop only runs against a repository whose **default branch** contains a
`.loop-consent` file with `consent = true`. No marker, no run — the engine
refuses before touching anything.

The marker is maintained by the repo's maintainers, not by the loop
operator. This is the crucial property: the people who would receive the
PRs are the people who decided to receive them.

Deleting the marker, or setting `consent = false`, revokes consent at any
time. The next cycle simply refuses.

## Rule 2: the repo's own tests are the only eval

The tool never decides a mutation is "good" by its own judgement. It runs
the repository's own test command before and after the mutation:

- if the repo's tests already fail, the loop declines to run at all
  ("broken baseline" — it will not pile changes onto a broken tree);
- a mutation ships only if the tests pass after it, with the same return
  code as the baseline;
- if no test command can be detected, nothing ships (fail closed).

This means the loop can never argue with a maintainer about whether a
change is an improvement. The repo's own CI semantics decide.

## Rule 3: hard rate limits

Per target, the tool enforces both:

- `max_runs_per_day` (default 2) — cycles per calendar day;
- `max_prs_per_week` (default 3) — emissions per ISO week.

The consent file may tighten these further (`max_prs_per_week = 1`); the
tighter limit always wins. These are ceilings, not targets. If a maintainer
asks for less, the answer is less.

## Rule 4: every change is attributable

Every commit the tool creates carries git trailers:

```
X-Loop-Tool: loop-v2/0.1.0 (opt-in autonomous code-improvement)
X-Loop-Stop: reply 'loop-stop' to make this tool never touch this repo again
```

Every run appends to a write-once provenance log: run id, upstream commit,
strategies, gate verdicts, emitted artifact (see `provenance-schema.md`).
A maintainer can always answer "what touched my code, and why".

## Rule 5: stopping is one action, and permanent

Maintainers stop the tool by any of:

1. replying `loop-stop` to any emitted PR (recorded in provenance via
   `loop stop <target-dir> <owner/name>` — permanent for that repo);
2. removing the `.loop-consent` marker;
3. being listed in the blocklist shipped with the tool.

A `loop-stop` is never undone by the operator unilaterally. If a maintainer
wants to re-opt-in later, they add the consent marker back and explicitly
clear the stop record.

## Rule 6: respect licence and attribution

The tool only proposes changes; licences govern the resulting derivative
work as usual. Operators pointing the loop at a repo with a CLA/DCO are
responsible for satisfying it — when in doubt, don't run against that repo.
The tool never claims authorship of the underlying code: PR bodies state
plainly what was generated and how it was evaluated.

## Operator checklist

Before pointing loop-v2 at a repo you do not own:

- [ ] the repo carries a valid `.loop-consent` marker (ask for it, never
      add it yourself to someone else's repo);
- [ ] the repo's licence/CLA is compatible with machine-proposed changes;
- [ ] rate limits are set to the minimum the maintainer asked for;
- [ ] `emit = "patch"` first; only switch to `"pr"` once the maintainer
      has seen and accepted sample patches;
- [ ] you can be reached at the contact the maintainer knows about.

## What this tool will never do

- run against a repo without consent, no matter how "safe" the change;
- bypass a failing gate by weakening the eval;
- push directly to a default branch (emission is patch/branch/PR only);
- flood: caps are hard, checked from provenance, and tightened by consent.
