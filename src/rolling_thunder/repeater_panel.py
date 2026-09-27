"""UI-independent six-meter repeater panel state and operator actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from rolling_thunder.repeater_configuration import StagedRepeaterRadioAction
from rolling_thunder.repeater_domain import RepeaterRecord
from rolling_thunder.repeater_nearby import (
    NearbyRepeater,
    NearbyRepeaterState,
    NearbyRepeaterStateKind,
)

NearbyStateProvider = Callable[[], NearbyRepeaterState]
OverrideApplier = Callable[[str, bool], None]


class RepeaterDisplayFilter(StrEnum):
    """Operator-visible repeater filtering modes."""

    ACTIVE_ONLY = "active_only"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class StagedRepeaterActiveAction:
    """Exact local Active mutation captured by one Context Button #2 press."""

    repeater: RepeaterRecord
    effective_active: bool
    target_active: bool

    @classmethod
    def from_nearby(cls, item: NearbyRepeater) -> StagedRepeaterActiveAction:
        return cls(
            repeater=item.repeater,
            effective_active=item.effective_active,
            target_active=not item.effective_active,
        )

    @property
    def stable_key(self) -> str:
        return self.repeater.stable_key

    def matches(self, item: NearbyRepeater) -> bool:
        return (
            item.repeater == self.repeater
            and item.effective_active is self.effective_active
            and self.target_active is (not item.effective_active)
        )


@dataclass(frozen=True, slots=True)
class RepeaterPanelRow:
    repeater: RepeaterRecord
    distance_miles: float
    effective_active: bool
    selected: bool = False

    @property
    def stable_key(self) -> str:
        return self.repeater.stable_key


@dataclass(frozen=True, slots=True)
class RepeaterPanelState:
    nearby_kind: NearbyRepeaterStateKind
    nearby_detail: str
    display_filter: RepeaterDisplayFilter
    rows: tuple[RepeaterPanelRow, ...]
    selected_stable_key: str | None = None
    staged_action: StagedRepeaterActiveAction | None = None
    source_error: str | None = None

    @property
    def staged_stable_key(self) -> str | None:
        if self.staged_action is None:
            return None
        return self.staged_action.stable_key


