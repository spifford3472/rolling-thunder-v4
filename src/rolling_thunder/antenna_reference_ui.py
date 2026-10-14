"""Tk presentation for the optional offline antenna/RF advisory panel."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

from rolling_thunder.antenna_reference_domain import ExposureDistanceKind
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

PUBLIC_TABLE_COLUMNS = ("BAND", "MODE", "POWER", "PUBLIC MIN")

_DENSE_DISPLAY_HEIGHT_PX = 720
_STATUS_BAR_HEIGHT_PX = 76
_CONTEXT_OUTER_VERTICAL_MARGIN_PX = 20
_CONTEXT_BORDER_PX = 2
_CONTEXT_CONTENT_VERTICAL_PADDING_PX = 16
_CONTEXT_HEADER_FONT_SIZE = 31
_CONTEXT_HEADER_VERTICAL_PADDING_PX = 10
_ANTENNA_POSITION_FONT_SIZE = 16
_ANTENNA_POSITION_VERTICAL_PADDING_PX = 1
_ANTENNA_NOTICE_FONT_SIZE = 12
_ANTENNA_NOTICE_VERTICAL_PADDING_PX = 2
_ANTENNA_CARD_BORDER_PX = 4
_ANTENNA_TABLE_VERTICAL_PADDING_PX = 4
_TK_DEFAULT_PIXELS_PER_INCH = 96.0
_TK_FONT_LINE_HEIGHT_FACTOR = 1.2
_TK_LABEL_VERTICAL_CHROME_PX = 4


@dataclass(frozen=True)
class PublicTableRow:
    """One display row for a configured public-separation scenario."""

    band: str
    mode: str
    power: str
    public_minimum: str

    @property
    def cells(self) -> tuple[str, str, str, str]:
        return (self.band, self.mode, self.power, self.public_minimum)


@dataclass(frozen=True)
class PublicTableLayout:
    """Responsive typography and row sizing for the in-car table."""

    heading_font_size: int
    row_font_size: int
    heading_height_px: int
    header_height_px: int
    row_height_px: int
    footer_height_px: int
    required_height_px: int


@dataclass(frozen=True)
class AntennaVerticalBudget:
    """Measured vertical budget from the physical display down to the inner table."""

    display_height_px: int
    table_usable_height_px: int


def tk_label_required_height_px(
    font_size_points: int,
    *,
    line_count: int = 1,
    pixels_per_inch: float = _TK_DEFAULT_PIXELS_PER_INCH,
) -> int:
    """Conservatively model Tk's point conversion, line spacing, and label border."""
    em_pixels = ceil(font_size_points * pixels_per_inch / 72.0)
    line_height = ceil(em_pixels * _TK_FONT_LINE_HEIGHT_FACTOR)
    return (line_height * line_count) + _TK_LABEL_VERTICAL_CHROME_PX


def antenna_vertical_budget(
    display_height_px: int = _DENSE_DISPLAY_HEIGHT_PX,
    *,
    pixels_per_inch: float = _TK_DEFAULT_PIXELS_PER_INCH,
) -> AntennaVerticalBudget:
    """Return the real table height after the dashboard and antenna-page chrome."""
    context_header_height = tk_label_required_height_px(
        _CONTEXT_HEADER_FONT_SIZE,
        pixels_per_inch=pixels_per_inch,
    )
    position_height = tk_label_required_height_px(
        _ANTENNA_POSITION_FONT_SIZE,
        pixels_per_inch=pixels_per_inch,
    )
    notice_height = tk_label_required_height_px(
        _ANTENNA_NOTICE_FONT_SIZE,
        pixels_per_inch=pixels_per_inch,
    )
    fixed_chrome = sum(
        (
            _STATUS_BAR_HEIGHT_PX,
            _CONTEXT_OUTER_VERTICAL_MARGIN_PX,
            _CONTEXT_BORDER_PX,
            _CONTEXT_CONTENT_VERTICAL_PADDING_PX,
            context_header_height,
            _CONTEXT_HEADER_VERTICAL_PADDING_PX,
            position_height,
            _ANTENNA_POSITION_VERTICAL_PADDING_PX,
            notice_height,
            _ANTENNA_NOTICE_VERTICAL_PADDING_PX,
            _ANTENNA_CARD_BORDER_PX,
            _ANTENNA_TABLE_VERTICAL_PADDING_PX,
        )
    )
    return AntennaVerticalBudget(
        display_height_px=display_height_px,
        table_usable_height_px=max(0, display_height_px - fixed_chrome),
    )


