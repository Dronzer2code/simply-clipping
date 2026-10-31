"""P2-P5 physics: resample, smooth, acceleration, wheel and electric power, CdA fit.

Radar spec (docs/spec/SIMPLY_CLIPPING_SPEC.md PIPELINE)::

    resample to 10 Hz, Savitzky-Golay (7, 2), acceleration
    P_wheel = m*a*v + 0.5*rho*CdA*v^3 + Crr*m*g*v
    P_elec  = P_wheel / eta - P_ICE

Lessons designed in: L-c (partial deploy: the CdA fit must not assume 350 kW),
L-d (ICE power per maker, mass falls with fuel). Scaffold (SC-0): signatures only.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pandas as pd

from simply_clipping.loader import Config

Array = npt.NDArray[np.float64]


def resample(car: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """One car's stream on a uniform ``signal.resample_hz`` grid, no bridging of long gaps."""
    raise NotImplementedError("SC-1: resample to signal.resample_hz")


def acceleration(v_ms: Array, cfg: Config) -> tuple[Array, Array]:
    """Savitzky-Golay smoothed speed and its derivative (m/s, m/s^2)."""
    raise NotImplementedError("SC-1: Savitzky-Golay (signal.savgol_window, signal.savgol_order)")


def mass_kg(team_id: str, lap: Array, cfg: Config) -> Array:
    """Car mass with the fuel left on each lap (lesson L-d)."""
    raise NotImplementedError("SC-1: car.mass_kg + fuel left")


def p_ice_kw(team_id: str, cfg: Config) -> float:
    """ICE power of the team's maker (lesson L-d), default ``car.p_ice_kw``."""
    raise NotImplementedError("SC-1: car.p_ice_kw_by_team")


def wheel_power_kw(v_ms: Array, a_ms2: Array, m_kg: Array, cda_m2: Array, cfg: Config) -> Array:
    """P_wheel = m*a*v + 0.5*rho*CdA*v^3 + Crr*m*g*v, in kW."""
    raise NotImplementedError("SC-1: wheel power")


def electric_power_kw(p_wheel_kw: Array, p_ice: float, cfg: Config) -> Array:
    """P_elec = P_wheel / eta - P_ICE, in kW."""
    raise NotImplementedError("SC-1: electric power")


def fit_cda(car: pd.DataFrame, layout: dict[str, object], cfg: Config) -> dict[str, float]:
    """CdA per aero mode (``cda_fit.aero_modes``) for one car, partial deploy allowed (L-c)."""
    raise NotImplementedError("SC-2: CdA fit per car per aero mode")
