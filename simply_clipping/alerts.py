"""P9 alerts: ATTACK, DEFEND, RE-PASS RISK, CLOSING-SPEED RISK from ``our``'s view.

Rules and thresholds: spec ALERT RULES (config ``alerts.*``); the same pair and
type is suppressed for ``alerts.suppress_laps``; closing-speed alerts are one
per episode, for the single biggest-closing rival (lesson L-f).
Scaffold (SC-0): ``no_alerts`` only.
"""

from __future__ import annotations

import pandas as pd

from simply_clipping.loader import Config, Feed

ALERT_TYPES = ("ATTACK", "DEFEND", "REPASS_RISK", "CLOSING_SPEED_RISK")
ALERT_COLUMNS = ("time_s", "lap", "type", "car_a", "car_b", "confidence", "branch")


def no_alerts() -> pd.DataFrame:
    """Return an empty ``alerts.parquet`` table with the contract's columns."""
    return pd.DataFrame({
        "time_s": pd.Series(dtype="float64"), "lap": pd.Series(dtype="int64"),
        "type": pd.Series(dtype="str"), "car_a": pd.Series(dtype="str"),
        "car_b": pd.Series(dtype="str"), "confidence": pd.Series(dtype="float64"),
        "branch": pd.Series(dtype="str"),
    })  # fmt: skip


def offline_alerts(
    feed: Feed, estimates: pd.DataFrame, own: pd.DataFrame, our: str, cfg: Config
) -> pd.DataFrame:
    """Every alert for ``our`` over the race, one row when it fires."""
    raise NotImplementedError("SC-5 / SC-6: alert rules")
