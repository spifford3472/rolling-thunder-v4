# Raspberry Pi Dashboard Autostart

Rolling Thunder v4.2 checkpoint 1 adds a systemd-managed dashboard startup path for
the installed Raspberry Pi.

## Design

The service starts after `graphical.target`, then the launcher waits 180 seconds
before starting the dashboard. The delay is intentional: it gives Raspberry Pi OS
and the desktop session time to settle before the Python/Tk dashboard begins its
normal hardware, map, and service initialization.

The launcher validates the production checkout, virtual-environment UI entry
point, and active YAML configuration before launch. Missing prerequisites fail
visibly in the journal instead of creating a silent boot loop.

The dashboard remains the existing `rolling-thunder-ui` application. This
checkpoint does not create a second application entry point or move application
logic into systemd.

The unit uses `Restart=on-failure` with a ten-second restart delay. A normal
operator/systemd stop is not treated as a failure.

## Production paths

The checked-in unit assumes the established production worktree:

```text
/home/geoff/projects/rolling-thunder-v4-regional
```

and:

```text
/home/geoff/projects/rolling-thunder-v4/.venv/bin/rolling-thunder-ui
/home/geoff/projects/rolling-thunder-v4-regional/config/rolling-thunder.yaml
```

The service runs as `geoff` and uses the production arrangement verified on `anvilmobile`: the regional worktree is the working directory, while the Python environment is `/home/geoff/projects/rolling-thunder-v4/.venv`. LightDM/Xorg provides display `:0`, `/home/geoff/.Xauthority`, and `/run/user/1000`. The launcher also refuses to start when an existing Rolling Thunder dashboard process is already running.

## Installation

After the checkpoint branch is deployed to the production worktree:

```bash
sudo install -m 0755 \
  /home/geoff/projects/rolling-thunder-v4-regional/deploy/rolling-thunder-autostart \
  /home/geoff/projects/rolling-thunder-v4-regional/deploy/rolling-thunder-autostart

sudo install -m 0644 \
  /home/geoff/projects/rolling-thunder-v4-regional/deploy/systemd/rolling-thunder.service \
  /etc/systemd/system/rolling-thunder.service

sudo systemctl daemon-reload
sudo systemctl enable rolling-thunder.service
```

The first `install` command intentionally reapplies executable mode to the
checked-out launcher. It does not copy the launcher outside the production
worktree.

## Verification without the three-minute delay

For an initial supervised test, create a systemd drop-in rather than editing the
checked-in unit:

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

Remove the test override with:

```bash
sudo systemctl revert rolling-thunder.service
sudo systemctl daemon-reload
```

The production service then returns to the checked-in 180-second delay.

## Boot acceptance

Checkpoint 1 is accepted on `anvilmobile` when all of the following are observed:

1. the service is enabled;
2. a reboot reaches the graphical desktop normally;
3. the dashboard does not launch immediately;
4. the journal records the 180-second startup wait;
5. the dashboard appears after the delay without SSH intervention;
6. radio/GPS/controls/map initialization behaves as it did under manual startup;
7. stopping the service terminates the dashboard cleanly; and
8. an unexpected dashboard failure is restarted by systemd.

If the desktop uses a different display or X authority path, record the actual
installed values in the pull-request acceptance notes before merge.
