# Durable Completed-QSO Producer Contract

## Status and scope

`completed_qso_producer.py` defines the Pi-owned post-durability boundary for
optional completed-FT8 analytics. It is deliberately not production-composed in
this branch: there are no endpoints, secrets, provider calls, service changes, or
new operator controls. The contract can be injected into `ApplicationRuntime` for
offline acceptance, but automatic delivery must wait for the independent VOACAP
and PSK Reporter receiver changes to merge and stabilize.

The local QSO and terminal attempt remain authoritative. Analytics delivery has no
radio, transmit, logging, contact-sync, Wavelog, or provider authority.

## Required terminal ordering

For a successful terminal FT8 result, runtime ordering is:

```text
durably commit Contact under the stable QSO UUID
    -> durably commit matching successful FT8PerformanceAttempt
    -> validate the combined CompletedFt8QsoEvent
    -> durably enqueue that event in the producer SQLite outbox
    -> return from terminal handling

separate bounded background worker
    -> authenticated VOACAP ingestion (Contact only)
    -> authenticated PSK ingestion (complete event)
```

The producer is never invoked when contact logging failed, performance persistence
failed, the terminal result was unsuccessful, the UUIDs differ, or the immutable
callsign/start/frequency contract differs. Producer enqueue failure is logged after
the authoritative records are durable and must not roll them back or change the
radio result.

Only the short local SQLite enqueue is permitted at the terminal boundary. DNS,
HTTP, bearer authentication, retry sleeps, receiver processing, and every provider
request belong to the independently scheduled delivery and Forge workers.

## Local outbox and replay

One immutable JSON event is keyed by `Contact.contact_id`, which is also the FT8
attempt UUID. Both destination states live beside that single event:

- VOACAP receives the complete frozen `Contact`;
- PSK Reporter receives the complete `CompletedFt8QsoEvent` containing the same
  contact and successful terminal attempt;
- a successful destination is never redelivered merely because the other failed;
- failures retain bounded error text and use restart-safe exponential retry;
- restart reopens the same pending/retry rows;
- exact source replay is accepted; and
- changed event data under the UUID fails closed before either destination is used.

Receiver acknowledgement means only that the receiver durably accepted the event.
It does not mean VOACAP or PSK Reporter provider work succeeded.

## Transport and authentication dependency

The delivery worker accepts typed sink protocols and performs no provider calls.
Production composition must use the reviewed clients from the receiver branches:

- VOACAP: `POST /api/v1/completed-qsos`, complete `Contact`, bearer token, and
  `Idempotency-Key: <contact_id>`;
- PSK Reporter: `POST /api/v1/completed-ft8-events`, complete event, a distinct
  bearer token, and the same idempotency key.

The two high-entropy bearer credentials must be independent, loaded from protected
runtime environment files rather than YAML/Git, and used only across the private
WireGuard path or TLS. A receiver's accepted or replay acknowledgement must match
the submitted UUID before its outbox destination is marked delivered. HTTP 409,
authentication failure, timeout, malformed acknowledgement, and uncertain network
outcome remain retryable locally; receiver UUID idempotency makes those retries safe.

## Merge and rollout dependency

The integration PR should follow both independent receiver PRs, not precede them.
After both merge, rebase this branch and add a small composition-only follow-up that:

1. uses the merged typed VOACAP client and the final PSK client/API response;
2. adds disabled-by-default Pi endpoint/interval/batch configuration and protected
   secret-environment names;
3. constructs the local outbox adapter and background scheduler only when explicitly
   enabled;
4. starts delivery after local services and stops it before persistence teardown;
5. verifies receiver UUID acknowledgements and keeps the destinations independent;
6. performs provider-disabled authentication, replay, restart, and outage acceptance;
   and
7. separately obtains authorization for either Forge service or provider gate.

Do not resolve this dependency by copying provisional receiver transports into the
Pi or by routing analytics through contact sync/Wavelog. No service installation,
activation, provider request, or production secret change belongs to this PR.
