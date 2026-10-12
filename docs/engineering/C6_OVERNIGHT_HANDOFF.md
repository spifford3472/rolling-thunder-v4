# C6.2-C6.4 overnight handoff

Updated: 2026-10-12 UTC. Branch:
`feature/voacap-c62-c64-overnight`, based on
`ddf6741bb33fc544a90ab3871e15839739ed2ce7`.

## Production state and go/no-go

Production is unchanged. No sudo, deployment, service action, protected database
write, provider POST, public network request, Pi access, CAT/PTT action, RF
transmission, merge or gate change was performed. The installed sampler's three
gates remain outside this worktree and were not inspected or changed.

Unattended C6.4 activation: **NO-GO**. Controlled provider pilot: **NO-GO until a
separate explicit one-request authorization and the prerequisites below**.

## Implemented checkpoints

1. C6.2 SSN boundary: `forge_solar_ssn.py` accepts only a strict normalized
   monthly-smoothed-observed SSN contract, validates bounded/fresh/non-future source
   provenance, stores immutable snapshots and rejects changed source-record replay.
   Its query-only HamQSL audit labels raw `sunspots` ineligible and cannot create a
   smoothed snapshot.
2. Audited plan tooling: `rolling-thunder-forge-voacap-plan` fixes origin to
   `EM79xm`, requires an explicit one-to-eight-target reviewed inventory, retains
   uncertainty and lineage, and produces a one-POST/10-second/one-attempt pilot plan.
   It defaults to dry-run/no-write and refuses artifact overwrite.
3. Prospective scheduling correction: clocks are converted to UTC before choosing
   complete future days, including local-offset/DST midnight boundaries.
4. Controlled pilot staging: exact approval phrase, all-three-gate validation,
   strict plan-bound checks, pre-run consistent SQLite backup plus integrity/foreign
   key verification, backup SHA-256/rollback output, pre-POST exact version guard and
   a hard adapter one-POST cap.
5. Offline integration/sandbox tests: real urllib request framing uses an in-memory
   fake socket (zero egress); systemd assertions preserve the dedicated identity,
   strict filesystem boundary and loopback-only IP policy. Installer ordering tests
   require world-readable/traversable immutable venv files and a successful CLI
   preflight before the current link or systemd units can change.

Commit SHAs and PR: no new commit or PR. The completed checkpoint could not be
committed because this managed session exposes the linked worktree Git index at
`/home/geoff/projects/rolling-thunder-v4/.git/worktrees/rolling-thunder-v4-voacap-overnight`
read-only; Git failed creating `index.lock`. Source files remain safely modified in
this isolated worktree. No permission change or sandbox bypass was attempted.

## Validation at this checkpoint

Focused tests: 43 passing after the implementation above (command uses
`PYTHONPATH=src /home/geoff/projects/rolling-thunder-codex/.venv/bin/pytest`). Full
full Ruff and strict MyPy (330 source files) pass, and `git diff --check` passes.
Full pytest completed with 3,289 passed, 7 skipped and 3 failures. All three failures
are unrelated existing live-loopback HTTP tests whose socket creation is prohibited
by this managed sandbox (`PermissionError: Operation not permitted`):
`test_real_http_framing_completes_without_waiting_for_connection_close`,
`test_live_http_handler_reads_bounded_post_body`, and
`test_live_http_contract_on_disposable_local_db`. Pre-commit Ruff and MyPy passed;
its pytest hook reproduced only those same three sandbox socket failures. The
temporary ignored `.venv` symlink used to satisfy the repository hook paths was
removed by the command trap.

## Deliberately unresolved source contract

No authoritative NOAA/SILSO public wire schema was asserted from memory. The new
JSON contract is an internal provider-neutral normalization boundary, not a claim
that an upstream publishes that shape. Tomorrow's exact safe action is to review an
authoritative upstream specification/sample and revision policy, then implement a
provider-specific adapter mapping it into `SmoothedSsnSnapshot` with captured fixture
tests. Confirm that monthly smoothed *observed* SSN is the intended VOACAP input for
the forecast month; if a predicted monthly series is required, introduce a separate
semantic instead of relabeling observations.

## Next safe actions

1. Review the SSN upstream contract and scientific choice above; do not fabricate a
   current value or use HamQSL raw counts.
2. Supply/review the small regional target manifest, uncertainty text, plan UUID,
   version and parent ID. Run the plan command without `--apply` first.
3. Review the controlled-pilot database backup directory and disposable/production
   rollback procedure. Obtain explicit authorization for exactly one provider POST.
4. If authorized later, run one pilot only; require version 0.3.0, one ready future
   pre-choice slot, immutable response/provenance and restored OFF gates afterward.
5. Design/review C6.4 cadence, retry/storage health thresholds and offline recovery
   only after successful pilot evidence. Do not activate it as part of this branch.

The staged C6.4 plan in `voacap-ft8-phase-c6.md` now enumerates the child-plan,
cadence, call/retry/storage caps, provider-free health, bounded offline recovery,
go/no-go and rollback requirements. It creates no schedule and grants no activation.
