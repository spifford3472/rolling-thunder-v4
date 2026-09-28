"""UI-independent stable selection and exact receive-action primitives."""

from dataclasses import dataclass

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.spot_domain import SpotIdentity, SpotRecord, SpotSnapshot
from rolling_thunder.value_types import Callsign


@dataclass(frozen=True, slots=True)
class StagedSpotAction:
    """Immutable action-critical values captured from the current selection."""

    identity: SpotIdentity
    callsign: Callsign
    frequency: Frequency
    mode: RadioMode

    @classmethod
    def from_spot(cls, spot: SpotRecord) -> "StagedSpotAction":
        """Capture the exact receive target represented by one selected spot."""
        return cls(
            identity=spot.identity,
            callsign=spot.callsign,
            frequency=spot.frequency,
            mode=spot.mode,
        )

    def matches(self, spot: SpotRecord) -> bool:
        """Return whether a record still represents this exact receive action."""
        return (
            self.identity == spot.identity
            and self.callsign == spot.callsign
            and self.frequency == spot.frequency
            and self.mode is spot.mode
        )


@dataclass(frozen=True, slots=True)
class SpotSelectionState:
    """Immutable shared stable-selection state."""

    snapshot: SpotSnapshot
    selected_identity: SpotIdentity | None = None

    @property
    def selected_index(self) -> int | None:
        """Return the selected identity's current snapshot index."""
        if self.selected_identity is None:
            return None
        return self.snapshot.index_of(self.selected_identity)

    @property
    def selected_spot(self) -> SpotRecord | None:
        """Return the selected record from the current snapshot."""
        if self.selected_identity is None:
            return None
        return self.snapshot.get(self.selected_identity)


class SpotSelectionController:
    """Preserve selection by stable identity without performing external work."""

    def __init__(self, snapshot: SpotSnapshot) -> None:
        self._snapshot = snapshot
        self._selected_identity: SpotIdentity | None = None

    @property
    def state(self) -> SpotSelectionState:
        """Return an immutable snapshot of current selection state."""
        return SpotSelectionState(
            snapshot=self._snapshot,
            selected_identity=self._selected_identity,
        )

    def replace_snapshot(self, snapshot: SpotSnapshot) -> SpotSelectionState:
        """Atomically replace spots while preserving a still-present identity."""
        self._snapshot = snapshot
        selected = self._selected_identity
        if selected is not None and snapshot.index_of(selected) is None:
            self._selected_identity = None
        return self.state

    def select_identity(self, identity: SpotIdentity) -> SpotSelectionState:
        """Select one present stable identity or clear stale selection."""
        if self._snapshot.index_of(identity) is None:
            self._selected_identity = None
            return self.state
        self._selected_identity = identity
        return self.state

    def select_next(self) -> SpotSelectionState:
        """Move toward the end without wrapping or neighboring fallback."""
        if not self._snapshot.spots:
            self._selected_identity = None
            return self.state

        current_index = self.state.selected_index
        target_index = (
            0
            if current_index is None
            else min(current_index + 1, len(self._snapshot.spots) - 1)
        )
        return self.select_identity(self._snapshot.spots[target_index].identity)

    def select_previous(self) -> SpotSelectionState:
        """Move toward the start without wrapping or neighboring fallback."""
        if not self._snapshot.spots:
            self._selected_identity = None
            return self.state

        current_index = self.state.selected_index
        target_index = (
            len(self._snapshot.spots) - 1 if current_index is None else max(0, current_index - 1)
        )
        return self.select_identity(self._snapshot.spots[target_index].identity)

    def clear_selection(self) -> SpotSelectionState:
        """Clear the current stable selection."""
        self._selected_identity = None
        return self.state
