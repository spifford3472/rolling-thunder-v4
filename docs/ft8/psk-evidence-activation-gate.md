# CP2.4 private PSK evidence activation gate (NOT authorization to deploy)

Existing PSK-N2 production audit on Forge: 278 outbound KI5VNB FT8 reception rows, 207 distinct receivers, 206 with usable grids over 24 hours; zero rows in the last 30 minutes and two hours at audit time. This establishes normalized history coverage but **not** evidence within the ranking model's 30-minute live window. Reuse existing PSK-N2 collector/normalization acceptance, with no additional provider polling or RF re-test.

## Gated sequence

1. **Already validated in development:** end-to-end read-only HTTP adapter, real ephemeral socket on loopback, disposable normalized SQLite database, matching private token accepted, invalid token and off-path target neutral. The test changes no installed service and never contacts PSK Reporter.
2. **Before production activation:** designate an independently secured runtime and least-privileged read-only access to the *existing* PSK-N2 history database. Do not broaden directory/file ACLs or replace the collector service account. Verify schema v5/`psk_reception` in the service's existing database (already audited). Use a dedicated long random bearer token held in protected service configuration, not git, command line, or shell history.
3. **Listener network:** current executable enforces `127.0.0.1` only. It is **not directly reachable from the Pi**. Review a restricted WireGuard/SSH forward or authenticated private reverse proxy separately; do not expose port 8791 publicly or relax loopback binding casually. Confirm end-to-end token handling and that headers/query strings are absent from logs.
4. **Pi opt-in:** configure `ROLLING_THUNDER_FT8_EVIDENCE_URL` and `ROLLING_THUNDER_FT8_EVIDENCE_TOKEN` only after the private transport is verified. Unset both for immediate local ranking fallback. Outbound reception evidence is advisory only; no PTT/radio power authority.
5. **Acceptance:** read-only one valid authenticated request, one deliberately bad token (must reject), receiver-grid/path filtering, empty recent window, offline fallback, unchanged PSK worker health, existing FT8 UI/encoder behavior. Do not repeat dummy-load/CAT/PSK provider acceptance solely for this consumer.

**No deployment or production config change is included.** Owner approval is required for any live listener enablement, credential installation, reverse proxy/tunnel changes, or Pi rollout.
