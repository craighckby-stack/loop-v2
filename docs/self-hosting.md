# Self-hosting loop-v2

Phase 1 ships as a CLI you run yourself, against repos you have a right to
touch. This page is the operating manual, plus the roadmap to hosted shapes.

## Running it

Requirements: Python 3.11+, git. No third-party Python dependencies — the
engine is stdlib-only by design (small attack surface, trivial installs).

```bash
pip install .                     # or: python -m loop.cli ...
loop init-target targets/my-repo --local-path /path/to/repo
loop check targets/my-repo
loop run targets/my-repo
loop report targets/my-repo
```

State layout (all local, nothing phones home):

```
<runs-dir>/                       # default: next to the target bundle
  provenance.jsonl                # append-only log (see provenance-schema.md)
  <run-id>/
    working-copy/                 # deleted after the cycle unless --keep-working-copy
    <run-id>.patch                # the emitted patch, when emit = "patch"
```

## Scheduling

The CLI is one-shot. Wrap it in cron/systemd timers if you want recurring
cycles:

```systemd
# ~/.config/systemd/user/loop-my-repo.timer
[Timer]
OnCalendar=daily
Persistent=true
```

The rate limiter still applies on top of any schedule — daily cron with
`max_runs_per_day = 2` just means every second run is refused. If you want
one run a day, set the timer AND the cap to match; the caps exist for when
your scheduler misbehaves.

## GitHub targets

```toml
[target]
id = "some-repo"
provider = "github"
repo = "owner/name"          # upstream to clone
fork = "you/your-fork"       # where branches are pushed (defaults: same repo)
emit = "pr"
```

- `LOOP_GH_TOKEN` must be set for `emit = "branch"|"pr"` — a token with
  push access to the fork and PR access to the upstream.
- The token is read from the environment at call time and never stored by
  the tool. Scope it minimally; a fine-grained token limited to the fork
  repo is the right shape.
- PRs are opened via the GitHub REST API with no extra permissions.

**The consent marker must be on the upstream's base branch.** If you own
both, add `.loop-consent` to the upstream. If you do not own the upstream,
ask — the marker is the maintainer's decision, never yours.

## Security notes for operators

- The gate executes the target repo's test command inside the working copy.
  Treat every run like running a stranger's CI: use a container or a
  dedicated user if the target is not fully trusted, and mind `post-commit`
  hooks (pass `--keep-working-copy` consciously).
- Provenance logs record upstream commit ids and file names, not file
  contents — safe to keep, useful to share.
- If you operate the tool for a team, share the provenance log and the
  blocklist, not tokens. Each operator brings their own credentials.

## Roadmap: from CLI to hosted

1. **Phase 1 (this repo): CLI, self-hosted.** You run it against repos you
   control or have consent for. Liability, tokens and scheduling stay with
   you. This is the safe default.
2. **Phase 2: more language adapters** — Go, TypeScript/JavaScript via
   tree-sitter or native parsers; same gate model (`go test`, `npm test`).
3. **Phase 3: GitHub App.** Maintainers install the app on repos they own;
   consent becomes the install itself, plus the marker. Rate limits and
   blocklist enforced centrally by the app.
4. **Phase 4 (deliberately deferred): hosted "any repo" submission.** Not
   built until etiquette, caps and blocklists are battle-tested. A hosted
   autonomous-PR service without a strong trust model becomes spam
   infrastructure; we will not ship that.
