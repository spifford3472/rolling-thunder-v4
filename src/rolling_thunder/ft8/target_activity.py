"""Read-only FT8 activity for a selected target; never affects transmit eligibility."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import TypeAdapter

from rolling_thunder.ft8.domain import FT8Decode, FT8MessageKind, FT8Period
from rolling_thunder.value_types import Callsign

_CALLSIGN = TypeAdapter(Callsign)


class TargetActivityKind(StrEnum):
    UNKNOWN = "unknown"
    CQ = "cq"
    OTHER_QSO = "other_qso"
    SIGNOFF = "signoff"


@dataclass(frozen=True, slots=True)
class TargetActivity:
    callsign: str
    kind: TargetActivityKind = TargetActivityKind.UNKNOWN
    other_callsign: str | None = None
    message_kind: FT8MessageKind | None = None
    last_period: FT8Period | None = None
    observed_source: bool = False


class FT8TargetActivityTracker:
    """Bounded per-target observation of decoded FT8 traffic.

    A message addressed TO the target by someone else is not evidence that the
    target transmitted it. Only source-attributed messages qualify as activity.
    """

    def __init__(self, *, freshness_periods: int = 4, local_callsign: str | None = None) -> None:
        if freshness_periods < 1:
            raise ValueError("freshness_periods must be positive")
        self._freshness = freshness_periods
        self._local_callsign = (
            None if local_callsign is None else _CALLSIGN.validate_python(local_callsign)
        )
        self._target: str | None = None
        self._latest: TargetActivity | None = None
        self._high_water: FT8Period | None = None

    def select(self, callsign: str | None) -> None:
        target = None if callsign is None else _CALLSIGN.validate_python(callsign)
        if target != self._target:
            self._target = target
            self._latest = None
            self._high_water = None

    def observe(self, decodes: tuple[FT8Decode, ...], current_period: FT8Period) -> None:
        if self._high_water is not None and current_period < self._high_water:
            return
        self._high_water = current_period
        if self._target is None:
            return
        for decode in decodes:
            if decode.period > current_period or current_period.index - decode.period.index >= self._freshness:
                continue
            if decode.source_callsign != self._target:
                continue
            if self._latest is not None and self._latest.last_period is not None and decode.period < self._latest.last_period:
                continue
            if decode.kind is FT8MessageKind.CQ:
                activity = TargetActivity(self._target, TargetActivityKind.CQ, last_period=decode.period, message_kind=decode.kind, observed_source=True)
            elif (
                decode.destination_callsign is not None
                and decode.destination_callsign not in {self._target, self._local_callsign}
                and decode.kind in {
                FT8MessageKind.ADDRESSED_GRID, FT8MessageKind.REPORT, FT8MessageKind.R_REPORT, FT8MessageKind.ACK_73,
                }
            ):
                stage = TargetActivityKind.SIGNOFF if decode.kind is FT8MessageKind.ACK_73 else TargetActivityKind.OTHER_QSO
                activity = TargetActivity(self._target, stage, decode.destination_callsign, decode.kind, decode.period, True)
            else:
                continue
            self._latest = activity

    def snapshot(self, current_period: FT8Period | None = None) -> TargetActivity | None:
        if self._target is None:
            return None
        previous = self._latest
        if previous is None or previous.last_period is None:
            return TargetActivity(self._target)
        now = current_period or self._high_water
        if now is not None and now.index - previous.last_period.index >= self._freshness:
            return TargetActivity(self._target)
        return previous
