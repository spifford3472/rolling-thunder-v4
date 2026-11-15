# STAB-07H — Hardware-disabled ARM64 Tk lifecycle and refusal evidence

**November 14, 2026 — OFFLINE REVIEW CANDIDATE. PRODUCTION NO GO.**

This task extends STAB-07G's emulated ARM64 Python environment with a real
Tk event loop backed by a private virtual display, and exercises the **existing
Rolling Thunder heartbeat and shutdown primitives** against inert fake
runtime/peripheral callbacks. It does not invoke `run_dashboard()` or the
installed `rolling-thunder-ui` command, start a real application service, touch
production SQLite, open a CAT/serial/PTT/device path, or transmit RF.

## Provenance, isolation, and nonproduction paths

- Forge remains `x86_64` and the test runs under the already verified,
  unprivileged network-disabled QEMU AArch64 sandbox from STAB-07G. Its Debian
  CPython is 3.13.5 (`deb13u5`), **not a bit-identical copy** of AnvilMobile's
  `deb13u4`. All 26 pinned ARM64 dependencies and the **noneditable** Rolling
  Thunder 4.4.1 app wheel were installed offline in STAB-07G; the UI import and
  18 native/import smoke checks passed there before this lifecycle test.
- A private Ubuntu `xvfb` binary was downloaded without host package install:
  `.deb` SHA256
  `2011271eabcc2eb460e99995c5ef26e46633e87d04f570e305b62f178f7b452c`;
  extracted executable SHA256
  `0081b27338b510ec5e2068a93c6db31480872de9bb082f347f3747ef1648e794`.
- The test X server is run inside a distinct unprivileged bwrap user/PID/
  **network** namespace, with `-nolisten tcp`, GLX disabled, a private MIT
  cookie, a private socket at `display/.X11-unix`, and a dedicated framebuffer.
  Xvfb is not a Forge display manager, public listener or systemd service.
  The guest can see **only** that private X socket, no host/home station data.
- Scratch paths are owned by `rt-remote`, nonproduction only:
  `/home/rt-remote/workspaces/rt-stab07g-sandbox` (existing QEMU sysroot,
  venv and copied, reviewed test script),
  `/home/rt-remote/workspaces/rt-stab07h-sandbox` (first private Xvfb trial)
  and `/home/rt-remote/workspaces/rt-stab07h-repeat` (isolated private
  test display and scratch for the reproducible runner). No host package,
  Docker socket permission, binfmt kernel setting, production port, timer,
  privileged file or service was changed.
- The private guest uses a read-only mounted sysroot and app venv, private
  scratch for the synthetic heartbeat marker, sandbox-local `/dev` and `/proc`,
  and a cleared environment (`-I -B` Python). Actual AnvilMobile audio, USB,
  controllers and GPS are entirely absent.

## What the real Tk test runs

`deploy/rolling-thunder-arm64-tk-lifecycle.py` creates a real `tk.Tk()` root,
withdraws the window, enters its real event loop, and invokes the current code's
`rolling_thunder.ui_readiness.start_ui_heartbeat` with a private runtime
marker. `has_fresh_heartbeat` must confirm a fresh tick from this process.
Then a real SIGTERM is sent to this **test process** and
`ui_main._sigterm_close_handler` records the request without doing Tk work from
the signal handler. Tk dispatches the close request and intentionally calls
`ui_main._request_close_once` twice. Exactly **one** fake cleanup worker must
start. It enters `ui_main._run_orderly_shutdown`, running fake runtime stop
**before** both fake peripheral cleanup steps. The Tk loop remains responsive
until worker completion, then destroys the test root. Late synthetic operator
commands are checked against the already-started close gate and refused.
The previous signal handler is restored and an old heartbeat must fail the
freshness check. The test uses no radio-capable object, transmit command,
application database, service factory, device file or network request.

The following four emulated ARM64/Xvfb scenarios completed successfully on
Forge in initial manual harness trials:

| Scenario | Observed behavior | Outcome |
| --- | --- | --- |
| `normal` | fresh Tk marker, SIGTERM, one worker, fake runtime then both peripherals | PASS |
| `runtime-error` | fake runtime stop raises; both peripheral callbacks still attempted, error recorded | PASS (expected error) |
| `peripheral-error` | first peripheral raises; final peripheral still attempted, error recorded | PASS (expected error) |
| `delayed-cleanup` | first peripheral takes about 150 ms; Tk observes eventual completion | PASS |

`stalled-worker` is an **expected-refusal** negative scenario: an inert worker
blocks beyond the Tk-bound eight-second fail-safe. The test must report
`close_finished=false` and exit with refusal status, not claim a successful
cleanup or physical receive. A timeout cannot de-key a physical radio or
complete a blocked CAT operation. Failure reporting is not an invitation to
kill a production RF process.

