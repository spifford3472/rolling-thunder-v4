"""Command-line entry point for the isolated FT-891 ATAS CAT bench probe."""

import argparse
import os
from pathlib import Path

from rolling_thunder.config import HardwareAdapterMode, load_config
from rolling_thunder.ft891_atas_probe import (
    AtasProbeDirection,
    AtasProbeOrder,
    AtasProbeRequest,
    AtasProbeSafetyError,
    run_atas_probe,
)
from rolling_thunder.pyserial_cat_transport import PySerialCatTransport
from rolling_thunder.radio import RadioConnectionError

_DEFAULT_CONFIG = Path("config/rolling-thunder.yaml")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one guarded FT-891 PTT + microphone UP/DOWN CAT experiment. "
            "This keys the transmitter briefly and is not part of normal Rolling Thunder."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG,
        help="Rolling Thunder YAML configuration path.",
    )
    parser.add_argument(
        "--direction",
        required=True,
        choices=[item.value for item in AtasProbeDirection],
    )
    parser.add_argument(
        "--order",
        required=True,
        choices=[item.value for item in AtasProbeOrder],
    )
    parser.add_argument(
        "--inter-command-delay-ms",
        type=int,
        default=50,
    )
    parser.add_argument(
        "--countdown-seconds",
        type=int,
        default=30,
        help="Seconds to wait before the CAT port is opened and RF is keyed (0-60).",
    )
    parser.add_argument(
        "--keyed-duration-seconds",
        type=float,
        default=3.0,
        help="How long CAT PTT remains active before meter readback; maximum 3.0 s.",
    )
    parser.add_argument(
        "--confirmed-power-watts",
        type=int,
        required=True,
        help="Operator-confirmed radio RF power setting; probe refuses values above 10 W.",
    )
    parser.add_argument(
        "--confirm-rf-path",
        required=True,
        choices=["atas"],
        help="Explicitly confirm the FT-891 RF path is connected to the ATAS test antenna.",
    )
    parser.add_argument(
        "--i-understand-radio-will-transmit",
        action="store_true",
        help="Required acknowledgement that this diagnostic briefly keys RF.",
    )
    return parser


def _other_process_holders(device: Path) -> tuple[int, ...]:
    """Return Linux PIDs, other than this process, currently holding the resolved tty."""
    try:
        target = device.resolve(strict=True)
    except OSError:
        return ()

    holders: set[int] = set()
    own_pid = os.getpid()
    proc = Path("/proc")
    if not proc.exists():
        return ()

    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == own_pid:
            continue
        fd_dir = entry / "fd"
        try:
            fds = tuple(fd_dir.iterdir())
        except (FileNotFoundError, PermissionError, OSError):
            continue
        for fd in fds:
            try:
                if fd.resolve(strict=True) == target:
                    holders.add(pid)
                    break
            except (FileNotFoundError, PermissionError, OSError):
                continue
    return tuple(sorted(holders))


def main() -> int:
    args = _parser().parse_args()

    if not args.i_understand_radio_will_transmit:
        raise SystemExit(
            "REFUSED: add --i-understand-radio-will-transmit only after preparing "
            "the stationary ATAS bench test."
        )
    if not 1 <= args.confirmed_power_watts <= 10:
        raise SystemExit(
            "REFUSED: --confirmed-power-watts must be between 1 and 10 W for this probe."
        )

    config = load_config(args.config)
    hardware = config.hardware

    if hardware.effective_radio_mode is not HardwareAdapterMode.REAL:
        raise SystemExit("REFUSED: hardware.radio_mode must be real.")
    device = hardware.radio_device
    if device is None:
        raise SystemExit("REFUSED: hardware.radio_device is not configured.")
    if not str(device).endswith("-if00-port0"):
        raise SystemExit(
            "REFUSED: probe requires the FT-891 Enhanced CAT interface ending in "
            "-if00-port0; the Standard interface must remain unopened."
        )

    holders = _other_process_holders(device)
    if holders:
        joined = ", ".join(str(pid) for pid in holders)
        raise SystemExit(
            "REFUSED: FT-891 CAT device is already open by PID(s) "
            f"{joined}. Stop the Rolling Thunder dashboard and any other CAT client first."
        )

    if not 0 <= args.countdown_seconds <= 60:
        raise SystemExit("REFUSED: --countdown-seconds must be between 0 and 60.")

    request = AtasProbeRequest(
        direction=AtasProbeDirection(args.direction),
        order=AtasProbeOrder(args.order),
        inter_command_delay_ms=args.inter_command_delay_ms,
        keyed_duration_s=args.keyed_duration_seconds,
    )
    transport = PySerialCatTransport(
        device,
        baud_rate=hardware.radio_baud_rate,
        timeout_s=min(hardware.radio_timeout_s, 0.5),
    )

    print("===== FT-891 ATAS CAT PROBE =====")
    print(f"Device: {device}")
    print(f"Direction: {request.direction.value}")
    print(f"Order: {request.order.value}")
    print(f"Confirmed RF power: {args.confirmed_power_watts} W")
    print("RF path: ATAS")
    print(f"Pre-key countdown: {args.countdown_seconds} seconds")
    print(f"Maximum keyed interval: {request.keyed_duration_s:.1f} seconds")
    print("The probe will force RX/TX0 in a finally block.")

    for remaining in range(args.countdown_seconds, 0, -1):
        if remaining <= 5 or remaining % 5 == 0:
            print(f"Keying in {remaining}...")
        import time
        time.sleep(1)

    print("KEYING NOW")

    try:
        result = run_atas_probe(transport, request)
    except (AtasProbeSafetyError, RadioConnectionError, ValueError) as error:
        print(f"ABORTED: {error}")
        return 2

    print("RESULT: probe completed and returned to receive")
    print(f"Frequency: {result.frequency.hz} Hz")
    print(f"Mode: {result.mode.value}")
    print(f"TX readback while keyed: TX{result.tx_state_while_keyed}")
    print(f"SWR meter raw: {result.swr_meter_raw}/255")
    print(f"Power meter raw: {result.power_meter_raw}/255")
    print("Observe and record whether the ATAS physically moved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
