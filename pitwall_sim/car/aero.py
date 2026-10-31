"""F02 active aero: Straight Mode / Corner Mode (TRD Active aero).

``STRAIGHT_MODE`` on zones tagged ``straight_mode_allowed`` in the track config
when throttle >= ``aero.straight_mode_throttle_min``; otherwise
``CORNER_MODE``. Drag and downforce areas per mode come from the team config.
Dirty air (T-032) scales these later.

Modes are returned as the int codes of :data:`pitwall_sim.race.state.AERO_MODES`
(what ``CarArrays.aero_mode`` stores), and parameters are a ``NamedTuple``, so
the Numba kernel (T-030) can compile these functions unchanged.
"""

from __future__ import annotations

from typing import NamedTuple

from pitwall_sim.config.loader import ConfigError
from pitwall_sim.config.models import AeroConfig, TeamPerformance
from pitwall_sim.race.state import AERO_MODES

STRAIGHT_MODE = AERO_MODES.index("STRAIGHT_MODE")
CORNER_MODE = AERO_MODES.index("CORNER_MODE")


class AeroParams(NamedTuple):
    """One team's aero areas (m^2) and the Straight Mode throttle threshold."""

    cda_straight: float
    cda_corner: float
    cla_straight: float
    cla_corner: float
    straight_mode_throttle_min: float


def _value(name: str, value: float | str) -> float:
    if isinstance(value, str):
        raise ConfigError(f"aero needs team {name}, which is {value}")
    return float(value)


def aero_params(team: TeamPerformance, cfg: AeroConfig) -> AeroParams:
    """Build :class:`AeroParams` for one team.

    Raises:
        ConfigError: A team aero coefficient is still a placeholder.

    """
    return AeroParams(
        cda_straight=_value("cda_straight", team.cda_straight),
        cda_corner=_value("cda_corner", team.cda_corner),
        cla_straight=_value("cla_straight", team.cla_straight),
        cla_corner=_value("cla_corner", team.cla_corner),
        straight_mode_throttle_min=cfg.straight_mode_throttle_min,
    )


def aero_mode(in_straight_mode_zone: bool, throttle: float, p: AeroParams) -> int:
    """``STRAIGHT_MODE`` in an allowed zone at (near) full throttle, else ``CORNER_MODE``."""
    if in_straight_mode_zone and throttle >= p.straight_mode_throttle_min:
        return STRAIGHT_MODE
    return CORNER_MODE


def cda(mode: int, p: AeroParams) -> float:
    """Drag area ``CdA`` (m^2) for an aero mode code."""
    return p.cda_straight if mode == STRAIGHT_MODE else p.cda_corner


def cla(mode: int, p: AeroParams) -> float:
    """Downforce area ``ClA`` (m^2) for an aero mode code."""
    return p.cla_straight if mode == STRAIGHT_MODE else p.cla_corner
