# Raspberry Pi Dashboard Autostart

Rolling Thunder uses a systemd-managed dashboard startup path on the installed
Raspberry Pi.

## Design

The service starts after `graphical.target`, then the launcher waits 180 seconds
before starting the dashboard. The delay is intentional: it gives Raspberry Pi OS
and the desktop session time to settle before the Python/Tk dashboard begins its
normal hardware, map, and service initialization.

The launcher validates the production checkout, virtual-environment UI entry
point, and active YAML configuration before launch. Missing prerequisites fail
visibly in the journal instead of creating a silent boot loop.

The dashboard remains the existing `rolling-thunder-ui` application. The
launcher does not create a second application entry point or move application
logic into systemd.

The unit uses `Restart=on-failure` with a ten-second restart delay. A normal
operator/systemd stop is not treated as a failure.

## Production paths

The supported production checkout is:

```text
/home/geoff/projects/rolling-thunder-v4
```

The production virtual environment and configuration are:

```text
/home/geoff/projects/rolling-thunder-v4/.venv/bin/rolling-thunder-ui
/home/geoff/projects/rolling-thunder-v4/config/rolling-thunder.yaml
```

The service runs as `geoff` with the production checkout as its working
directory. LightDM/Xorg provides display `:0`,
`/home/geoff/.Xauthority`, and `/run/user/1000`. The launcher also refuses
to start when an existing Rolling Thunder dashboard process is already running.

The launcher defaults `ROLLING_THUNDER_APP_DIR` to the same production
checkout. The systemd unit sets that value explicitly so the runtime location
is unambiguous.

## Installation

From the production checkout:

```bash
cd /home/geoff/projects/rolling-thunder-v4

chmod 0755 deploy/rolling-thunder-autostart

sudo install -m 0644 \
  deploy/systemd/rolling-thunder.service \
  /etc/systemd/system/rolling-thunder.service

sudo systemctl daemon-reload
sudo systemctl enable rolling-thunder.service
```

The launcher remains in the production checkout; it is not copied to a separate
runtime directory.

## Legacy v4.2 path override

During the v4.2.0 release transition, `anvilmobile` used the local drop-in:

```text
/etc/systemd/system/rolling-thunder.service.d/v4.2-main.conf
```

to override an older checked-in base unit that still referenced
`/home/geoff/projects/rolling-thunder-v4-regional`.

The corrected base unit now contains the same production path directly. Keep the
legacy drop-in installed until the corrected base unit has been physically tested
on `anvilmobile`. Remove it only after verifying that the effective unit is
unchanged apart from the redundant override.

## Verification without the three-minute delay

For a supervised test, use a temporary drop-in rather than editing the checked-in
unit:

```bash
sudo systemctl edit rolling-thunder.service
```

Use:

```ini
[Service]
Environment=ROLLING_THUNDER_STARTUP_DELAY_SECONDS=0
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl start rolling-thunder.service
systemctl status rolling-thunder.service --no-pager -l
journalctl -u rolling-thunder.service -n 100 --no-pager
```

Remove only the temporary zero-delay override after the supervised test. Do not
remove `v4.2-main.conf` until the corrected base service has passed the
Checkpoint 0 acceptance test.

## Checkpoint 0 acceptance

Checkpoint 0 is accepted on `anvilmobile` when all of the following are
observed:

1. the checked-in unit points only to `/home/geoff/projects/rolling-thunder-v4`;
2. the launcher defaults to that same production checkout;
3. the installed effective unit starts the dashboard from that checkout;
4. radio, GPS, controls, map, logging, and other existing behavior remains unchanged;
5. stopping the service terminates the dashboard cleanly;
6. the service restarts correctly after a supervised failure/start test; and
7. after the base-unit test succeeds, removing the legacy `v4.2-main.conf`
   drop-in does not change the effective production paths.

A reboot/180-second startup test should be performed before final merge approval
when practical.

## v4.2.0 recovery

The immutable v4.2.0 recovery point is tag `v4.2.0`, commit
`3f5a9c22bc600883b1eb8d868d92e2f58658cc24`.

Checkpoint 0 does not change application code, configuration data, databases,
audio rules, udev rules, or radio behavior. If rollback is required, restore the
v4.2.0 checkout and the known-good `v4.2-main.conf` drop-in before restarting
`rolling-thunder.service`.