**Evidence status:** The initial four scenarios on private display `:94`
passed. The hardened runner uses a second private display `:95` to avoid
sharing sockets or display cookies with any user X session. It additionally
rejects stale heartbeat markers and refuses an incomplete/forged result.
The hardened runner's **repeated `normal` case also passed**, including
`stale_heartbeat_rejected=true` after the real Tk loop ended. The deliberate
`stalled-worker` run returned **exit 75**, as required, and left no approved
shutdown result. Both disposable Xvfb instances were stopped; the repeat
runner left no private X socket, cookie, or lock residue.

## Repeatable runner, files and integrity

- `deploy/rolling-thunder-arm64-tk-runner.py` permits only fixed named
  fake-cleanup scenarios. It validates the STAB-07G QEMU executable/ARM64
  interpreter using the existing read-only sandbox contract; compares the
  copied guest test program against the checked-in source SHA; verifies the
  extracted Xvfb and its archive SHA; refuses outside/private-unsafe paths,
  reused X sockets and existing authorization cookies.
- The runner creates a fresh temporary Xauthority cookie, launches a private
  namespace Xvfb, waits for the expected socket, launches the guest with a
  hard timeout, validates its structured evidence and **always terminates**
  its own Xvfb process group. It removes only private socket/lock residue
  known to belong to the terminated instance. A stale X socket, unauthorized
  command or missing proof produces a refusal, not automatic reuse.
- The guest emits explicit status keys: `readiness_fresh`,
  `stale_heartbeat_rejected`, `sigterm_received`, `close_worker_count`,
  `close_finished`, `ordered_fake_steps`, `cleanup_errors` and
  `post_shutdown_operator_commands`. It always states
  `production_ready=false`, `radio_or_ptt_tested=false`,
  `no_real_dashboard_startup=true` and
  `loaded_python_bytes_independently_proven=false`.
- `tests/test_arm64_tk_lifecycle_runner.py` exercises the strict report
  acceptance matrix, malicious/forged completion or production flags,
  unsafe socket/mount attempts, wrong guest script, unexpected binary and
  action refusal. The regular CI suite remains hardware-free and does not
  start Xvfb; the emulated GUI trials are separate Forge evidence.

For an existing reviewed, uncompromised private sandbox, an explicit user
may rerun one case from Forge:

```bash
cd /home/rt-remote/workspaces/rt-stab07
python deploy/rolling-thunder-arm64-tk-runner.py \
  --sandbox /home/rt-remote/workspaces/rt-stab07g-sandbox \
  --display /home/rt-remote/workspaces/rt-stab07h-repeat/display \
  --mode normal
```

The copy at `.../rt-stab07g-sandbox/runtime/tk-lifecycle.py` must match the
reviewed repository source file byte-for-byte. If scratch no longer exists,
reconstruct in a separately verified private workspace instead of bypassing
checksum or permission tests. Do not put this test script in a production
systemd unit or make the original radio adapters part of its runtime.

## Staging / rollback boundary and remaining acceptance

The earlier STAB-07F candidate remains immutable under a **private Forge**
workspace, and its own independent `--verify-only` recheck returned 30/30
staged files checked, `production_ready=false`, after these lifecycle trials.
The accompanying prior-release no-overwrite and interrupted-stage tests passed
alongside the new runner tests. These establish **offline rollback candidate
preservation**, not a verified install/rollback transaction on the Pi. No
production symlink, application version, QSO row or service process was
changed by this test. Failure-injection cleanup errors never turn into an
implicit approval to restore a DB or clear a deployment transaction journal.

**Unresolved: full Rolling Thunder `run_dashboard` composition and real widget
startup against hardware fakes, full Tk rendering and timing under a production
monitor, exact Pi OS/stdlib/native package bytes, systemd launcher, privileged
root-owned release and receipt signing, imported-code in-memory proof, durable
SQLite/WAL snapshot/rollback, and physical receive/PTT de-key evidence.**
A green Tk fake-worker test cannot prove the real worker calls will meet a
20-second systemd stop deadline or that an FT-891 has returned to receive.
These remain NO GO, with separate owner approval required before any merge,
privileged install, restart, rollback or RF test.

**Rollback and change history:** This is an isolated source-and-scratch trial.
Abandoning the branch and shutting down the private X server returns the host
and active Pi to their unchanged condition; scratch data can be retained for
review or explicitly deleted later. No changes were made to OPNsense or
192.168.9.0/24 or 192.168.10.0/24, so no deployed infrastructure entry is
claimed. Actual future infrastructure changes must be documented and
committed in `spifford3472/ki5vnb-qth-infrastructure`, including configuration
paths, integrations, jobs, validation, rollback and history.

2026-11-14: Added ARM64 real-Tk, signal/shutdown order and failure-injection
mock lifecycle harness; private Xvfb runner; expected-refusal tests; updated
engineering indexes and recorded remaining safety blockers. Local Forge
full pytest **4,273 passed, 7 skipped**, strict MyPy 401 files, targeted Ruff
and git diff --check passed. Whole-repository Ruff retained the four
pre-existing USB-observer diagnostics (untouched). **Production NO GO.**
