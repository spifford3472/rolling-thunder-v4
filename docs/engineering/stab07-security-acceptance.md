# STAB-07B — Offline security acceptance and remaining live safety gates

**State: offline candidate only / parked production NO GO** (2026-11-14).
Nothing in this work authorizes merging, installation, a systemd restart,
SQLite mutation, radio control, or RF transmission.

## Observed as-built facts (read-only)

- AnvilMobile's system service was observed active with MainPID `60400`,
  `User=geoff`, and four listed drop-ins. The root deployment wrapper is
  mode `0750` owned by root; protected `60-ft8-period.conf` is mode `0600`
  owned by root. The restricted read-only remote account cannot hash or read
  the protected originals. No change to sudoers or root file permissions.
- The operator's earlier wrapper copy SHA256 is
  `476ecdbdbcc70bcb1025ac1ce97bae1982b98d8842d5e333ea43632378512daf`.
  **Equality with the installed privileged original has not been verified.**
- The service can expose an XDG user runtime directory, which is a necessary
  but insufficient Tk-heartbeat prerequisite. The uninstalled code has not
  been observed operating on the real Pi; a green GitHub test is not field
  acceptance.
- The real FT8 UI's unlock path supplies a constant
  `radio_confirmed_receive=True`. This is a **hardware safety blocker**:
  pressing the 1-3-1 sequence or issuing CAT `TX0;` cannot independently prove
  physical de-key. Do not claim this is resolved by security work.

## Trust-boundary correction to candidate recovery authorization

Previous STAB-06F accepted a private JSON file without checking an issuer's
cryptographic signature. That could not authenticate owner approval. This
branch changes the uninstalled reconciler to require a detached **Ed25519**
signature on canonical JSON (
`json.dumps` with sorted keys, compact separators, ASCII escaping and with
`signature_b64` omitted). It verifies using OpenSSL 3's `pkeyutl -verify`,
passing message and signature only through Linux memory-backed descriptors,
with a bounded execution timeout. No application/database/service operation
occurs on verification failure.

Signed receipt scope is strictly:

- schema `version=1`, project `spifford3472/rolling-thunder-v4`,
  `target_host=anvilmobile` and action
  `decision=attest_existing_running_release`;
- exact transaction ID, expected SHA, SHA256 digest of a freshly collected
  inspection report, explicit independent running-identity attestation text,
  separate approval ID, issued-at and expires-at timestamps;
- issuance not in the future, expiry not passed, lifetime at most 300 seconds;
- base64 Ed25519 signature from the **independently trusted signer**.

Verification key must be root-owned, non-symlink, in a root-owned and
non-group/world-writable parent, and located at
`/etc/rolling-thunder/approver-ed25519.pub`. The private signing key must
**never** be placed on AnvilMobile or in Git, logs, or ChatGPT messages.
Signing, owner authentication, key rotation/revocation, replay logs and issuer
approval auditing belong to a separately approved **SpiffBridge** (or equally
trusted) authorization boundary; no key was generated or installed as part of
this change. Test keys are disposable local fixtures only. A handwritten
receipt, unsigned JSON, forged signature, wrong project/host, unknown key,
excessive TTL, unsafe key file or changed evidence fails closed. A signature
proves the trusted signer's approval of bytes, **not** physical radio RX or
independent runtime SHA correctness.

## Root-owned wrapper and protected FT8 drop-in inspection

`deploy/diagnostics/rt-stab07-readonly-evidence.py` is a **noninstalled**
read-only evidence collector designed for a separately authorized, interactive
on-device inspection. It computes SHA256 of the installed root wrapper, its
operator-authorized captured copy, and protected drop-in; compares wrapper
identities and reports only the protected unit's directive *names*, never
values, environment secrets or drop-in content. It returns NO GO if protected
reads fail, files are unsafe or wrapper hashes differ. Even matching hashes do
not verify deployability, and directive names do not validate protected FT8
configuration values. The owner must review the protected values locally and
safely; never paste credentials into ChatGPT.

No privileged read was attempted through sudo expansion, and this collector
has not been executed on AnvilMobile. The repo-local script's ownership and
runtime path must be considered before any owner-approved execution; this is
not a production installation procedure.

## Remaining evidence and safety prerequisites

1. **Owner-authorized local read-only evidence:** independently hash the
   installed wrapper and capture, inspect protected FT8 drop-in values with
   secrets redacted, validate service unit and drop-in expansion and preserve
   exact source hashes. Any mismatch is NO GO.
2. **SpiffBridge signer integration:** verify the external issuer is actually
   connected, authenticated, authorizes this project/host/operation, audits
   receipt issuance and enforces expiry, nonce and key rotation. This branch
   includes the verifier only, **not** the issuer or host installation.
3. **Independent runtime identity:** do not rely on an editable checkout HEAD,
   `MainPID`, or a signed string supplied by the operator as sole evidence
   that *loaded Python code* is the reviewed release. Design and validate an
   independent exact-SHA runtime attestation under pinned release paths.
4. **SQLite/WAL:** obtain an owner-approved consistent parked snapshot and
   test integrity, rollback schema constraints and preservation of every QSO
   and newer record. Immutable read-only mode correctly refuses a live WAL;
   do not weaken this refusal or overwrite the active database.
5. **FT8/PPT receive and shutdown:** independently establish physical radio
   RX, proper lockout, failed `TX0;` behavior and bounded shutdown while parked.
   The existing constant confirmation flag requires a separately reviewed
   fail-closed correction and physical acceptance; do not claim test evidence
   proves de-key. No live RF authorization is granted here.
6. **Installation/release:** require separate owner approvals for source
   merges, privileged helper/key installation, production restart/deployment
   and RF. Record configuration paths, integrations, jobs, validation,
   rollback and change history in
   `spifford3472/ki5vnb-qth-infrastructure` before any relevant host change
   is considered complete.

## Tests and change history

`tests/test_recovery_reconciliation.py` now uses disposable Ed25519 keypairs
and refuses unsigned, tampered, forged, wrong-scope, expired, overlong or unsafe
keys while preserving the journal. `tests/test_stab07_privileged_evidence.py`
verifies hash comparison, symlink refusal and redaction using only temporary
files. No production/privileged path is called in tests.

2026-11-14: Added offline cryptographic verification boundary and protected
metadata evidence design. Revert this branch for rollback; no installed host
state changed. Live deployment decision: **NO GO**.
