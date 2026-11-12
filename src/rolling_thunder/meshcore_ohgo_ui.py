"""Large-text, scrollable MeshCore/OHGO viewport and rotary action adapter.

This viewport never fetches network data or mutates provider state. Only
accepted, context-scoped rotary movements scroll its displayed text.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from rolling_thunder.context_navigation import ContextId
from rolling_thunder.control_dispatcher import EventAwareInterceptor
from rolling_thunder.physical_controls import ControlAction, ControlInputEvent

_OHGO_BODY_FONT = ("DejaVu Sans", 42, "bold")
_OHGO_MORE_FONT = ("DejaVu Sans", 27, "bold")


class MeshcoreOhgoScrollInterceptor(EventAwareInterceptor):
    """Consume only rotary scroll actions within the active OHGO context."""

    def __init__(
        self,
        *,
        selected_context: Callable[[], ContextId],
        scroll: Callable[[ControlAction], bool],
        allowed: Callable[[], bool] = lambda: True,
    ) -> None:
        self._selected_context = selected_context
        self._scroll = scroll
        self._allowed = allowed

    def intercept(self, event: ControlInputEvent, action: ControlAction) -> bool | None:
        """Return None outside this context so existing controls keep priority."""

        if (
            action not in (ControlAction.MOVE_NEXT, ControlAction.MOVE_PREVIOUS)
            or self._selected_context() is not ContextId.MESHCORE_OHGO
        ):
            return None
        if not self._allowed():
            # Do not forward a gated turn to unrelated selection handlers.
            return False
        return self._scroll(action)


class MeshcoreOhgoWidgets:
    """Dedicated, word-wrapped Text viewport with a fixed bottom MORE indicator."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        background: str,
        foreground: str,
    ) -> None:
        self.frame = tk.Frame(parent, bg=background)
        self.frame.grid(row=1, column=0, sticky="nsew", padx=3, pady=2)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)
        self._body = tk.Text(
            self.frame,
            bg=background,
            fg=foreground,
            font=_OHGO_BODY_FONT,
            wrap="word",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            takefocus=0,
            cursor="arrow",
            width=1,
            height=1,
            padx=6,
            pady=4,
            spacing2=5,
            spacing3=10,
            state="disabled",
            yscrollcommand=self._on_scroll,
        )
        self._body.grid(row=0, column=0, sticky="nsew")
        self._more = tk.StringVar(value="")
        tk.Label(
            self.frame,
            textvariable=self._more,
            bg=background,
            fg="#ffffff",
            font=_OHGO_MORE_FONT,
            anchor="center",
        ).grid(row=1, column=0, sticky="ew", pady=(1, 0))
        self._last_content: str | None = None
        self._visible = True
        self._last_more = ""
        self.hide()

    def _on_scroll(self, first: float, last: float) -> None:
        """Derive MORE from actual rendered text geometry, not guessed line count."""

        more = "MORE" if float(last) < 0.999 else ""
        if more != self._last_more:
            self._last_more = more
            self._more.set(more)

    def update(self, content: str) -> None:
        """Only replace changed data, preserving the operator's scroll position."""

        if content == self._last_content:
            return
        self._last_content = content
        self._body.configure(state="normal")
        self._body.delete("1.0", "end")
        self._body.insert("1.0", content)
        self._body.configure(state="disabled")
        self._body.yview_moveto(0.0)

    def scroll(self, action: ControlAction) -> bool:
        """Scroll one wrapped display line in the requested rotary direction."""

        if action is ControlAction.MOVE_NEXT:
            self._body.yview_scroll(1, "units")
            return True
        if action is ControlAction.MOVE_PREVIOUS:
            self._body.yview_scroll(-1, "units")
            return True
        return False

    @property
    def visible(self) -> bool:
        """Whether the viewport is selected and should remain mapped."""

        return self._visible

    def show(self) -> None:
        """Map only on context entry, avoiding refresh-driven blank frames."""

        if not self._visible:
            self.frame.grid()
            self._visible = True

    def hide(self) -> None:
        """Unmap only on context exit, not during routine refreshes."""

        if self._visible:
            self.frame.grid_remove()
            self._visible = False
