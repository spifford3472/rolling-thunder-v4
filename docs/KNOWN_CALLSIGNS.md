# Forge known/friend callsign directory

## Ownership and privacy

The existing `rolling-thunder-forge-callsign-info` process owns this directory.
There is no new daemon or port and no QRZ/Wavelog lookup is needed for directory
routes. SQLite records contain normalized unique callsign, display name, private
multiline comment, active flag, and UTC creation/update timestamps. Station-call
validation uses the shared callsign type, including supported portable suffixes.
Matches are exact normalized station callsigns; `W1ABC/P` is a separate entry
from `W1ABC`. All active entries currently mean `friend`; inactive entries are
unknown to clients. Classification transport can carry additional relationships
by extending the typed relationship values later.

Admin records and comments never enter the normal directory API or Pi cache.
Existing Wavelog last-QSO comments in contact intelligence are a separate existing
contract; this feature does not add directory comments to that response.

Schema 1 is initialized transactionally and reopening preserves records. Future
unknown schema versions are rejected rather than silently rewritten. Each worker
uses a short SQLite connection/transaction; normalized collisions are errors,
not silent overwrites. The directory is limited to 4,096 records (including
inactive entries), so active snapshots are complete and bounded.

## Configuration and state

Forge configuration `/etc/rolling-thunder/forge-callsign-info.yaml`:

```yaml
known_callsigns:
  enabled: true
  database_path: /var/lib/rolling-thunder-forge-callsign-info/known-callsigns.sqlite3
```

The default is disabled so upgrading an existing service does not create new
state or expose new administration. The configured path must be absolute;
production state must remain outside every Git checkout. The systemd unit adds
`StateDirectory=rolling-thunder-forge-callsign-info` with mode 0750. The database
inherits service identity `rollingthunder` and UMask 0027. Custom paths require
appropriate service-account permissions and sandbox write access.

Pi configuration under the existing `forge` mapping:

```yaml
forge:
  enabled: true
  # Keep existing spot service api_url and other settings.
  known_callsigns:
    enabled: true
    api_url: http://192.168.9.170:8788
    request_timeout_s: 5
    refresh_interval_s: 30
    stale_after_s: 90
```

Pi friend classification is independently configurable from the optional contact
intelligence overlay. Its default is disabled. No new Pi persistence schema,
radio configuration, transmit authority, or Forge secret is introduced.

## Admin frontend and security decision

Open `http://192.168.9.170:8788/admin/known-callsigns` from the trusted network.
Use Add friend to enter a callsign, optional name, and comment. Edit allows
renaming and changing the comment/name. Clear Active to deactivate, check it to
reactivate, and save. Search filters callsigns. Delete opens a separate
confirmation page; only its Confirm deletion POST removes a record. GET never
mutates directory state. Comments are visible only on these private admin pages.

The existing RadioLAN/CarLAN-over-WireGuard network authorization boundary
remains the access control, as documented in `FORGE_DEPLOYMENT.md`. No additional
operator credential is added: any host permitted to reach this private listener
is trusted to administer the directory. This is an explicit deployment decision,
not a public unauthenticated administration service. Restrict routed access to
trusted owner/vehicle devices; do not forward TCP 8788 publicly or through UPnP.
Untrusted/shared-network or Internet exposure requires authentication and TLS
before exposure. The service does not modify firewall or routing policy.

Forms use a process-signed CSRF token matched to an HttpOnly SameSite=Strict
cookie and reject cross-origin POSTs when Origin is supplied. HTML escapes all
record fields, disallows scripts/framing, and bounds request bodies to 32 KiB.
Forms opened before a service restart must be reloaded. The CSRF token is not an
operator credential; QRZ/Wavelog secrets never appear in HTML or JavaScript.

## Reusable directory API

`GET /api/v1/known-callsigns` returns the complete bounded active snapshot:

```json
{"api_schema_version":"1","entries":[{"callsign":"W1ABC","known":true,"relationship":"friend"}]}
```

`POST /api/v1/known-callsigns` accepts a JSON batch of 1–128 station callsigns:

```json
{"callsigns":["w1abc","W2ABC","W1ABC"]}
```

The response normalizes uppercase, deduplicates in first-input order, and
explicitly returns unknown/inactive classification:

```json
{"api_schema_version":"1","results":[{"callsign":"W1ABC","known":true,"relationship":"friend"},{"callsign":"W2ABC","known":false,"relationship":null}]}
```

Neither response contains comments, labels, internal IDs, or timestamps. Malformed
batches return 400, oversized bodies 413, unsupported methods 405, and disabled
or unavailable directory routes 503. Existing `/health` and contact-intelligence
routes remain available independently of directory request failure.

## Pi cache and presentation

`KnownCallsignPollingService` schedules one worker, with at most one refresh
pending. It uses the existing injected HTTP transport/scheduler patterns. The Pi
fetches one complete active snapshot every 30 seconds by default, independently
of screen refreshes and QRZ/Wavelog lookup timing. A batch client is also available
for future callers. Typed validation rejects oversized/duplicate/inactive
snapshot entries, inconsistent classifications, and unexpected fields.

