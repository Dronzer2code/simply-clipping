"""F11 Radar physics: wheel power from Public Feed samples (T-051, TRD steps 1-3).

Only Public Feed values and the Radar's own constants (``app.yaml: radar.*``)
are used, never the simulator's true team values, so estimates carry realistic
model error (TRD RIVAL BATTERY RADAR).
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

type FloatArray = npt.NDArray[np.float64]

G_MS2 = 9.80665
KMH_TO_MS = 1.0 / 3.6


def savgol_coefficients(window: int, order: int, deriv: int, dt: float) -> FloatArray:
    """Savitzky-Golay weights for the centre sample of an odd ``window`` (step 1).

    ``weights @ samples`` gives the smoothed value (``deriv`` 0) or derivative
    (``deriv`` 1, per second) at the window's centre.
    """
    if window % 2 == 0 or window <= order:
        raise ValueError(f"savgol window must be odd and > order, got {window}, {order}")
    half = window // 2
    x = np.arange(-half, half + 1, dtype=np.float64) * dt
    vander = np.vander(x, order + 1, increasing=True)
    pinv = np.linalg.pinv(vander)
    weights: FloatArray = pinv[deriv] * math.factorial(deriv)
    return weights


def resample(t_s: FloatArray, values: FloatArray, grid_s: FloatArray) -> FloatArray:
    """Linear resampling onto ``grid_s`` (step 1; dropped frames are bridged)."""
    return np.interp(grid_s, t_s, values)


def wheel_power_w(
    v_ms: FloatArray | float,
    a_ms2: FloatArray | float,
    cda_m2: FloatArray | float,
    mass_kg: float,
    rho: float,
    c_rr: float,
) -> FloatArray | float:
    """``P_wheel = m a v + 1/2 rho CdA v^3 + C_rr m g v`` (step 2)."""
    return mass_kg * a_ms2 * v_ms + 0.5 * rho * cda_m2 * v_ms**3 + c_rr * mass_kg * G_MS2 * v_ms


def electric_power_w(p_wheel_w: float, eta: float, p_ice_w: float) -> float:
    """``P_elec = P_wheel / eta - P_ICE`` (step 3): > 0 deploying, < 0 harvesting."""
    return p_wheel_w / eta - p_ice_w
