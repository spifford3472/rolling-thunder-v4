# Forge Spot Service Production Deployment

## Purpose

This document defines the supported production deployment for the Rolling Thunder Forge spot aggregation service established by checkpoint 8 of GitHub issue #148.

The Forge service remains an independent, read-only spot aggregation process. It has no radio, CAT, receive-tuning, PTT, MOX, keying, tuner, power, contact logging, or Tkinter authority.

## Production host and listener

The supported host is `forge` on the RadioLAN address `192.168.9.170`.

The production REST listener is:

```text
192.168.9.170:8766
```

Port `8765` is not used by the production Forge spot service. The service must not bind to `0.0.0.0`.

## Production layout

| Purpose | Path |
| --- | --- |
| Application checkout | `/opt/rolling-thunder-forge` |
| Python virtual environment | `/opt/rolling-thunder-forge/.venv` |
| Production YAML | `/etc/rolling-thunder/forge-spots.yaml` |
| Optional environment secrets | `/etc/rolling-thunder/forge-spots.env` |
| Persistent SQLite database | `/var/lib/rolling-thunder/forge-spots.db` |
| systemd unit | `/etc/systemd/system/rolling-thunder-forge-spots.service` |
| journal | `journalctl -u rolling-thunder-forge-spots.service` |

The application checkout must be installed from a known Git commit. Production deployment must never be performed from an uncommitted working tree.

## Service account

The service runs as the dedicated system account `rollingthunder` with home `/nonexistent` and shell `/usr/sbin/nologin`.

The systemd unit uses:

```text
User=rollingthunder
Group=rollingthunder
```

The service must not run as `root` or the interactive `geoff` account.

The application tree is owned by `root:rollingthunder`; the service account has read/execute access but does not own the source tree. Persistent state is owned by `rollingthunder:rollingthunder` so the service can update its SQLite database without write access to application source or configuration.

## Configuration

The tracked production template is:

```text
config/forge-spots.production.example.yaml
```

The deployed configuration is:

```text
/etc/rolling-thunder/forge-spots.yaml
```

The production database path is:

```text
/var/lib/rolling-thunder/forge-spots.db
```

The accepted checkpoint-8 deployment enables POTA and DXSpider, uses a 60-second aggregation refresh interval with refresh-on-start enabled, and leaves QRZ enrichment disabled until credentials are intentionally provisioned.

DXSpider login uses the licensed operator callsign configured in production YAML.

## QRZ credentials

QRZ credentials must never be committed to Git or stored in Forge YAML.

If QRZ enrichment is enabled, credentials are provided only through `/etc/rolling-thunder/forge-spots.env` using:

```text
ROLLING_THUNDER_QRZ_USERNAME
ROLLING_THUNDER_QRZ_PASSWORD
```

Recommended ownership and mode for the environment file are `root:rollingthunder` and `0640`. When QRZ is disabled the file may remain empty.

## systemd service

The tracked unit source is:

```text
deploy/systemd/rolling-thunder-forge-spots.service
```

The installed unit is:

```text
/etc/systemd/system/rolling-thunder-forge-spots.service
```

The unit uses `Restart=on-failure`, a five-second restart delay, `NoNewPrivileges=true`, an empty capability bounding set, private temporary storage, read-only system protection, restricted kernel/control-group access, and `StateDirectory=rolling-thunder`.

### Lifecycle commands

```bash
systemctl status rolling-thunder-forge-spots.service
sudo systemctl start rolling-thunder-forge-spots.service
sudo systemctl stop rolling-thunder-forge-spots.service
sudo systemctl restart rolling-thunder-forge-spots.service
sudo systemctl enable rolling-thunder-forge-spots.service
sudo systemctl disable rolling-thunder-forge-spots.service
```

The supported production state is both `active` and `enabled`.

## Logs and diagnostics

Recent journal:

```bash
sudo journalctl -u rolling-thunder-forge-spots.service -n 50 --no-pager
```

Follow logs:

```bash
sudo journalctl -u rolling-thunder-forge-spots.service -f
```

Listener check:

```bash
ss -lntp | grep '192.168.9.170:8766'
```

Health check:

```bash
curl -fsS http://192.168.9.170:8766/api/v1/health
```

Spot snapshot:

```bash
curl -fsS http://192.168.9.170:8766/api/v1/spots
```

A normal live deployment reports the service, DX, and POTA as healthy. Provider failures may intentionally leave retained data available with degraded health.