def public_table_layout(
    usable_height_px: int,
    row_count: int,
    *,
    pixels_per_inch: float = _TK_DEFAULT_PIXELS_PER_INCH,
) -> PublicTableLayout:
    """Choose the largest legible typography whose Tk requests fit the viewport."""
    candidates = ((17, 20), (16, 19), (15, 18))
    heading_font_size, row_font_size = candidates[-1]
    for candidate_heading, candidate_row in candidates:
        candidate_fixed = (
            tk_label_required_height_px(
                candidate_heading,
                pixels_per_inch=pixels_per_inch,
            )
            + tk_label_required_height_px(
                max(14, candidate_row - 4),
                pixels_per_inch=pixels_per_inch,
            )
            + (
                2
                * tk_label_required_height_px(
                    max(12, candidate_row - 7),
                    pixels_per_inch=pixels_per_inch,
                )
            )
        )
        # PUBLIC MIN is intentionally one point larger than the other cells and
        # therefore determines Tk's requested height for every four-column row.
        candidate_rows = row_count * tk_label_required_height_px(
            candidate_row + 1,
            pixels_per_inch=pixels_per_inch,
        )
        if candidate_fixed + candidate_rows <= usable_height_px:
            heading_font_size, row_font_size = candidate_heading, candidate_row
            break

    heading_height = tk_label_required_height_px(
        heading_font_size,
        pixels_per_inch=pixels_per_inch,
    )
    header_height = tk_label_required_height_px(
        max(14, row_font_size - 4),
        pixels_per_inch=pixels_per_inch,
    )
    row_height = tk_label_required_height_px(
        row_font_size + 1,
        pixels_per_inch=pixels_per_inch,
    )
    footer_height = 2 * tk_label_required_height_px(
        max(12, row_font_size - 7),
        pixels_per_inch=pixels_per_inch,
    )
    required_height = heading_height + header_height + footer_height + row_height * row_count
    return PublicTableLayout(
        heading_font_size=heading_font_size,
        row_font_size=row_font_size,
        heading_height_px=heading_height,
        header_height_px=header_height,
        row_height_px=row_height,
        footer_height_px=footer_height,
        required_height_px=required_height,
    )


def public_table_row_bounds(
    layout: PublicTableLayout,
    row_count: int,
) -> tuple[tuple[int, int], ...]:
    """Return each data row's top/bottom coordinates inside the table viewport."""
    first_row_top = layout.heading_height_px + layout.header_height_px
    return tuple(
        (
            first_row_top + (index * layout.row_height_px),
            first_row_top + ((index + 1) * layout.row_height_px),
        )
        for index in range(row_count)
    )


def _band_label(frequency_hz: int) -> str:
    if 7_000_000 <= frequency_hz < 7_300_000:
        return "40m"
    if 14_000_000 <= frequency_hz < 14_350_000:
        return "20m"
    if 21_000_000 <= frequency_hz < 21_450_000:
        return "15m"
    if 28_000_000 <= frequency_hz < 29_700_000:
        return "10m"
    if 50_000_000 <= frequency_hz < 54_000_000:
        return "6m"
    if 144_000_000 <= frequency_hz < 148_000_000:
        return "2m"
    if 420_000_000 <= frequency_hz <= 450_000_000:
        return "70cm"
    return f"{frequency_hz / 1e6:g}M"


def _mode_label(name: str) -> str:
    normalized = name.upper()
    if "SSB" in normalized:
        return "SSB"
    if "FT8" in normalized:
        return "FT8"
    return "FM"