The cache publishes an immutable set of at most 4,096 friend callsigns. Rendering
reads that set only; no card performs HTTP. Refresh success replaces the complete
set, so deactivate/delete disappears after the next refresh. Failed or malformed
responses immediately clear decoration; stale data expires after 90 seconds by
default. Stop cancels polling, waits for bounded in-flight HTTP, and clears it.
No persisted Pi friend cache is used, so restart/offline starts without stars.

Separate gold `★` labels decorate POTA/DX cards, FT8 CQ rows, the shared pending
remote callsign (including Browse), contact intelligence, DMR audio/history, and
LOG remote callsigns. Local configuration/operator identity and unrelated IDs
are not decorated. Repeater/channel names and placeholder screens are not remote
callsign lists. Canonical callsigns, selected/worked backgrounds, FT8 outcome
colors/markers, filtering, eligibility, retry, capture, tuning, logging and sync
remain unchanged. A star is informational only, not worked state or permission.

## Owner deployment and live acceptance

No deployment or live hardware validation is performed in Codex Cloud. Use the
exact PR commit, initially in isolated Pi/Forge validation worktrees with isolated
configuration/state and a different loopback validation port. Never run two
instances against the same production directory database. Record the current
service unit, configuration, package/wheel, source SHA and rollback point first.

Production Forge install/source location is
`/opt/rolling-thunder-forge-callsign-info`; its private venv is `.venv` there.
Only `rolling-thunder-forge-callsign-info.service` changes. The spot, weather,
contact-sync, map, and other service units do not need replacement or restart.

Before production adoption, back up the existing directory database if present
using SQLite's backup API (or `.backup` in sqlite3), not an inconsistent live file
copy. Store the backup outside the checkout with restricted permissions. Back up
the service YAML, environment file, and unit without displaying secret contents.
For a first install, record that no previous directory database existed.

In a validation worktree, install this exact source into the validation service's
private venv. For production adoption after owner acceptance, install the exact
validated source into `/opt/rolling-thunder-forge-callsign-info/.venv`:

```bash
/opt/rolling-thunder-forge-callsign-info/.venv/bin/python -m pip install --force-reinstall --no-deps /path/to/exact-commit-worktree
/opt/rolling-thunder-forge-callsign-info/.venv/bin/python -m pip show rolling-thunder
/opt/rolling-thunder-forge-callsign-info/.venv/bin/python -c 'import rolling_thunder.forge_callsign_info_api as api; import rolling_thunder.forge_known_callsigns as directory; print(api.__file__); print(directory.__file__)'
```

Version alone is insufficient (this feature does not bump the release version).
Compare the installed module contents/hashes to the exact validation worktree;
confirm `ExecStart` and the running service use that venv, not an older copied
package. Existing package dependencies suffice; no framework or new dependency
is needed. Preserve the environment file and all unrelated YAML settings.

Enable `known_callsigns` in the service YAML, install the updated callsign-info
unit, then `systemctl daemon-reload` and restart only the callsign-info service.
Verify service identity, StateDirectory access, the resolved production database
path, listener bind address, health, and journal. Check both new routes:

```bash
curl -fsS http://192.168.9.170:8788/health
curl -fsS http://192.168.9.170:8788/api/v1/known-callsigns
curl -fsS -H 'Content-Type: application/json' --data '{"callsigns":["W1ABC"]}' http://192.168.9.170:8788/api/v1/known-callsigns
```

On the Pi, use an isolated worktree of the same commit and validation data.
Refresh its actual runtime venv/package and enable the Pi settings above with the
validation service URL. Restart only the validation dashboard. Confirm its
import path points to the exact tested package before checking the screens.

Acceptance checklist:

1. Confirm exact commit/package paths, database backup, and private listener.
2. Load admin, add a test friend, and verify a multiline comment is visible there.
3. Verify snapshot/batch responses contain classification only, with no comment.
4. Verify gold stars on POTA/DX, FT8 CQ, Browse pending/overlay, DMR and LOG where
   that remote callsign is actually displayed; unknown calls remain unchanged.
5. Edit name/comment and verify persistence; deactivate and wait one poll for
   stars to disappear, reactivate for their return, and confirm/delete for removal.
6. Stop or isolate the validation Forge service; verify Pi usability and absent
   stars after failure/staleness without blocking radio, selection, capture,
   FT8 eligibility/authorization, logging or contact sync.
7. Restart Forge and confirm stored records/comments survive. Recheck ordinary
   contact intelligence and health alongside the new routes.
8. Perform owner-approved normal POTA/DX/FT8 regression operation; no additional
   RF work is authorized by the directory itself. Record results/readability.

Rollback: disable Pi friend polling, restore the recorded service package/unit
and configuration, reload systemd if the unit changed, and restart only the
callsign-info service. Preserve the new database for forward recovery. Restore
a database backup only with the service stopped and explicit intent to discard
later directory edits; schema 1 is independent of every other Forge/Pi database.
