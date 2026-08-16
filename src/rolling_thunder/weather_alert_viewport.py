"""Deterministic scroll viewport for the driving weather-alert summary."""

from __future__ import annotations

from dataclasses import dataclass
from textwrap import wrap

from rolling_thunder.weather_alert_panel import WeatherAlertPanelPresentation

_DEFAULT_WRAP_WIDTH = 42
_DEFAULT_VISIBLE_LINES = 5


@dataclass(frozen=True)
class WeatherAlertViewportPresentation:
    """Immutable visible slice of the first operator-facing weather alert."""

    text: str
    offset: int
    line_count: int
    visible_line_count: int
    can_scroll_up: bool
    can_scroll_down: bool
    overflowing: bool


class WeatherAlertViewportController:
    """Scroll already-published alert text without provider or hardware work."""

    def __init__(
        self,
        *,
        wrap_width: int = _DEFAULT_WRAP_WIDTH,
        visible_lines: int = _DEFAULT_VISIBLE_LINES,
    ) -> None:
        if wrap_width <= 0:
            raise ValueError("Weather alert wrap width must be positive.")
        if visible_lines <= 0:
            raise ValueError("Weather alert visible line count must be positive.")

        self._wrap_width = wrap_width
        self._visible_lines = visible_lines
        self._signature: tuple[str, str, str] | None = None
        self._lines: tuple[str, ...] = ()
        self._offset = 0
        self._state = self._build_state()

    @property
    def state(self) -> WeatherAlertViewportPresentation:
        """Return the latest immutable alert viewport."""
        return self._state

    def synchronize(
        self,
        presentation: WeatherAlertPanelPresentation,
    ) -> WeatherAlertViewportPresentation:
        """Synchronize with the first displayed alert while preserving position."""
        if not presentation.items:
            self._signature = None
            self._lines = ()
            self._offset = 0
            self._state = self._build_state()
            return self._state

        item = presentation.items[0]
        signature = (item.alert_id, item.area, item.headline)
        lines = self._wrapped_lines(item.area, item.headline)
        if signature != self._signature:
            self._offset = 0
        self._signature = signature
        self._lines = lines
        self._offset = min(self._offset, self._maximum_offset())
        self._state = self._build_state()
        return self._state

    def scroll_previous(self) -> bool:
        """Move one wrapped line toward the beginning when possible."""
        if self._offset <= 0:
            return False
        self._offset -= 1
        self._state = self._build_state()
        return True

    def scroll_next(self) -> bool:
        """Move one wrapped line toward the end when possible."""
        maximum = self._maximum_offset()
        if self._offset >= maximum:
            return False
        self._offset += 1
        self._state = self._build_state()
        return True

    def _wrapped_lines(self, area: str, headline: str) -> tuple[str, ...]:
        lines: list[str] = []
        for paragraph in (area, headline):
            lines.extend(
                wrap(
                    paragraph,
                    width=self._wrap_width,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
                or ("",)
            )
        return tuple(lines)

    def _maximum_offset(self) -> int:
        return max(0, len(self._lines) - self._visible_lines)

    def _build_state(self) -> WeatherAlertViewportPresentation:
        line_count = len(self._lines)
        visible = self._lines[
            self._offset : self._offset + self._visible_lines
        ]
        maximum = self._maximum_offset()
        return WeatherAlertViewportPresentation(
            text="\n".join(visible),
            offset=self._offset,
            line_count=line_count,
            visible_line_count=min(line_count, self._visible_lines),
            can_scroll_up=self._offset > 0,
            can_scroll_down=self._offset < maximum,
            overflowing=line_count > self._visible_lines,
        )
