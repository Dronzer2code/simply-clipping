"""F02 battery: integration, clamp, harvest sources, super-clip, per-lap counters.

Implements docs/spec/TRD.md Battery::

    E(t+dt) = clip(E(t) + (P_harvest - P_k_deploy / eta_discharge) * dt, 0, E_usable_max)

with the per-lap limits: energy harvested this lap may not exceed the race
harvest limit (resolved per race: S1 value -> track override -> Rule Set
default) plus the Overtake extra energy while Overtake mode is active; energy
deployed this lap may not exceed ``deploy_max_mj_per_lap`` when a Rule Set sets
one (both 2026 Rule Sets set none). Counters reset at the timing line, and at
the formation lap start when the Rule Set says so (post-Miami only).

Units are SI (J, W, s). ``CarState`` stores MJ (``battery_mj``,
``harvest_mj_lap``, ``deploy_mj_lap``); the step kernel converts at the array
boundary. Functions use plain floats and a ``NamedTuple`` so the Numba kernel
(T-030) can compile them unchanged.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from pitwall_sim.car.powertrain import KW_TO_W, MJ_TO_J
from pitwall_sim.config.loader import ConfigError
from pitwall_sim.config.models import RuleSet, TeamPerformance


class BatteryParams(NamedTuple):
    """Battery limits for one car in one race, SI units."""

    e_usable_max_j: float
    harvest_limit_j: float
    """Race harvest limit per lap, before the Overtake extra."""
    overtake_extra_j: float
    deploy_limit_j: float
    """Per-lap deploy limit; ``inf`` when the Rule Set has none."""
    harvest_max_w: float
    """MGU-K harvest power limit: the Rule Set MGU-K maximum, which applies both ways."""
    superclip_power_w: float
    partial_harvest_max_w: float
    brake_harvest_share: float
    discharge_efficiency: float
    reset_at_formation_lap: bool


class BatteryStep(NamedTuple):
    """Result of one :func:`step`: new state plus the energy that moved."""

    battery_j: float
    harvest_lap_j: float
    deploy_lap_j: float
    harvested_j: float
    """Energy stored this step."""
    drawn_j: float
    """Energy taken from the battery this step (before discharge losses)."""


def _value(name: str, value: float | str) -> float:
    if isinstance(value, str):
        raise ConfigError(f"battery needs {name}, which is {value}")
    return float(value)


def battery_params(rules: RuleSet, team: TeamPerformance, harvest_limit_mj: float) -> BatteryParams:
    """Battery limits for one car.

    Args:
        rules: The race's Rule Set.
        team: The car's team coefficients.
        harvest_limit_mj: Race harvest limit per lap, from
            ``config.loader.resolve_harvest_limit_mj`` (S1 value -> track -> Rule Set).

    Raises:
        ConfigError: A value the battery uses is still a placeholder.

    """
    energy = rules.energy
    reset = energy.energy_counter_reset
    if reset in ("UNRESOLVED", "UNKNOWN"):
        raise ConfigError(f"battery needs energy.energy_counter_reset, which is {reset}")
    deploy_limit = energy.deploy_max_mj_per_lap
    return BatteryParams(
        e_usable_max_j=_value("energy.e_usable_max_mj", energy.e_usable_max_mj) * MJ_TO_J,
        harvest_limit_j=harvest_limit_mj * MJ_TO_J,
        overtake_extra_j=_value(
            "overtake.extra_energy_mj_per_lap", rules.overtake.extra_energy_mj_per_lap
        )
        * MJ_TO_J,
        deploy_limit_j=math.inf
        if deploy_limit is None
        else _value("energy.deploy_max_mj_per_lap", deploy_limit) * MJ_TO_J,
        harvest_max_w=_value("power.p_k_max_kw", rules.power.p_k_max_kw) * KW_TO_W,
        superclip_power_w=_value("energy.superclip_power_kw", energy.superclip_power_kw) * KW_TO_W,
        partial_harvest_max_w=_value("team partial_harvest_max_kw", team.partial_harvest_max_kw)
        * KW_TO_W,
        brake_harvest_share=_value("team brake_harvest_share", team.brake_harvest_share),
        discharge_efficiency=_value(
            "team battery_discharge_efficiency", team.battery_discharge_efficiency
        ),
        reset_at_formation_lap=reset == "formation_lap_start",
    )


# --------------------------------------------------------------------------- #
# Harvest sources (TRD Battery table)
# --------------------------------------------------------------------------- #


def braking_harvest_w(brake_power_w: float, p: BatteryParams) -> float:
    """``min(P_k_harvest_max, brake_power * harvest_share)``."""
    return min(p.harvest_max_w, max(brake_power_w, 0.0) * p.brake_harvest_share)


def superclip_harvest_w(p: BatteryParams) -> float:
    """Super-clipping at full throttle: harvest at ``superclip_power_kw``."""
    return min(p.superclip_power_w, p.harvest_max_w)


def part_throttle_harvest_w(requested_w: float, p: BatteryParams) -> float:
    """Part-throttle harvest, capped at the team's ``partial_harvest_max_kw``."""
    return min(p.partial_harvest_max_w, p.harvest_max_w, max(requested_w, 0.0))