## Persistence and restart behavior

Forge SQLite state is independent of the Pi contact database.

The service loads the last durable Forge snapshot during startup, so the HTTP API can serve retained state before the first live provider refresh has completed.

A restored or migrated database must pass:

```sql
PRAGMA integrity_check;
```

A live SQLite database must be copied with SQLite backup semantics rather than with an uncoordinated file copy.

## Network trust boundary

The Forge REST API currently provides neither TLS nor application-layer authentication. This is an explicit checkpoint-8 trust-boundary decision and is acceptable only inside the trusted private Rolling Thunder routed network.

The production listener is restricted to `192.168.9.170:8766` rather than every Forge interface.

The expected mobile path is:

```text
anvilmobile / CarLAN
    -> WireGuard
    -> RadioLAN
    -> forge:8766
```

The Pi may use hostname `forge` when approved local name resolution or its host mapping resolves that name to `192.168.9.170`.

The deployment assumes:

- no public Internet port forwarding to TCP 8766
- no UPnP exposure
- private WireGuard access for the mobile client
- OPNsense remains the routed network security boundary
- only intended private networks are allowed to reach the Forge RadioLAN API

The Forge host does not rely on UFW for this service boundary. Security therefore depends on the specific bind address plus the routed OPNsense/WireGuard policy.

Anyone who can reach TCP 8766 can read the health and spot endpoints. No credentials or radio-control operations are exposed by this service, but the lack of API authentication remains an explicit residual risk.

If the API is ever exposed outside the trusted private network, TLS and authentication must be added before that exposure is considered supported.

## Pi failure behavior

Forge availability is not required for local Rolling Thunder operation.

If Forge, WireGuard, cellular service, DXSpider, POTA, or the public Internet is unavailable:

- the Pi retains its most recent valid shared-spot snapshot
- stale/error age remains visible through the Pi Forge client state
- malformed or incomplete Forge responses do not replace the durable Pi cache
- local SQLite contact logging remains authoritative and available
- no alternate public POTA polling authority is activated when Forge mode is enabled

## Deployment update procedure

A production update must use a known Git commit and preserve the currently working service until the new build is validated.

Recommended sequence:

1. complete and push the feature commit
2. stage the exact commit under `/opt/rolling-thunder-forge`
3. create the production virtual environment
4. install the package into that virtual environment
5. validate configuration as the `rollingthunder` service account
6. validate a copy of the current SQLite database
7. run the new executable side-by-side on a temporary private port
8. require successful live POTA and DX provider refreshes
9. stop the old production process
10. take a final SQLite backup
11. start the new systemd service on 8766
12. require live healthy POTA and DX refreshes
13. verify process identity, command, working directory, listener, and commit
14. enable the service at boot only after all checks pass

A side-by-side smoke test must use a separate SQLite copy and a separate port. Two Forge processes must never write the same SQLite database concurrently.

## Rollback

If a newly deployed systemd service fails before acceptance:

1. stop the new service
2. disable it if it was enabled
3. confirm TCP 8766 is no longer listening
4. restore the last known-good application/config/database combination
5. start the last known-good service
6. require a successful health response before declaring rollback complete

Never launch a rollback process while another process still owns TCP 8766.

The retained SQLite snapshot may be used during provider outages, but a database with failed integrity validation must never be placed into service.

## Checkpoint-8 deployment acceptance

The first checkpoint-8 production deployment was accepted on Forge using application commit:

```text
9300cbc3cd8aa4335ca6071d6d8cfa80d267b8c0
```

Acceptance demonstrated:

- exact deployed commit verification
- dedicated `rollingthunder` UID
- working directory `/opt/rolling-thunder-forge`
- production config `/etc/rolling-thunder/forge-spots.yaml`
- persistent SQLite integrity validation
- live POTA refresh
- live DXSpider refresh
- healthy REST response on `192.168.9.170:8766`
- systemd `Restart=on-failure`
- five-second restart delay
- service active under systemd
- service enabled at boot
- old interactive `geoff` Forge process retired
- real Pi requests reaching `/api/v1/spots` through the private routed path

At final infrastructure acceptance the API reported both POTA and DX providers healthy with no persistence or startup-storage error.

## Radio safety boundary

Deployment does not change radio authority. The Forge service has no code path for CAT, frequency or mode changes, PTT/MOX, keying, tuner control, power control, or transmit control.

All operator-confirmed receive tuning remains on the Pi and must route through `ReceiveTuningService`.
