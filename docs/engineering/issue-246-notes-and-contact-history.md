# Issue246 implementation and acceptance plan

Baseline: d0378f3d20755920f4e73becb55e4e6d5f08330e. Owner authorizes development,
testing, merge and deployment on October29. Scope: ordinary new QSO notes blank;
shared callsign popup shows true worked count and last band, keeping FIRST CONTACT.
No radio, FT8 state machine, database migration or historical contact rewrite.

Owners: contact metadata/commit plus shared Wavelog serialization; Forge history
adapter/service; shared immutable callsign models and pure Pi presentation. Existing
POTA/DX/Browse/FT8 consumers and retry contracts must remain intact. Tests cover
blank and explicit notes, historical claimed-payload retries, exact-call full totals,
missing history data, no notes in the popup and old/new response compatibility.
Run Ruff, strict MyPy, pytest and diff check, exact-head CI, then approved wrappers.
Rollback source/components without reverting newer contacts or ledger rows. Upgrade
Pi readers before the expanded callsign-info response; no spots/VOACAP deployment.

Qwen-first: rt-code local-only run 20261029T140115455896Z-issue246-blank-notes
was bounded and stopped through launcher SIGINT after no output or actual diff.
The initial task was already limited to notes; reducing it to a helper would not
address the discovered durable payload compatibility boundary. Coordinator handles
the integrated correction and independently verifies it; no Qwen artifact accepted.

## Implemented contract and validation

The deployed Wavelog3.2.3 PHP contract was read without mutation: Qso_resource::index
counts exact-call filtered results across token-visible station IDs; JSON defaults
to newest-first and meta.total remains the full total under limit=1. The adapter
reuses that single request and existing cache; missing count/band is unknown and
invalid/contradictory totals fail closed. Pi publishes no additional provider work.

Ordinary POTA/Browse metadata no longer synthesizes notes; explicit supplied text
is preserved, including existing DMR workflow metadata. Weather stays structured
but is not appended to new Wavelog notes. No existing notes/rows are cleared.
For an existing durable claim only, contact-sync accepts the exact original legacy
notes rendering when its full station+ADIF hash matches the original claim. Pending
retries upload identical old ADIF and synchronized replays stay no-ops. Different
payload/station identities still fail; claim hashes are never updated. No schema
migration, new service, configuration option or dependency is introduced.

Validation: 139 focused tests; full3595passed/7skipped; Ruff; strict MyPy348files;
diff check. Actual Tk font metrics on Forge measured representative heading883px
and detail1433px within3044px available on the installed3840px display. This is
layout sizing evidence, not an installed operator screenshot or live QSO test.

Rollout order: approved contact-sync wrapper, approved Pi wrapper, then approved
callsign-info wrapper; verify exact sources and health independently. New Pi accepts
old Forge unknown history fields; older strict Pi readers reject the new response.
Rollback callsign-info first, then Pi/contact-sync as needed, retaining newer DBs.
The generic contact-sync runbook's historical station-routing RF/contact acceptance
is not rerun for unchanged routing; deterministic replay tests cover this notes
change and live read-only history/health checks follow rollout. No synthetic QSO is
inserted into production for testing. Owner merge/deploy authority is explicit.
