"""F02 dirty air and slipstream (T-032, TRD Dirty air and slipstream).

Within ``dirty_air.range_m`` of the car ahead (distance along the track) the
following car's wake factor is ``f = 1 - gap / range``; its downforce drops
(``ClA x (1 - downforce_loss_max f)``: slower corners) and so does its drag
(``CdA x (1 - drag_reduction_max f)``: faster straights). Both aero modes are
scaled. The coefficients are ``# PLACEHOLDER: calibrate`` (F20).

The scalar functions are compiled so the step kernel can call them per car.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np
import numpy.typing as npt
from numba import njit

from pitwall_sim.config.models import AppConfig

type FloatArray = npt.NDArray[np.float64]
type BoolArray = npt.NDArray[np.bool_]
type IntArray = npt.NDArray[np.int64]


class DirtyAirParams(NamedTuple):
    """Wake range and the largest downforce / drag reductions (at zero gap)."""

    range_m: float
    downforce_loss_max: float
    drag_reduction_max: float


def dirty_air_params(app: AppConfig) -> DirtyAirParams:
    """Wake coefficients from ``app.yaml`` (``dirty_air``, ``slipstream``)."""
    return DirtyAirParams(
        range_m=app.dirty_air.range_m,
        downforce_loss_max=app.dirty_air.downforce_loss_max,
        drag_reduction_max=app.slipstream.drag_reduction_max,
    )


@njit(cache=True, inline="always")
def wake_factor(gap_m: float, range_m: float) -> float:
    """``1 - gap / range`` within range of the car ahead, else 0."""
    if gap_m < 0.0 or gap_m >= range_m:
        return 0.0
    return 1.0 - gap_m / range_m


@njit(cache=True, inline="always")
def downforce_scale(f: float, downforce_loss_max: float) -> float:
    """``ClA`` multiplier for wake factor ``f``."""
    return 1.0 - downforce_loss_max * f


@njit(cache=True, inline="always")
def drag_scale(f: float, drag_reduction_max: float) -> float:
    """``CdA`` multiplier for wake factor ``f``."""
    return 1.0 - drag_reduction_max * f


@njit(cache=True)
def gaps_ahead_m(
    s_m: FloatArray,
    running: BoolArray,
    in_pit: BoolArray,
    length_m: float,
    out: FloatArray,
    out_idx: IntArray,
) -> None:
    """Distance along the track from each car on track to the nearest car ahead on track.

    Lap-independent (a lapped car ahead on the road counts); ``inf`` and index
    -1 when the car is alone, not running or in the pit lane (pit-lane cars and
    the track do not interact). ``O(n^2)``, cheap for 22 cars.
    """
    n = s_m.size
    for i in range(n):
        best = math.inf
        ahead = -1
        if running[i] and not in_pit[i]:
            for j in range(n):
                if j == i or not running[j] or in_pit[j]:
                    continue
                gap = s_m[j] - s_m[i]
                if gap <= 0.0:
                    gap += length_m
                if gap < best:
                    best = gap
                    ahead = j
        out[i] = best
        out_idx[i] = ahead
