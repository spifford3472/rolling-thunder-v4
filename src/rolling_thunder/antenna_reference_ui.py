"""Tk presentation for the optional offline antenna/RF advisory panel."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rolling_thunder.antenna_reference_domain import (
    GroundReflectionModel,
    TextProvenance,
)
from rolling_thunder.antenna_reference_panel import (
    AntennaEvaluationRequest,
    AntennaPanelState,
    AntennaPanelStatus,
    AntennaReferenceCard,
    ReferenceMode,
)
from rolling_thunder.rf_exposure_calculator import (
    ExposureEnvironment,
    RfExposureResult,
    fcc_mpe_limit,
)

_BACKGROUND = "#151515"
_PANEL = "#101010"
_BORDER = "#303030"
_BRIGHT = "#ffffff"
_MUTED = "#a8a8a8"
_WARNING = "#ffd24a"
_ACCENT = "#66ccff"
_ERROR = "#ff6b6b"


def card_summary_lines(card: AntennaReferenceCard) -> tuple[str, ...]:
    """Return compact truthful catalog/installation lines."""
    lines = [
        f"{card.region.value}  •  {card.antenna_name}",
        f"INSTALLATION  {card.installation_name}",
        "BANDS  " + (", ".join(card.bands) if card.bands else "NONE RECORDED"),
        "GAIN  " + ("; ".join(card.gain_lines) if card.gain_lines else "UNKNOWN"),
        "LOSS  " + ("; ".join(card.loss_lines) if card.loss_lines else "UNKNOWN"),
        f"LOSS INVENTORY  {'COMPLETE' if card.losses_complete else 'INCOMPLETE'}",
        f"PROVENANCE  {card.provenance}",
    ]
    if any("6m " in band.casefold() or "6 m " in band.casefold() for band in card.bands):
        lines.append("6 M  EXPLICITLY ASSOCIATED WITH THIS ANTENNA")
    return tuple(lines)


def evaluation_lines(
    result: RfExposureResult,
    *,
    frequency_mhz: float | None = None,
) -> tuple[str, ...]:
    """Format an advisory without a pass/fail, safe, or compliance verdict."""
    if not result.inputs_complete:
        limit_lines: tuple[str, ...] = ()
        if frequency_mhz is not None:
            controlled = fcc_mpe_limit(frequency_mhz, ExposureEnvironment.CONTROLLED)
            uncontrolled = fcc_mpe_limit(frequency_mhz, ExposureEnvironment.UNCONTROLLED)
            limit_lines = (
                f"CONTROLLED / 6 MIN LIMIT  {controlled.power_density_mw_cm2:.4g} mW/cm²",
                (
                    "UNCONTROLLED / 30 MIN LIMIT  "
                    f"{uncontrolled.power_density_mw_cm2:.4g} mW/cm²"
                ),
            )
        return (
            "ADVISORY INCOMPLETE — NO SAFETY OR COMPLIANCE FINDING",
            *(f"MISSING  {item}" for item in result.missing_inputs),
            *limit_lines,
            (
                f"DISTANCE  {result.evaluated_distance_m:.3f} m "
                f"({'MEASURED' if result.distance_verified else 'UNVERIFIED'})"
            ),
        )
    assert result.erp_watts_peak is not None
    assert result.eirp_watts_peak is not None
    assert result.controlled is not None
    assert result.uncontrolled is not None
    return (
        "REFERENCE ESTIMATE — NOT A SAFETY OR COMPLIANCE FINDING",
        f"PEAK ERP  {result.erp_watts_peak:.2f} W    EIRP  {result.eirp_watts_peak:.2f} W",
        (
            "CONTROLLED / 6 MIN  "
            f"LIMIT {result.controlled.limit.power_density_mw_cm2:.4g} mW/cm²  "
            f"EST. DIST {result.controlled.estimated_required_distance_m:.3f} m"
        ),
        (
            "UNCONTROLLED / 30 MIN  "
            f"LIMIT {result.uncontrolled.limit.power_density_mw_cm2:.4g} mW/cm²  "
            f"EST. DIST {result.uncontrolled.estimated_required_distance_m:.3f} m"
        ),
        (
            f"SCENARIO DISTANCE  {result.evaluated_distance_m:.3f} m "
            f"({'MEASURED' if result.distance_verified else 'UNVERIFIED'})"
        ),
        (
            f"REFLECTION  {result.ground_reflection_model.value} "
            f"({result.ground_reflection_power_factor:g}× power density)"
        ),
    )


class AntennaReferenceWidgets:
    """Render published state and an explicitly setup-gated scenario editor."""

    def __init__(
        self,
        parent: Any,
        *,
        setup_enabled: bool,
        submit_evaluation: Callable[[AntennaEvaluationRequest], bool],
    ) -> None:
        import tkinter as tk

        self._tk = tk
        self._setup_enabled = setup_enabled
        self._submit_evaluation = submit_evaluation
        self._state = AntennaPanelState()
        self.frame = tk.Frame(parent, bg=_BACKGROUND)
        self.frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(1, weight=1)
        self.frame.grid_remove()

        self._position = tk.StringVar(value="")
        tk.Label(
            self.frame,
            textvariable=self._position,
            bg=_BACKGROUND,
            fg=_ACCENT,
            font=("DejaVu Sans", 16, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=(2, 4))

        card = tk.Frame(
            self.frame,
            bg=_PANEL,
            highlightthickness=2,
            highlightbackground=_BORDER,
        )
        card.grid(row=1, column=0, sticky="nsew", padx=4)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)
        self._body = tk.StringVar(value="Loading offline antenna records…")
        self._body_label = tk.Label(
            card,
            textvariable=self._body,
            bg=_PANEL,
            fg=_BRIGHT,
            font=("DejaVu Sans", 15, "bold"),
            justify="left",
            anchor="nw",
            wraplength=570,
        )
        self._body_label.grid(row=0, column=0, sticky="nsew", padx=12, pady=10)

        footer = tk.Frame(self.frame, bg=_BACKGROUND)
        footer.grid(row=2, column=0, sticky="ew", padx=4, pady=(5, 0))
        footer.grid_columnconfigure(0, weight=1)
        self._notice = tk.StringVar(
            value="VIEW ONLY • ENCODER MOVES • NO RADIO OR POWER CONTROL"
        )
        tk.Label(
            footer,
            textvariable=self._notice,
            bg=_BACKGROUND,
            fg=_WARNING,
            font=("DejaVu Sans", 12, "bold"),
            justify="left",
            anchor="w",
            wraplength=430,
        ).grid(row=0, column=0, sticky="ew")
        self._evaluate_button = tk.Button(
            footer,
            text="PARKED SETUP: EVALUATE",
            command=self.open_evaluation_editor,
            font=("DejaVu Sans", 12, "bold"),
            bg="#274754",
            fg=_BRIGHT,
            activebackground="#315f73",
            activeforeground=_BRIGHT,
            padx=8,
            pady=5,
        )
        if setup_enabled:
            self._evaluate_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

    def show(self) -> None:
        self.frame.grid()

    def hide(self) -> None:
        self.frame.grid_remove()

    def update(self, state: AntennaPanelState) -> None:
        """Render only immutable state already published by the controller."""
        self._state = state
        if state.status is AntennaPanelStatus.LOADING:
            self._position.set("OFFLINE REFERENCE • LOADING")
            self._body.set("Loading antenna and installation records…")
            return
        if state.error is not None:
            self._position.set("OFFLINE REFERENCE • ERROR")
            self._body.set(state.error)
            self._body_label.configure(fg=_ERROR)
            return
        self._body_label.configure(fg=_BRIGHT)
        card = state.selected_card
        if card is None:
            self._position.set("HF  •  VHF  •  UHF")
            self._body.set(
                "NO ANTENNA OR INSTALLATION RECORDS\n\n"
                "No manufacturer, model, gain, loss, band, six-metre capability, or "
                "vehicle geometry is assumed. Add sourced records during a parked bench "
                "setup session before evaluating an installation."
            )
            self._evaluate_button.configure(state="disabled")
            return
        assert state.selected_index is not None
        self._position.set(
            f"{state.selected_index + 1}/{len(state.cards)}  •  "
            "ENCODER PREVIOUS / NEXT"
        )
        lines = list(card_summary_lines(card))
        request = state.evaluation_request
        if request is not None:
            lines.extend(
                (
                    "",
                    f"MODE  {request.mode.value}    FREQUENCY  {request.frequency_mhz:g} MHz",
                    f"FORWARD POWER  {request.forward_tx_watts:g} W (MANUAL INPUT)",
                    (
                        f"TX FRACTION  6 MIN {request.controlled_tx_fraction:g}  •  "
                        f"30 MIN {request.uncontrolled_tx_fraction:g}"
                    ),
                )
            )
        if state.evaluation is not None:
            lines.extend(
                (
                    "",
                    *evaluation_lines(
                        state.evaluation,
                        frequency_mhz=(
                            None if request is None else request.frequency_mhz
                        ),
                    ),
                )
            )
            lines.extend(("", "CAUTION  NEAR-FIELD / VEHICLE GEOMETRY / MULTISOURCE NOT MODELED"))
        elif state.status is AntennaPanelStatus.EVALUATING:
            lines.extend(("", "CALCULATING TRANSIENT ADVISORY…"))
        self._body.set("\n".join(lines))
        self._evaluate_button.configure(
            state=(
                "normal"
                if self._setup_enabled and card.installation_id is not None
                else "disabled"
            )
        )

    def open_evaluation_editor(self) -> None:
        """Open a deliberate mouse/keyboard-only parked setup form."""
        if not self._setup_enabled:
            return
        card = self._state.selected_card
        installation_id = None if card is None else card.installation_id
        if card is None or installation_id is None:
            return

        tk = self._tk
        window = tk.Toplevel(self.frame)
        window.title("Parked RF Exposure Advisory Setup")
        window.configure(bg=_BACKGROUND)
        window.geometry("900x680")
        window.transient(self.frame.winfo_toplevel())

        tk.Label(
            window,
            text="PARKED BENCH ENTRY — REFERENCE ONLY",
            bg=_BACKGROUND,
            fg=_WARNING,
            font=("DejaVu Sans", 20, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(16, 4))
        tk.Label(
            window,
            text=(
                "This does not read or set radio power and cannot establish compliance or safety. "
                "Use measured occupant/public geometry; 6 ft is only an unverified scenario."
            ),
            bg=_BACKGROUND,
            fg=_BRIGHT,
            font=("DejaVu Sans", 13),
            wraplength=820,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 12))

        values: dict[str, Any] = {
            "mode": tk.StringVar(value=ReferenceMode.FT8.value),
            "frequency": tk.StringVar(value=""),
            "power": tk.StringVar(value=""),
            "controlled": tk.StringVar(value=""),
            "uncontrolled": tk.StringVar(value=""),
            "distance": tk.StringVar(value="6"),
            "verified": tk.BooleanVar(value=False),
            "reflection": tk.StringVar(value=GroundReflectionModel.ARRL_TYPICAL_GROUND.value),
            "source": tk.StringVar(value=""),
        }
        fields = (
            ("Mode / RF envelope", "mode"),
            ("Frequency (MHz)", "frequency"),
            ("Forward power (W, manually entered)", "power"),
            ("Controlled TX fraction / 6 min (0-1)", "controlled"),
            ("Uncontrolled TX fraction / 30 min (0-1)", "uncontrolled"),
            ("Distance (ft)", "distance"),
            ("Reflection assumption", "reflection"),
            ("Operator provenance / source", "source"),
        )
        for row, (label, key) in enumerate(fields, start=2):
            tk.Label(
                window,
                text=label,
                bg=_BACKGROUND,
                fg=_BRIGHT,
                font=("DejaVu Sans", 13, "bold"),
                anchor="e",
            ).grid(row=row, column=0, sticky="e", padx=(18, 10), pady=5)
            if key == "mode":
                widget = tk.OptionMenu(window, values[key], *(item.value for item in ReferenceMode))
            elif key == "reflection":
                widget = tk.OptionMenu(
                    window,
                    values[key],
                    *(item.value for item in GroundReflectionModel),
                )
            else:
                widget = tk.Entry(
                    window,
                    textvariable=values[key],
                    font=("DejaVu Sans", 13),
                    width=46,
                )
            widget.grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=5)

        verified_row = len(fields) + 2
        tk.Checkbutton(
            window,
            text="Distance is measured/verified for this occupant or public location",
            variable=values["verified"],
            bg=_BACKGROUND,
            fg=_BRIGHT,
            selectcolor=_PANEL,
            activebackground=_BACKGROUND,
            activeforeground=_BRIGHT,
            font=("DejaVu Sans", 13),
        ).grid(row=verified_row, column=1, sticky="w", padx=(0, 18), pady=8)
        message = tk.StringVar(value="")
        tk.Label(
            window,
            textvariable=message,
            bg=_BACKGROUND,
            fg=_ERROR,
            font=("DejaVu Sans", 12, "bold"),
            wraplength=820,
            justify="left",
        ).grid(row=verified_row + 1, column=0, columnspan=2, sticky="ew", padx=18)

        def submit() -> None:
            try:
                request = AntennaEvaluationRequest(
                    installation_id=installation_id,
                    mode=ReferenceMode(values["mode"].get()),
                    frequency_mhz=float(values["frequency"].get()),
                    forward_tx_watts=float(values["power"].get()),
                    controlled_tx_fraction=float(values["controlled"].get()),
                    uncontrolled_tx_fraction=float(values["uncontrolled"].get()),
                    distance_feet=float(values["distance"].get()),
                    distance_verified=bool(values["verified"].get()),
                    ground_reflection_model=GroundReflectionModel(
                        values["reflection"].get()
                    ),
                    provenance=TextProvenance(source=values["source"].get()),
                )
            except (TypeError, ValueError) as error:
                message.set(f"Check every explicit input: {error}")
                return
            if not self._submit_evaluation(request):
                message.set("An advisory is already running or the installation changed.")
                return
            window.destroy()

        buttons = tk.Frame(window, bg=_BACKGROUND)
        buttons.grid(
            row=verified_row + 2,
            column=0,
            columnspan=2,
            sticky="e",
            padx=18,
            pady=16,
        )
        tk.Button(buttons, text="CANCEL", command=window.destroy, padx=16, pady=7).pack(
            side="left", padx=6
        )
        tk.Button(
            buttons,
            text="CALCULATE ADVISORY",
            command=submit,
            bg="#274754",
            fg=_BRIGHT,
            padx=16,
            pady=7,
        ).pack(side="left", padx=6)
