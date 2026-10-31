"""F02 powertrain: ICE, MGU-K, tapers, zone caps, boost net cap, Overtake mode.

Implements docs/spec/TRD.md Powertrain::

    P_ice       = throttle * P_ice_max[team]
    P_k_allowed = min(zone_cap(s, rule_set),
                      P_k_max * taper(v, mode),
                      boost_cap(activation_power, rule_set))   # post-Miami only
    P_k_deploy  = min(P_k_allowed * deploy_fraction, battery.available_power())

Every rule value comes from the Rule Set (HR-05) and is converted once to SI
(W, m/s, J) in :class:`PowertrainParams`. The functions take and return plain
floats and use no Python objects in their arithmetic, so the Numba step kernel
(T-030) can compile them unchanged.

``deploy_fraction`` (Energy Mode, driver state) is decided by the AI Driver
(T-031) and the battery's available power by T-022; here they are inputs.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from pitwall_sim.config.loader import ConfigError
from pitwall_sim.config.models import RuleSet, TeamPerformance

KMH_TO_MS = 1.0 / 3.6
KW_TO_W = 1_000.0
MJ_TO_J = 1_000_000.0


class PowertrainParams(NamedTuple):
    """Rule Set and team values for one car, in SI units.

    A ``NamedTuple`` so Numba-compiled functions can take it as an argument.
    """

    p_ice_max_w: float
    p_k_max_w: float
    """Team MGU-K limit, never above the Rule Set ``power.p_k_max_kw``."""
    zone_cap_acceleration_w: float
    """MGU-K cap inside ``acceleration_zone`` zones."""
    zone_cap_other_w: float
    """MGU-K cap everywhere else (equal to the above pre-Miami)."""
    boost_net_cap_w: float
    """Boost cap above the total power at activation; ``inf`` when the Rule Set has none."""
    boost_taper_start_ms: float
    boost_taper_end_ms: float
    overtake_taper_start_ms: float
    overtake_taper_end_ms: float
    overtake_extra_energy_j: float
    overtake_activation_gap_s: float


def _value(name: str, value: float | str) -> float:
    if isinstance(value, str):
        raise ConfigError(f"powertrain needs {name}, which is {value}")
    return float(value)


def powertrain_params(rules: RuleSet, team: TeamPerformance) -> PowertrainParams:
    """Convert the Rule Set and one team's coefficients to :class:`PowertrainParams`.

    Raises:
        ConfigError: A value the powertrain uses is still a placeholder.

    """
    power, overtake = rules.power, rules.overtake
    p_k_rule_kw = _value("power.p_k_max_kw", power.p_k_max_kw)
    p_k_team_kw = _value("team p_k_max_kw", team.p_k_max_kw)
    boost_cap_kw = power.boost_net_cap_kw
    return PowertrainParams(
        p_ice_max_w=_value("team p_ice_max_kw", team.p_ice_max_kw)
        * _value("team pu_power_scale", team.pu_power_scale)
        * KW_TO_W,
        p_k_max_w=min(p_k_team_kw, p_k_rule_kw) * KW_TO_W,
        zone_cap_acceleration_w=_value(
            "power.zone_caps_kw.acceleration_zone", power.zone_caps_kw.acceleration_zone
        )
        * KW_TO_W,
        zone_cap_other_w=_value("power.zone_caps_kw.other", power.zone_caps_kw.other) * KW_TO_W,
        boost_net_cap_w=math.inf
        if boost_cap_kw is None
        else _value("power.boost_net_cap_kw", boost_cap_kw) * KW_TO_W,
        boost_taper_start_ms=_value("power.boost_taper_start_kmh", power.boost_taper_start_kmh)
        * KMH_TO_MS,
        boost_taper_end_ms=_value("power.boost_taper_end_kmh", power.boost_taper_end_kmh)
        * KMH_TO_MS,
        overtake_taper_start_ms=_value("overtake.taper_start_kmh", overtake.taper_start_kmh)
        * KMH_TO_MS,
        overtake_taper_end_ms=_value("overtake.taper_end_kmh", overtake.taper_end_kmh) * KMH_TO_MS,
        overtake_extra_energy_j=_value(
            "overtake.extra_energy_mj_per_lap", overtake.extra_energy_mj_per_lap
        )
        * MJ_TO_J,
        overtake_activation_gap_s=_value("overtake.activation_gap_s", overtake.activation_gap_s),
    )


# --------------------------------------------------------------------------- #
# Scalar functions (Numba-compatible)
# --------------------------------------------------------------------------- #


def linear_taper(v_ms: float, start_ms: float, end_ms: float) -> float:
    """1 up to ``start``, linear to 0 at ``end``, 0 beyond (TRD taper functions)."""
    if v_ms <= start_ms:
        return 1.0
    if v_ms >= end_ms:
        return 0.0
    return (end_ms - v_ms) / (end_ms - start_ms)


def taper_boost(v_ms: float, p: PowertrainParams) -> float:
    """MGU-K taper without Overtake mode."""
    return linear_taper(v_ms, p.boost_taper_start_ms, p.boost_taper_end_ms)


def taper_overtake(v_ms: float, p: PowertrainParams) -> float:
    """MGU-K taper while Overtake mode is active."""
    return linear_taper(v_ms, p.overtake_taper_start_ms, p.overtake_taper_end_ms)


def ice_power_w(throttle: float, p: PowertrainParams) -> float:
    """``P_ice = throttle * P_ice_max[team]``, throttle clamped to [0, 1]."""
    return min(max(throttle, 0.0), 1.0) * p.p_ice_max_w


def zone_cap_w(in_acceleration_zone: bool, p: PowertrainParams) -> float:
    """MGU-K cap for the zone the car is in (one value pre-Miami)."""
    return p.zone_cap_acceleration_w if in_acceleration_zone else p.zone_cap_other_w


def boost_cap_w(
    boost_active: bool, activation_total_power_w: float, p_ice_w: float, p: PowertrainParams
) -> float:
    """Post-Miami boost cap on MGU-K power; ``inf`` when boost is off or the Rule Set has none.

    DECIDED (owner, interpretation per Motor Sport Magazine wording): at boost
    activation the car's total power (ICE + MGU-K) is recorded; while boost is
    active, total power may not exceed that recorded power + ``boost_net_cap``.
    With the current ICE power ``p_ice_w`` that leaves this much for the MGU-K.
    The zone cap still applies on top (see :func:`mgu_k_allowed_w`).
    """
    if not boost_active:
        return math.inf
    return max(activation_total_power_w + p.boost_net_cap_w - p_ice_w, 0.0)


def mgu_k_allowed_w(
    v_ms: float,
    in_acceleration_zone: bool,
    overtake_active: bool,
    boost_active: bool,
    activation_total_power_w: float,
    p_ice_w: float,
    p: PowertrainParams,
) -> float:
    """``P_k_allowed``: the lowest of zone cap, tapered MGU-K maximum and boost cap.

    ``activation_total_power_w`` is the total power recorded when boost was
    activated (ignored while boost is off); ``p_ice_w`` is the current ICE power.
    """
    taper = taper_overtake(v_ms, p) if overtake_active else taper_boost(v_ms, p)
    return min(
        zone_cap_w(in_acceleration_zone, p),
        p.p_k_max_w * taper,
        boost_cap_w(boost_active, activation_total_power_w, p_ice_w, p),
    )


def mgu_k_deploy_w(
    p_k_allowed_w: float, deploy_fraction: float, battery_available_w: float
) -> float:
    """``P_k_deploy``: the allowed power scaled by the deploy fraction, limited by the battery."""
    fraction = min(max(deploy_fraction, 0.0), 1.0)
    return min(p_k_allowed_w * fraction, max(battery_available_w, 0.0))


def overtake_available(gap_to_car_ahead_s: float, p: PowertrainParams) -> bool:
    """Overtake mode is earned when the gap at the detection point is within the limit."""
    return 0.0 <= gap_to_car_ahead_s <= p.overtake_activation_gap_s


def overtake_extra_energy_j(
    overtake_active: bool, in_overtaking_zone: bool, p: PowertrainParams
) -> float:
    """Extra energy per lap granted by Overtake mode, usable only inside overtaking zones."""
    if overtake_active and in_overtaking_zone:
        return p.overtake_extra_energy_j
    return 0.0
