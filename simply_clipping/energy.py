"""P6-P7 energy: states, integration, anchors, confidence.

States DEPLOY / CLIP / HARVEST / LIFT / CRUISE (spec STATES); energy integrated
and clamped to [energy.e_min_mj, energy.e_max_mj]. Lessons designed in: L-a (a
super-clip is not an empty battery: no anchor to 0 on every CLIP), L-b (the
regulated speed taper is not CLIP), L-e (honest confidence).

Scaffold (SC-0): ``prior_estimates`` writes a constant prior so the bench runs;
SC-3 and SC-4 replace it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from simply_clipping.loader import Config, const

STATES = ("DEPLOY", "CLIP", "HARVEST", "LIFT", "CRUISE")
ESTIMATE_COLUMNS = ("driver", "time_s", "energy_mj", "state", "confidence")


def classify_states(car: pd.DataFrame, cfg: Config) -> pd.Series:
    """Per sample state from throttle, brake, estimated P_elec and acceleration (L-b)."""
    raise NotImplementedError("SC-3: states, taper-aware")


def integrate(car: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Energy, anchors (L-a) and confidence (L-e) per sample for one car."""
    raise NotImplementedError("SC-4: energy integration, anchors, confidence")


def prior_estimates(cars: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Scaffold output: every car at ``output.estimates_hz`` with the prior energy.

    The state is the throttle / brake part of the STATES table only (no power yet):
    HARVEST on brake, LIFT below ``states.lift_throttle_pct``, CRUISE otherwise.
    """
    hz = float(const(cfg, "output.estimates_hz"))
    tick = np.floor(cars["time"].to_numpy() * hz)
    est = cars.assign(_tick=tick).groupby(["driver", "_tick"], sort=True).first().reset_index()
    state = np.where(
        est["brake"].to_numpy(dtype=bool),
        "HARVEST",
        np.where(est["throttle"] < float(const(cfg, "states.lift_throttle_pct")), "LIFT", "CRUISE"),
    )
    return pd.DataFrame({
        "driver": est["driver"].astype(str),
        "time_s": est["time"].astype(float),
        "energy_mj": float(const(cfg, "energy.prior_mj")),
        "state": state,
        "confidence": float(const(cfg, "energy.prior_confidence")),
    })  # fmt: skip
