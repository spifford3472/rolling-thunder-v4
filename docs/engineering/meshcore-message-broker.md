# MeshCore Message Broker — Issue #395

## Purpose and deployment state

A single **optional** message broker runs inside the existing independent
`rolling-thunder-meshcore-collector` service. The device, GPS bridge,
passive worker, main contact database, and existing read-only
`/v1/health`, `/v1/nodes`, `/v1/signals`, `/v1/activity` socket API are unchanged.

The code is **disabled by default**. Installing a new Rolling Thunder commit
does NOT start message collection. Enabling requires owner-reviewed, verified
public-channel metadata, a protected bearer-token ACL, separate broker storage,
a second Unix socket, and an explicitly changed service launch invocation.
The existing service unit template does not enable it.

## Why stock firmware is sufficient

Exact installed upstream companion v1.16.0 commit:
`07a3ca9e05b0ab23b878200b2c44b04e08131972`.

- `CMD_GET_CHANNEL` (0x1F, slot) returns a host-local 0x12 response carrying
  slot, name and a **16-byte secret**. The secret is read transiently only to
  compare SHA-256 against a trusted operator-provided digest; it is never logged,
  displayed, stored or added to a public API.
- `CMD_SYNC_NEXT_MESSAGE` (0x0A) returns and **destructively removes** the
  oldest firmware message, which may be public, private or binary. The code
  path has no direct radio transmission. It remains a **local serial command**,
  not a radio send. Independent firmware-managed RF remains unchanged.
- Legacy channel text uses 0x08; v3 uses 0x11. Private contact messages use
  0x07 or 0x10; group binary uses 0x1B. The broker never uses contents to
  infer privacy classification before recognizing a valid protocol response.
- The firmware's fixed 32-byte channel name may contain stale padding bytes
  after the NUL: matching uses only bytes before the terminator and an exact
  independent key digest; this is source-audited and regression-tested.
- No host-generated announcements, ACKs, broadcast messages, discovery, trace,
  PTT/CAT, or user-message replies can be initiated by the broker. It can emit
  only framed serial commands `< 02 00 1F <slot>` and `< 01 00 0A`.

This avoids a custom firmware fork, at the cost of an explicit **at-most-one
dequeued but not yet committed message** window if sudden power loss occurs
between firmware removal and the SQLite commit. The operator explicitly
accepted this limitation; there is no false exactly-once claim. On commit
failure, timeout, channel mismatch or full inbox, the controller stops
sending further dequeue commands and reports a fault. It does not blindly
retry an uncertain pop. Subsequent reconnect reattests channel identities.

## Durable architecture

The existing `meshcore-collector.service` remains the sole USB port owner.
The optional `MeshcoreBrokerDrain` executes on that serial thread; it
interleaves existing passive frames with a **single outstanding command**.
A push 0x83 or initial startup requests a bounded drain. After each response
the broker performs a **synchronous FULL SQLite transaction** before the next
0x0A can be sent. Up to 16 consecutive retrieves are followed by a yield,
so passive observation remains responsive.

`MeshcoreMessageBroker` has its **own isolated SQLite schema 1 database**,
not the existing observation/QSO database. Its streams are:

| Stream | Stored content | Access |
| --- | --- | --- |
| `public` | UTF-8 text, observed time, untrusted sender timestamp, exact verified channel slot/name | Approved public consumers |
| `private` | Original opaque contact/DM frame, never parsed as public | Explicitly authorized personal consumers |
| `quarantine` | Original opaque untrusted/unverified channel, binary or unknown frame | Operator-only consumer |

No raw packet from unsolicited 0x88 is persisted in the broker. Only an
actual firmware dequeued message enters the inbox. Invalid or unverified
channel text is quarantined; appearance of a hashtag is **not** channel
attestation. Sender identity is unverified by channel frame provenance.

An allowlisted consumer can `peek` without taking another consumer's
message, and acknowledge a message using its independent durable
`(consumer, stream)` cursor. Reconnect/restart reuses its cursor. No
consumer is allowed to delete messages. Acknowledging a public message
does not alter personal delivery or another public consumer's cursor.

Capacity defaults to **25,000 messages or 32 MiB**. The broker does not
silently prune private messages. When capacity is reached, draining stops
and an operator must review retention/cursor backup before any deletion.
The database and parent directory must be mode 0600/0700 respectively.
SQLite `synchronous=FULL` and `secure_delete=ON` are used.

**Privacy limitation:** the database is protected by Linux filesystem
permissions and distinct token-scoped API access, but **not encrypted at
rest**. Local root, backups, or compromise of the `geoff` account can expose
personal messages. Do not publish or sync this file to Forge/cloud or permit
other host identities without an additional approved encryption policy.
The private stream is not served through the legacy observation API.

## Independent local consumer API

