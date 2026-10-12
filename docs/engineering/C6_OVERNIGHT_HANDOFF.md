# C6 NOAA forecast-SSN implementation and safety-review handoff

Updated: 2026-10-12 UTC. Review branch:
`feature/c6-noaa-forecast-ssn-review`, starting from PR #318 head
`0c21a86c6f70f5fc4742fc216ef2bbac267e9f67`.

## Production state and go/no-go

Production is unchanged. No sudo, deployment, service action, protected database
write, provider POST, public network request, Pi access, CAT/PTT action, RF
transmission, merge or gate change was performed. The installed sampler's three
gates remain outside this worktree and were not inspected or changed.

Unattended C6.4 activation: **NO-GO**. Controlled provider pilot: **NO-GO until a
separate explicit one-request authorization and the prerequisites below**.

## Implemented checkpoints

1. C6.2 SSN boundary: `forge_solar_ssn.py` now implements the published NOAA/SWPC
   `predicted-solar-cycle.json` array contract. It selects exact-month
   `predicted_ssn`, retains raw bytes/hash and obtainable HTTP headers, records
   capture while leaving unprovable release unknown, and appends mutable-feed
   revisions. NOAA observed `smoothed_ssn` and HamQSL raw counts are ineligible.
2. Audited plan tooling: `rolling-thunder-forge-voacap-plan` fixes origin to
   `EM79xm`, requires an explicit one-to-eight-target reviewed inventory, retains
   uncertainty and lineage, and produces a one-POST/10-second/one-attempt pilot plan.
   It defaults to dry-run/no-write and refuses artifact overwrite.
3. Prospective scheduling correction: clocks are converted to UTC before choosing
   complete future days, including local-offset/DST midnight boundaries.
4. Controlled pilot staging: exact approval phrase, all-three-gate validation,
   strict plan-bound checks, pre-run consistent SQLite backup plus integrity/foreign
   key verification, backup SHA-256/table counts/rollback output, durable success or
   failure audit, pre-persistence provider identity/version guard and a hard adapter
   one-POST cap that survives timeout/ambiguous outcomes.
5. Candidate/response safety: no slot is created until SSN semantic, target month,
   complete source identity/freshness, canonical raw snapshot match and provider
   preflight pass. A ready row and
   cached response require exact model/service versions, bounded response and one
   unique requested hour/band cell with finite reliability and SNR.
6. Offline integration/sandbox tests: real urllib request framing uses an in-memory
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

## NOAA verification evidence and remaining limitation

NOAA's product page documents a multi-year forecast of smoothed monthly sunspot
number and identifies `time-tag` as `YYYY-MM` and `predicted_ssn` as predicted sunspot
number. The data index reported the current JSON at about 17 KB. A bounded direct
GET was attempted, but this managed sandbox could not resolve
`services.swpc.noaa.gov`; therefore no live value, response bytes or issuance time is
claimed in this handoff. Tests use a strict published-schema fixture. A future live
capture must go through the bounded HTTPS adapter and append its actual bytes/headers.

## Next safe actions

1. Perform one read-only NOAA capture in an environment with working DNS, inspect the
   retained headers/schema/hash, and do not infer an issue time absent explicit proof.
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
