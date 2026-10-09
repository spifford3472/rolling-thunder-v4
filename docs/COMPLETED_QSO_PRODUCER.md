# Durable Completed-QSO Producer Contract

## Status and scope

`completed_qso_producer.py` defines the Pi-owned post-durability boundary for
optional completed-FT8 analytics. It is production-composed behind explicit
disabled-by-default application and per-receiver gates. Enabling it constructs an
independent SQLite outbox, authenticated VOACAP and/or PSK Reporter ingestion
client, and a bounded background scheduler. There are no new operator controls.

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
Production composition uses the reviewed receiver clients:

- VOACAP: `POST /api/v1/completed-qsos`, complete `Contact`, bearer token, and
  `Idempotency-Key: <contact_id>`;
- PSK Reporter: `POST /api/v1/completed-ft8-events`, complete event, a distinct
  bearer token, and the same idempotency key.

The two high-entropy bearer credentials are independent
`ROLLING_THUNDER_COMPLETED_QSO_VOACAP_TOKEN` and
`ROLLING_THUNDER_COMPLETED_QSO_PSKREPORTER_TOKEN` values loaded from the protected
runtime environment file rather than YAML/Git and used only across the private
WireGuard path or TLS. A receiver's accepted or replay acknowledgement must match
the submitted UUID before its outbox destination is marked delivered. HTTP 409,
authentication failure, timeout, malformed acknowledgement, and uncertain network
outcome remain retryable locally; receiver UUID idempotency makes those retries safe.

## Configuration and rollout dependency

`ft8.completed_qso_delivery` owns the global gate, separate outbox path, scheduler
interval, batch and retry bounds, and independently gated VOACAP/PSK endpoints.
The runtime creates no outbox, client, or scheduler while the global gate is false.
When enabled, FT8 must also be enabled, at least one receiver must be selected, and
that receiver must have both an endpoint and its protected bearer credential.

The delivery scheduler starts with application background services and stops before
the existing performance/contact synchronization services. It never runs from the
FT8 terminal callback or Tk thread. Provider-free integration tests cover delayed
transport invocation, distinct authentication, wrong-UUID acknowledgement, and
independent destination progress. Forge process, ingestion, and provider gates still
require separate owner authorization and live private-network acceptance.

Do not route analytics through contact sync/Wavelog. Source composition does not
install or activate either Forge service, authorize provider requests, or provision
production secrets.
