"""Race setup screen for the live pit wall lite (sprint S-5)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from pitwall_sim.config.loader import DEFAULT_CONFIG_DIR, load_app, load_grid, load_track
from pitwall_sim.live.presets import PRESETS
from pitwall_sim.live.session import LiveSetup

BG, PANEL, TEXT, CLIP = "#101214", "#181B1F", "#E6E8EB", "#FF4D4F"


class SetupScreen(QDialog):
    """Track, Rule Set, Our Car, seed, Pause on alert, Test mode."""

    def __init__(self, config_dir: Path = DEFAULT_CONFIG_DIR) -> None:
        """Fill the choices from config (grid, Rule Sets)."""
        super().__init__()
        self.setWindowTitle("We Are Racing, Not Testing - race setup")
        self.setStyleSheet(f"background:{BG}; color:{TEXT};")
        grid = load_grid("real_2026", config_dir)
        self._teams = {t.display_name: t for t in grid.teams}
        self.track = QComboBox()
        self.track.addItem("Suzuka", "suzuka")
        self.rules = QComboBox()
        for path in sorted((config_dir / "rules").glob("*.yaml")):
            self.rules.addItem(path.stem, path.stem)
        self.rules.setCurrentText("2026_post_miami")
        self.team = QComboBox()
        self.team.addItems(list(self._teams))
        self.driver = QComboBox()
        self.team.currentTextChanged.connect(self._fill_drivers)
        self._fill_drivers(self.team.currentText())
        full = load_track("suzuka", config_dir).race_laps
        self.full_laps = int(full) if isinstance(full, int) else 53
        self.laps = QSpinBox()  # a short race reaches the flag (and the call summary) quickly
        self.laps.setRange(1, self.full_laps)
        self.laps.setValue(min(load_app(config_dir).ui.default_race_laps, self.full_laps))
        self.sc_lap = QSpinBox()  # demo: force a Safety Car on this lap (0 = off), H4
        self.sc_lap.setRange(0, self.full_laps)
        self.sc_lap.setSpecialValueText("off")
        self.sc_lap.setValue(load_app(config_dir).demo.scripted_sc_lap or 0)
        self.rain_lap = QSpinBox()  # E1: force rain from this lap (0 = off: the track's odds)
        self.rain_lap.setRange(0, self.full_laps)
        self.rain_lap.setSpecialValueText("off")
        self.rain_lap.setValue(load_app(config_dir).demo.rain_lap or 0)
        self.seed = QSpinBox()
        self.seed.setRange(0, 999999)
        self.seed.setValue(42)
        self.preset = QComboBox()
        for key, label in PRESETS.items():
            self.preset.addItem(label, key)
        self.pause_on_alert = QCheckBox("Pause on alert")
        self.test_mode = QCheckBox(
            "Test mode - show Rivals' TRUE battery (a real team can't see it)"
        )
        self.test_mode.setStyleSheet(f"color:{CLIP};")

        form = QFormLayout()
        form.addRow("Track", self.track)
        form.addRow("Rule Set", self.rules)
        form.addRow("Our team", self.team)
        form.addRow("Our driver", self.driver)
        form.addRow("Seed", self.seed)
        form.addRow("Race laps", self.laps)
        form.addRow("Safety Car on lap (demo)", self.sc_lap)
        form.addRow("Rain from lap", self.rain_lap)
        form.addRow("Scenario", self.preset)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Start race")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Live pit wall lite</b> - Suzuka 2026"))
        layout.addLayout(form)
        layout.addWidget(self.pause_on_alert)
        layout.addWidget(self.test_mode)
        layout.addWidget(buttons)

    def _fill_drivers(self, team_name: str) -> None:
        self.driver.clear()
        for d in self._teams[team_name].drivers:
            self.driver.addItem(f"{d.code} - {d.display_name}", d.driver_id)

    def choice(self) -> LiveSetup:
        """Return the setup as chosen."""
        return LiveSetup(
            our_driver_id=str(self.driver.currentData()),
            rule_set_id=str(self.rules.currentData()),
            seed=int(self.seed.value()),
            laps=None if self.laps.value() == self.full_laps else int(self.laps.value()),
            track_id=str(self.track.currentData()),
            pause_on_alert=self.pause_on_alert.isChecked(),
            test_mode=self.test_mode.isChecked(),
            preset=self.preset.currentData(),
            strategy=True,  # the pit wall shows the strategy panel (H5)
            scripted_sc_lap=int(self.sc_lap.value()) or None,
            rain_lap=int(self.rain_lap.value()) or None,
        )