# --------------------------------------------------------------------------- #
# Limits and integration
# --------------------------------------------------------------------------- #


def lap_harvest_limit_j(overtake_active: bool, p: BatteryParams) -> float:
    """Harvest allowed this lap: race limit, plus the Overtake extra while active."""
    return p.harvest_limit_j + (p.overtake_extra_j if overtake_active else 0.0)


def available_deploy_w(
    battery_j: float, deploy_lap_j: float, dt_s: float, p: BatteryParams
) -> float:
    """MGU-K power the battery can supply for one step (TRD ``battery.available_power``).

    Limited by the stored energy and any per-lap deploy allowance left,
    after discharge losses, so a full step at this power cannot overdraw.
    """
    if dt_s <= 0.0:
        return 0.0
    drawable_j = min(max(battery_j, 0.0), max(p.deploy_limit_j - deploy_lap_j, 0.0))
    return drawable_j * p.discharge_efficiency / dt_s


def step(
    battery_j: float,
    harvest_lap_j: float,
    deploy_lap_j: float,
    p_harvest_w: float,
    p_k_deploy_w: float,
    overtake_active: bool,
    dt_s: float,
    p: BatteryParams,
) -> BatteryStep:
    """Integrate one step and update the per-lap counters.

    Harvest is cut at the per-lap allowance and when the battery is full;
    the draw is cut at the stored energy and any per-lap deploy allowance.
    So ``0 <= battery <= E_usable_max`` and both counters stay within their
    limits for any inputs, including negative or huge powers.
    """
    dt = max(dt_s, 0.0)
    battery = min(max(battery_j, 0.0), p.e_usable_max_j)

    harvest_room = max(lap_harvest_limit_j(overtake_active, p) - harvest_lap_j, 0.0)
    harvested = min(max(p_harvest_w, 0.0) * dt, harvest_room, p.e_usable_max_j - battery)

    # Harvest room is measured before the draw (so the window is never exceeded),
    # and the draw may use energy harvested in this same step.
    deploy_room = max(p.deploy_limit_j - deploy_lap_j, 0.0)
    drawn = min(
        max(p_k_deploy_w, 0.0) * dt / p.discharge_efficiency, battery + harvested, deploy_room
    )

    battery = battery + harvested - drawn  # in [0, E_usable_max] by construction
    return BatteryStep(
        battery_j=min(max(battery, 0.0), p.e_usable_max_j),
        harvest_lap_j=harvest_lap_j + harvested,
        deploy_lap_j=deploy_lap_j + drawn,
        harvested_j=harvested,
        drawn_j=drawn,
    )


def reset_at_timing_line() -> tuple[float, float]:
    """Per-lap counters ``(harvest_lap_j, deploy_lap_j)`` at the start of a new lap."""
    return 0.0, 0.0


def reset_at_formation_lap(
    harvest_lap_j: float, deploy_lap_j: float, p: BatteryParams
) -> tuple[float, float]:
    """Counters at the formation lap start: reset post-Miami, unchanged pre-Miami."""
    if p.reset_at_formation_lap:
        return 0.0, 0.0
    return harvest_lap_j, deploy_lap_j
