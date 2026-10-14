"""Tk presentation for the optional offline antenna/RF advisory panel."""

from __future__ import annotations

from typing import Any

from rolling_thunder.antenna_reference_panel import (
    AntennaPanelState,
    AntennaPanelStatus,
    AntennaReferenceCard,
)
from rolling_thunder.antenna_reference_service import AntennaScenarioEvaluation
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
    """Render immutable file-backed antenna and scenario state."""

    def __init__(self, parent: Any) -> None:
        import tkinter as tk

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
            font=("DejaVu Sans Mono", 15, "bold"),
            justify="left",
            anchor="nw",
            wraplength=0,
        )
        self._body_label.grid(row=0, column=0, sticky="nsew", padx=12, pady=10)

        footer = tk.Frame(self.frame, bg=_BACKGROUND)
        footer.grid(row=2, column=0, sticky="ew", padx=4, pady=(5, 0))
        footer.grid_columnconfigure(0, weight=1)
        self._notice = tk.StringVar(
            value="READ ONLY • MANUAL YAML + RESTART • NO RADIO OR POWER CONTROL"
        )
        tk.Label(
            footer,
            textvariable=self._notice,
            bg=_BACKGROUND,
            fg=_WARNING,
            font=("DejaVu Sans", 12, "bold"),
            justify="left",
            anchor="w",
            wraplength=570,
        ).grid(row=0, column=0, sticky="ew")

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
                "vehicle geometry is assumed. Add sourced records to the manual antenna "
                "YAML off-car, validate it, and restart Rolling Thunder."
            )
            return
        assert state.selected_index is not None
        self._position.set(
            f"{state.selected_index + 1}/{len(state.cards)}  •  "
            "ENCODER PREVIOUS / NEXT"
        )
        self._position.set(
            f"{state.selected_index + 1}/{len(state.cards)} • {card.antenna_name} • ENCODER ◀ ▶"
        )
        self._body.set("\n".join(compact_public_table_lines(card)))


def compact_public_table_lines(card: AntennaReferenceCard) -> tuple[str, ...]:
    """Show one large-print row per mode, with public MPE separation only."""
    public = [
        e for e in card.evaluations
        if e.scenario.distance_kind.value == "hypothetical_six_foot"
    ]
    lines = [
        "Based on ARRL RF Exposure Calculator",
        "",
        "BAND   MODE   POWER   PUBLIC MIN",
        "----   ----   -----   ----------",
    ]
    for item in public:
        hz = item.scenario.frequency.hz
        band = (
            "40m" if 7_000_000 <= hz < 7_300_000 else
            "20m" if 14_000_000 <= hz < 14_350_000 else
            "15m" if 21_000_000 <= hz < 21_450_000 else
            "10m" if 28_000_000 <= hz < 29_700_000 else
            "6m" if 50_000_000 <= hz < 54_000_000 else
            "2m" if 144_000_000 <= hz < 148_000_000 else
            "70cm" if 420_000_000 <= hz <= 450_000_000 else
            f"{hz / 1e6:g}M"
        )
        mode = "SSB" if "SSB" in item.mode.name.upper() else (
            "FT8" if "FT8" in item.mode.name.upper() else "FM"
        )
        estimate = item.zero_loss_screening or item.result
        required = (
            f"{estimate.uncontrolled.estimated_required_distance_m / 0.3048:.1f} ft"
            if estimate.uncontrolled is not None else "N/A"
        )
        lines.append(
            f"{band:<6} {mode:<5}  {item.scenario.forward_tx_watts:>3g} W   {required:>8}"
        )
    if not public:
        lines.append("NO PUBLIC-SEPARATION SCENARIOS")
    lines.extend((
        "",
        "6 ft public boundary • 0 dB loss assumed",
        "Estimate only • Not FCC certification",
    ))
    return tuple(lines)


def scenario_evaluation_lines(
    evaluation: AntennaScenarioEvaluation,
) -> tuple[str, ...]:
    """Format every file-authoritative scenario input before its result."""
    scenario = evaluation.scenario
    screening = evaluation.zero_loss_screening
    screen_lines: tuple[str, ...] = ()
    if screening is not None and screening.uncontrolled is not None:
        feet = screening.uncontrolled.estimated_required_distance_m / 0.3048
        ratio = (
            screening.uncontrolled.estimated_power_density_mw_cm2
            / screening.uncontrolled.limit.power_density_mw_cm2
            * 100
        )
        screen_lines = (
            "BASED ON ARRL RF EXPOSURE CALCULATOR",
            f"EST. PUBLIC/DRIVER REQUIRED DISTANCE  {feet:.2f} ft",
            f"EST. EXPOSURE AT SCENARIO DISTANCE  {ratio:.1f}% OF UNCONTROLLED MPE",
            "ASSUMPTION: 0 dB CABLE/DUPLEXER LOSS",
            "ESTIMATE ONLY — NOT AN FCC COMPLIANCE DETERMINATION",
        )
    return (
        f"SCENARIO  {scenario.name}  •  MODE {evaluation.mode.name}",
        (
            f"{scenario.frequency.mhz:g} MHz  •  {scenario.forward_tx_watts:g} W FORWARD  •  "
            f"RF DUTY {evaluation.mode.rf_envelope_duty:g}"
        ),
        (
            f"TX FRACTION  6 MIN {scenario.controlled_tx_fraction:g}  •  "
            f"30 MIN {scenario.uncontrolled_tx_fraction:g}"
        ),
        f"DISTANCE BASIS  {scenario.distance_kind.value}",
        f"MODE SOURCE  {evaluation.mode.provenance.source}",
        f"SCENARIO SOURCE  {scenario.provenance.source}",
        *screen_lines,
        *(
            ()
            if screening is not None
            else evaluation_lines(
                evaluation.result,
                frequency_mhz=scenario.frequency.mhz,
            )
        ),
    )
