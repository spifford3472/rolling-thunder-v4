# FT8-P1 anvilmobile: guarded Pi cutover

Status: **PREPARED ONLY**. This runbook and its script are **not** production deployment approval. They do not authorize RF transmission.

Merged base: `c16e015051e29b92a5f773d594ad1cafd5c70c02` (PR #255). Existing Pi at preflight was `28f798ada0f81e2638797f3a56ebc7c172bb4ea4`, with schema 20 and service `rolling-thunder.service` running as `geoff`.

The production database is `/home/geoff/projects/rolling-thunder-v4/config/data/rolling-thunder.db`, resolved relative to `config/rolling-thunder.yaml`. Existing private backups of three databases were checked for integrity. A throwaway copy was migrated with the merged release; three FT8 evidence tables initialized; integrity and FK checks passed.

## Deployment constraints

- **Do not use** `/usr/local/sbin/rolling-thunder-deploy` for this cutover; its automatic rollback restores an older SQLite backup and deletes live WAL/SHM files.
- Use `deploy/rolling-thunder-ft8-p1-pi-cutover --preflight` after fetching the target in the production repository, and only use `--deploy-approved` after a separate operator go decision.
- The script makes fresh backups of all three SQLite databases and the production configuration, verifies the target is reachable on `origin/main`, and requires clean production Git state. It leaves all databases untouched during rollback; code/config can be reverted but database schema must be manually reviewed before attempting to operate against a newer incompatible release.
- Prior to service restart the script forces `ft8.transmit.enabled: false` and validates the configuration. **No-RF test does not key the FT-891.** Do not run hardware transmit/decoder tests or any other command that keys the radio before a separate supervised stationary test approval.
- The Forge FT8 period API token is present on Forge only. Pi upload requires secure, separately gated provisioning of the same token as `ROLLING_THUNDER_FT8_PERIOD_TOKEN` in the Pi process environment. Missing token fails closed; neither retrieve nor print the secret as part of this script. Other ordinary contact-sync credentials are independent.
- Deployed mobile UI remains operational with FT8 **receive-only** initially; later RF approval requires a stationary dummy load, PTT release/watchdog review, and decision regarding the legacy 100 W voice restore on FT8 exit.

The script is an operator cutover aid, not a replacement for the existing production deploy helper; do not install it over that helper. Logs must exclude bearer credentials and any secret environment content.