class RepeaterPanelController:
    """Preserve stable selection and transient Active-toggle state."""

    def __init__(
        self,
        nearby_state: NearbyStateProvider,
        *,
        apply_override: OverrideApplier | None = None,
        source_error: str | None = None,
    ) -> None:
        self._nearby_state = nearby_state
        self._apply_override = apply_override
        self._source_error = source_error
        self._display_filter = RepeaterDisplayFilter.ACTIVE_ONLY
        self._selected_stable_key: str | None = None
        self._staged_action: StagedRepeaterActiveAction | None = None

    @property
    def display_filter(self) -> RepeaterDisplayFilter:
        return self._display_filter

    @property
    def selected_stable_key(self) -> str | None:
        self._synchronize()
        return self._selected_stable_key

    @property
    def staged_action(self) -> StagedRepeaterActiveAction | None:
        self._synchronize()
        return self._staged_action

    def selected_radio_action(self) -> StagedRepeaterRadioAction | None:
        """Snapshot the selected repeater's exact typed radio configuration."""
        selected = self._selected_visible_item()
        return (
            StagedRepeaterRadioAction.from_repeater(selected.repeater)
            if selected is not None
            else None
        )

    @property
    def state(self) -> RepeaterPanelState:
        nearby, visible = self._synchronize()
        rows = tuple(
            RepeaterPanelRow(
                repeater=item.repeater,
                distance_miles=item.distance_miles,
                effective_active=item.effective_active,
                selected=item.repeater.stable_key == self._selected_stable_key,
            )
            for item in visible
        )
        return RepeaterPanelState(
            nearby_kind=nearby.kind,
            nearby_detail=nearby.detail,
            display_filter=self._display_filter,
            rows=rows,
            selected_stable_key=self._selected_stable_key,
            staged_action=self._staged_action,
            source_error=self._source_error,
        )

    def activate(self) -> RepeaterPanelState:
        return self.state

    def toggle_filter(self) -> RepeaterPanelState:
        """Switch active-only/all and cancel any transient Active toggle."""
        self._staged_action = None
        self._display_filter = (
            RepeaterDisplayFilter.ALL
            if self._display_filter is RepeaterDisplayFilter.ACTIVE_ONLY
            else RepeaterDisplayFilter.ACTIVE_ONLY
        )
        return self.state

    def select_next(self) -> RepeaterPanelState:
        _nearby, visible = self._synchronize()
        if not visible:
            self._clear_all()
            return self.state
        index = self._visible_selected_index(visible)
        target = 0 if index is None else min(index + 1, len(visible) - 1)
        return self.select_stable_key(visible[target].repeater.stable_key)

    def select_previous(self) -> RepeaterPanelState:
        _nearby, visible = self._synchronize()
        if not visible:
            self._clear_all()
            return self.state
        index = self._visible_selected_index(visible)
        target = len(visible) - 1 if index is None else max(0, index - 1)
        return self.select_stable_key(visible[target].repeater.stable_key)

    def select_stable_key(self, stable_key: str) -> RepeaterPanelState:
        _nearby, visible = self._synchronize()
        if not any(item.repeater.stable_key == stable_key for item in visible):
            self._clear_all()
            return self.state
        if stable_key != self._selected_stable_key:
            self._selected_stable_key = stable_key
            self._staged_action = None
        return self.state

    def clear_selection(self) -> RepeaterPanelState:
        self._clear_all()
        return self.state

    def stage_selected(self) -> RepeaterPanelState:
        """Capture an exact local Active toggle without persistence or radio work."""
        selected = self._selected_visible_item()
        self._staged_action = (
            StagedRepeaterActiveAction.from_nearby(selected)
            if selected is not None
            else None
        )
        return self.state

    def cancel_staging(self) -> RepeaterPanelState:
        """Cancel only the local Active action."""
        self._staged_action = None
        return self.state

    def apply_persisted_override(
        self,
        action: StagedRepeaterActiveAction,
    ) -> RepeaterPanelState:
        """Apply the completed local Active state."""
        if self._apply_override is not None:
            self._apply_override(action.stable_key, action.target_active)
        return self.state

    def _selected_visible_item(self) -> NearbyRepeater | None:
        _nearby, visible = self._synchronize()
        return next(
            (
                item
                for item in visible
                if item.repeater.stable_key == self._selected_stable_key
            ),
            None,
        )

    def _synchronize(self) -> tuple[NearbyRepeaterState, tuple[NearbyRepeater, ...]]:
        nearby = self._nearby_state()
        if self._source_error is not None or nearby.kind is not NearbyRepeaterStateKind.READY:
            self._clear_all()
            return nearby, ()

        visible = tuple(
            item
            for item in nearby.repeaters
            if self._display_filter is RepeaterDisplayFilter.ALL or item.effective_active
        )
        selected = self._selected_stable_key
        if selected is not None and not any(
            item.repeater.stable_key == selected for item in visible
        ):
            self._clear_all()
            return nearby, visible

        staged = self._staged_action
        if staged is not None:
            current = next(
                (item for item in visible if item.repeater.stable_key == staged.stable_key),
                None,
            )
            if selected != staged.stable_key or current is None or not staged.matches(current):
                self._staged_action = None

        return nearby, visible

    def _visible_selected_index(self, visible: tuple[NearbyRepeater, ...]) -> int | None:
        selected = self._selected_stable_key
        if selected is None:
            return None
        return next(
            (
                index
                for index, item in enumerate(visible)
                if item.repeater.stable_key == selected
            ),
            None,
        )

    def _clear_all(self) -> None:
        self._selected_stable_key = None
        self._staged_action = None
