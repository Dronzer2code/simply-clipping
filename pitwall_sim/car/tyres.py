"""F02 tyres: grip, wear, temperature (TRD Tyres).

::

    mu_tyre    = mu_base[compound] * f_temp(T_tyre) * f_wear(wear)
    d(wear)/dt = k_wear[compound] * abrasiveness * (|F_long| + |F_lat|) * v / norm
                 * driver_mgmt_factor
    f_wear(w)  = 1 - a*w                        for w <  cliff_w
               = 1 - a*cliff_w - b*(w - cliff_w)  for w >= cliff_w

MVP (MVP.md F02): tyre temperature is fixed at the compound's optimum, so
``f_temp = 1``; the temperature model (``dT/dt``, heat_gain, cool_rate) is
T-100. Wetness and the wet/intermediate crossover (``wet_grip_factor``) come
with the weather model (T-039).

Wear is a fraction: 0 new, capped at 1. ``norm`` is ``tyres.yaml: wear_norm_j``.
Functions use plain floats and a ``NamedTuple`` so the Numba kernel (T-030) can
compile them unchanged.
"""

from __future__ import annotations

from typing import NamedTuple

from pitwall_sim.config.loader import ConfigError
from pitwall_sim.config.models import Compound, TyreConfig


class TyreParams(NamedTuple):
    """One compound's coefficients plus the wear normalisation."""

    mu_base: float
    k_wear: float
    cliff_w: float
    a_wear: float
    b_wear: float
    t_optimal_c: float
    wear_norm_j: float


def tyre_params(tyres: TyreConfig, compound: Compound) -> TyreParams:
    """Build :class:`TyreParams` for one compound.

    Raises:
        ConfigError: The compound is missing or a coefficient is a placeholder.

    """
    c = tyres.compounds.get(compound)
    if c is None:
        raise ConfigError(f"tyres.yaml has no {compound} entry")
    values = {
        "mu_base": c.mu_base,
        "k_wear": c.k_wear,
        "cliff_w": c.cliff_w,
        "a_wear": c.a_wear,
        "b_wear": c.b_wear,
        "t_optimal_c": c.t_optimal_c,
    }
    for name, value in values.items():
        if isinstance(value, str):
            raise ConfigError(f"tyres need {compound}.{name}, which is {value}")
    return TyreParams(**{k: float(v) for k, v in values.items()}, wear_norm_j=tyres.wear_norm_j)


def f_wear(wear: float, p: TyreParams) -> float:
    """Grip factor from wear: linear to the cliff, steeper after it, never below 0."""
    w = min(max(wear, 0.0), 1.0)
    if w < p.cliff_w:
        factor = 1.0 - p.a_wear * w
    else:
        factor = 1.0 - p.a_wear * p.cliff_w - p.b_wear * (w - p.cliff_w)
    return max(factor, 0.0)


def tyre_temp_c(p: TyreParams) -> float:
    """MVP: tyre temperature held at the compound optimum (T-100 replaces this)."""
    return p.t_optimal_c


def f_temp(temp_c: float, p: TyreParams) -> float:
    """MVP: 1 (temperature held at optimum); T-100 adds the temperature curve."""
    return 1.0


def mu_tyre(wear: float, temp_c: float, p: TyreParams) -> float:
    """Tyre friction coefficient ``mu_base * f_temp * f_wear``."""
    return p.mu_base * f_temp(temp_c, p) * f_wear(wear, p)


def wear_rate_per_s(
    f_long_n: float,
    f_lat_n: float,
    v_ms: float,
    abrasiveness: float,
    driver_mgmt_factor: float,
    p: TyreParams,
) -> float:
    """Wear per second: ``k_wear * abrasiveness * (|F_long| + |F_lat|) * v / norm * mgmt``."""
    work_w = (abs(f_long_n) + abs(f_lat_n)) * abs(v_ms)
    rate = p.k_wear * abrasiveness * work_w / p.wear_norm_j * driver_mgmt_factor
    return max(rate, 0.0)


def step_wear(wear: float, rate_per_s: float, dt_s: float) -> float:
    """Wear after ``dt_s``; never decreases, capped at 1."""
    return min(wear + max(rate_per_s, 0.0) * max(dt_s, 0.0), 1.0)