A separate owner-only Unix socket, e.g.
`/run/user/1000/meshcore-broker.sock`, exposes:

- `GET /v1/status` — counts only for caller-authorized streams;
- `GET /v1/messages/public?limit=25` — bounded public delivery;
- `GET /v1/messages/private?limit=25` — requires private capability;
- `GET /v1/messages/quarantine?limit=25` — requires operator capability;
- `POST /v1/ack` with `{"stream":"public","message_id":123}` —
  advances only the authenticated consumer's cursor.

All broker calls require `Authorization: Bearer <high-entropy-token>`.
The server derives consumer identity from the token fingerprint using a
constant-time comparison; it does **not** trust a supplied consumer name or
arbitrary URL path. Public and personal consumers use different tokens.
Raw personal/quarantine responses are base64 encoded and carry
`Cache-Control: no-store`. Invalid tokens return 401, unauthorized
streams 403, and bulk writes/deletions 405. The existing observation socket
remains read-only and adds only the optional `GET /v1/broker-health`
status when the broker is enabled. No TCP port or firewall rule is needed.

## Opt-in installation prerequisites

Do not activate from a moving vehicle. Verify current exact production
commit, recorded SQLite backups, collector health, GPS, and USB identity.
The operator must identify and authorize actual public channels. Never
invent a channel index based on the label `#traffic` or `#skywarn`.
Use the physical radio's own configured channel list, then verify the
runtime identity through the channel-info response before draining.

Create an owner-only JSON configuration at
`/home/geoff/.config/rolling-thunder/meshcore-broker.json` with schema:

```json
{
  "schema": "meshcore/broker-config/v1",
  "approved_channels": [
    {
      "slot": 3,
      "name": "#traffic",
      "secret_sha256": "<64 lowercase hex SHA-256 digest of actual 16-byte channel key>",
      "approved_for_public_intake": true
    }
  ],
  "consumers": [
    {
      "name": "rolling-thunder",
      "token_sha256": "<64 lowercase hex SHA-256 of independent random bearer>",
      "streams": ["public"]
    },
    {
      "name": "operator",
      "token_sha256": "<different 64 lowercase hex digest>",
      "streams": ["private", "public", "quarantine"]
    }
  ]
}
```

**This is a shape example, not a claim that slot 3 is the configured
traffic channel.** Fingerprints are not plaintext channel secrets; bearer
tokens themselves must be generated with a CSPRNG and delivered privately
to each consumer (never GitHub, logs, CLI argument history or chat).

The service CLI adds `--enable-message-broker` and requires *all* of:

```text
--broker-config /home/geoff/.config/rolling-thunder/meshcore-broker.json
--broker-database /home/geoff/.local/share/meshcore-collector/meshcore-messages.db
--broker-socket /run/user/1000/meshcore-broker.sock
```

Omitting the enable flag and paths retains passive behavior. A partial
configuration fails before USB or existing SQLite is accessed. Activation
needs a separately approved systemd drop-in or reviewed service invocation;
no new unit has been installed by the code change itself. The existing
unit's `UMask=0077` and `ReadWritePaths` already encompass the example
data and runtime socket paths. The separate configuration file must be
mode 0600, owner `geoff`.

## Testing and acceptance

Run `ruff check .`, `mypy src/rolling_thunder`, `pytest`, and
`git diff --check` on the exact branch and GitHub CI before merging.
Hardware-free tests cover owner-only file permissions, fingerprinted
authorization, private and public streams, quarantine, independent
acknowledgements, restart durability, capacity failure, serial fake commands,
full frame decoding, channel mismatch, timeout, no-more and reconnect.

Live parked validation requires a **separately authorized activation** of
the above service options after verifying real channel index/name/digest.
Only a read-only source deployment is safe before then. Record the exact
previous SHA and production backup, prove that observations, GPS, FT8 and
dashboard remain healthy, verify both Unix sockets' 0600 mode, ensure
the private stream cannot be requested with a public token, and exercise
unexpected power loss/SQLite failure with synthetic fakes before considering
the feature complete. No on-air transmissions are part of this acceptance.

## Rollback and change history

Rollback the application via the approved
`/usr/local/sbin/rolling-thunder-deploy <previous-exact-SHA>` wrapper;
do not overwrite current observation or message databases with older
copies. For an activated broker, remove its reviewed systemd drop-in
using the saved previous configuration and restart only while parked.
Preserve the private message DB for later recovery; never publish it.

- 2026-11-11: initial v1.16 firmware audit and strict non-actuating
  decoder merged in PR #401.
- 2026-11-11: broker design accepted with the dequeued-before-commit
  power-loss risk. Added isolated SQLite inbox, bounded serial
  single-flight drain, verified public-channel gate, capability-scoped
  local Unix API, disabled-by-default startup, offline tests and runbook.
  No firmware changes or RF transmit support.