def public_table_rows(card: AntennaReferenceCard) -> tuple[PublicTableRow, ...]:
    """Select public scenarios and format their four operator-facing values."""
    rows: list[PublicTableRow] = []
    for item in card.evaluations:
        if item.scenario.distance_kind is not ExposureDistanceKind.HYPOTHETICAL_SIX_FOOT:
            continue
        estimate = item.zero_loss_screening or item.result
        required = (
            f"{estimate.uncontrolled.estimated_required_distance_m / 0.3048:.1f} ft"
            if estimate.uncontrolled is not None
            else "N/A"
        )
        rows.append(
            PublicTableRow(
                band=_band_label(item.scenario.frequency.hz),
                mode=_mode_label(item.mode.name),
                power=f"{item.scenario.forward_tx_watts:g} W",
                public_minimum=required,
            )
        )
    return tuple(rows)


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
        self._rendered_state: AntennaPanelState | None = None
        self._row_labels: list[tuple[Any, ...]] = []
        self.frame = tk.Frame(parent, bg=_BACKGROUND)
        self._pixels_per_inch = float(self.frame.winfo_fpixels("1i"))
        self.frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=0)
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
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=(0, 1))

        card = tk.Frame(
            self.frame,
            bg=_PANEL,
            highlightthickness=2,
            highlightbackground=_BORDER,
        )
        card.grid(row=1, column=0, sticky="nsew", padx=4)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)
        self._message = tk.StringVar(value="Loading offline antenna records…")
        self._message_label = tk.Label(
            card,
            textvariable=self._message,
            bg=_PANEL,
            fg=_BRIGHT,
            font=("DejaVu Sans", 20, "bold"),
            justify="left",
            anchor="center",
            wraplength=450,
        )
        self._message_label.grid(row=0, column=0, sticky="nsew", padx=18, pady=14)

        self._table = tk.Frame(card, bg=_PANEL)
        self._table.grid(row=0, column=0, sticky="nsew", padx=8, pady=2)
        column_weights = (17, 17, 23, 43)
        for column, weight in enumerate(column_weights):
            self._table.grid_columnconfigure(
                column,
                weight=weight,
                uniform="antenna-table",
            )

        self._heading_label = tk.Label(
            self._table,
            text="ARRL RF EXPOSURE CALCULATOR",
            bg=_PANEL,
            fg=_BRIGHT,
            font=("DejaVu Sans", 17, "bold"),
            anchor="center",
            justify="center",
        )
        self._heading_label.grid(row=0, column=0, columnspan=4, sticky="nsew")

        self._header_labels: list[Any] = []
        for column, text in enumerate(PUBLIC_TABLE_COLUMNS):
            label = tk.Label(
                self._table,
                text=text,
                bg=_BORDER,
                fg=_WARNING if column == 3 else _BRIGHT,
                font=("DejaVu Sans", 16, "bold"),
                anchor="center",
                highlightthickness=1,
                highlightbackground=_PANEL,
            )
            label.grid(row=1, column=column, sticky="nsew")
            self._header_labels.append(label)

        self._footer = tk.Frame(self._table, bg=_PANEL)
        self._footer.grid(row=2, column=0, columnspan=4, sticky="nsew")
        self._footer.grid_columnconfigure(0, weight=1)
        self._footer.grid_rowconfigure(0, weight=1)
        self._footer.grid_rowconfigure(1, weight=1)
        self._footer_labels = (
            tk.Label(
                self._footer,
                text="6 ft boundary • 0 dB loss assumed",
                bg=_PANEL,
                fg=_WARNING,
                font=("DejaVu Sans", 13, "bold"),
                anchor="center",
            ),
            tk.Label(
                self._footer,
                text="Estimate only • Not FCC certification",
                bg=_PANEL,
                fg=_MUTED,
                font=("DejaVu Sans", 13, "bold"),
                anchor="center",
            ),
        )
        for row, label in enumerate(self._footer_labels):
            label.grid(row=row, column=0, sticky="nsew")
        self._table.bind("<Configure>", self._resize_table)
        self._table.grid_remove()

        footer = tk.Frame(self.frame, bg=_BACKGROUND)
        footer.grid(row=2, column=0, sticky="ew", padx=4, pady=(2, 0))
        footer.grid_columnconfigure(0, weight=1)
        self._notice = tk.StringVar(
            value="READ ONLY • YAML+RESTART • NO RADIO/POWER"
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
        if state == self._rendered_state:
            return
        self._rendered_state = state
        self._state = state
        if state.status is AntennaPanelStatus.LOADING:
            self._position.set("OFFLINE REFERENCE • LOADING")
            self._show_message("Loading antenna and installation records…")
            return
        if state.error is not None:
            self._position.set("OFFLINE REFERENCE • ERROR")
            self._show_message(state.error, foreground=_ERROR)
            return
        card = state.selected_card
        if card is None:
            self._position.set("HF  •  VHF  •  UHF")
            self._show_message(
                "NO ANTENNA OR INSTALLATION RECORDS\n\n"
                "No manufacturer, model, gain, loss, band, six-metre capability, or "
                "vehicle geometry is assumed. Add sourced records to the manual antenna "
                "YAML off-car, validate it, and restart Rolling Thunder."
            )
            return
        assert state.selected_index is not None
        self._position.set(
            f"{state.selected_index + 1}/{len(state.cards)} • {card.antenna_name} • ENCODER ◀ ▶"
        )
        self._show_table(public_table_rows(card))

    def _show_message(self, text: str, *, foreground: str = _BRIGHT) -> None:
        self._table.grid_remove()
        self._message.set(text)
        self._message_label.configure(fg=foreground)
        self._message_label.grid()

    def _show_table(self, rows: tuple[PublicTableRow, ...]) -> None:
        import tkinter as tk

        self._message_label.grid_remove()
        previous_row_count = max(1, len(self._row_labels))
        for row_index in range(2, 3 + previous_row_count):
            self._table.grid_rowconfigure(row_index, weight=0, minsize=0)
        for stale_labels in self._row_labels:
            for label in stale_labels:
                label.destroy()
        self._row_labels.clear()

        if rows:
            for row_index, row in enumerate(rows, start=2):
                cell_labels: list[Any] = []
                row_background = _PANEL if row_index % 2 == 0 else _BACKGROUND
                for column, text in enumerate(row.cells):
                    label = tk.Label(
                        self._table,
                        text=text,
                        bg=row_background,
                        fg=_WARNING if column == 3 else _BRIGHT,
                        font=("DejaVu Sans", 20 + (1 if column == 3 else 0), "bold"),
                        anchor="center",
                        highlightthickness=1,
                        highlightbackground=_BORDER,
                    )
                    label.grid(row=row_index, column=column, sticky="nsew")
                    cell_labels.append(label)
                self._row_labels.append(tuple(cell_labels))
        else:
            label = tk.Label(
                self._table,
                text="NO PUBLIC-SEPARATION SCENARIOS",
                bg=_PANEL,
                fg=_WARNING,
                font=("DejaVu Sans", 20, "bold"),
                anchor="center",
            )
            label.grid(row=2, column=0, columnspan=4, sticky="nsew")
            self._row_labels.append((label,))

        footer_row = 2 + max(1, len(rows))
        self._footer.grid_configure(row=footer_row)
        self._table.grid()
        measured_height = self._table.winfo_height()
        fallback_height = antenna_vertical_budget(
            pixels_per_inch=self._pixels_per_inch,
        ).table_usable_height_px
        self._apply_table_layout(max(measured_height, fallback_height))

    def _resize_table(self, event: Any) -> None:
        if event.height >= 300:
            self._apply_table_layout(event.height)

    def _apply_table_layout(self, usable_height_px: int) -> None:
        row_count = max(1, len(self._row_labels))
        layout = public_table_layout(
            usable_height_px,
            row_count,
            pixels_per_inch=self._pixels_per_inch,
        )
        self._heading_label.configure(
            font=("DejaVu Sans", layout.heading_font_size, "bold")
        )
        self._table.grid_rowconfigure(0, weight=0, minsize=layout.heading_height_px)
        self._table.grid_rowconfigure(1, weight=0, minsize=layout.header_height_px)
        header_font_size = max(14, layout.row_font_size - 4)
        for label in self._header_labels:
            label.configure(font=("DejaVu Sans", header_font_size, "bold"))
        for offset, labels in enumerate(self._row_labels, start=2):
            self._table.grid_rowconfigure(
                offset,
                weight=0,
                minsize=layout.row_height_px,
            )
            for column, label in enumerate(labels):
                size = layout.row_font_size + (1 if column == 3 and len(labels) == 4 else 0)
                label.configure(font=("DejaVu Sans", size, "bold"))
        footer_row = 2 + row_count
        self._table.grid_rowconfigure(
            footer_row,
            weight=0,
            minsize=layout.footer_height_px,
        )
        footer_font_size = max(12, layout.row_font_size - 7)
        for label in self._footer_labels:
            label.configure(font=("DejaVu Sans", footer_font_size, "bold"))


def compact_public_table_lines(card: AntennaReferenceCard) -> tuple[str, ...]:
    """Retain the plain-text projection used by non-Tk callers and tests."""
    rows = public_table_rows(card)
    lines = [
        "Based on ARRL RF Exposure Calculator",
        "",
        "BAND   MODE   POWER   PUBLIC MIN",
        "----   ----   -----   ----------",
    ]
    for row in rows:
        lines.append(f"{row.band:<6} {row.mode:<5}  {row.power:>5}   {row.public_minimum:>8}")
    if not rows:
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
