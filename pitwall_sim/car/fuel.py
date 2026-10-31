"""F02 fuel: mass burn from ICE power (TRD Fuel).

``m_fuel`` falls with ``P_ice`` integrated over time: the fuel energy rate is
``P_ice / ice_efficiency`` and the mass rate that divided by the fuel's energy
density (team config). The Rule Set fuel energy-flow limit
(``fuel.max_fuel_energy_flow_mj_per_h``) caps the fuel energy rate, so it also
caps ICE power at ``ice_efficiency * max_flow``.

Start fuel mass per track is UNKNOWN (TRD) and set by calibration so a race
ends with >= 0 kg; here it is an input. Functions use plain floats and a
``NamedTuple`` so the Numba kernel (T-030) can compile them unchanged.
"""

from __future__ import annotations

from typing import NamedTuple

from pitwall_sim.car.powertrain import MJ_TO_J
from pitwall_sim.config.loader import ConfigError
from pitwall_sim.config.models import RuleSet, TeamPerformance

S_PER_H = 3_600.0


class FuelParams(NamedTuple):
    """One team's fuel conversion and the Rule Set flow limit, SI units."""

    ice_efficiency: float
    """Brake power out per fuel power in."""
    energy_density_j_per_kg: float
    max_energy_flow_w: float
    """Fuel energy-flow limit (Rule Set), as fuel power."""


def _value(name: str, value: float | str) -> float:
    if isinstance(value, str):
        raise ConfigError(f"fuel needs {name}, which is {value}")
    return float(value)


def fuel_params(rules: RuleSet, team: TeamPerformance) -> FuelParams:
    """Build :class:`FuelParams` for one team.

    Raises:
        ConfigError: A value the fuel model uses is still a placeholder.

    """
    flow_mj_per_h = _value(
        "fuel.max_fuel_energy_flow_mj_per_h", rules.fuel.max_fuel_energy_flow_mj_per_h
    )
    return FuelParams(
        ice_efficiency=_value("team ice_efficiency", team.ice_efficiency),
        energy_density_j_per_kg=_value(
            "team fuel_energy_density_mj_per_kg", team.fuel_energy_density_mj_per_kg
        )
        * MJ_TO_J,
        max_energy_flow_w=flow_mj_per_h * MJ_TO_J / S_PER_H,
    )


def max_ice_power_w(p: FuelParams) -> float:
    """ICE power the fuel energy-flow limit allows (3000 MJ/h at 50% -> ~417 kW)."""
    return p.ice_efficiency * p.max_energy_flow_w


def fuel_flow_w(p_ice_w: float, p: FuelParams) -> float:
    """Fuel energy rate for an ICE power, capped at the Rule Set flow limit."""
    return min(max(p_ice_w, 0.0) / p.ice_efficiency, p.max_energy_flow_w)


def burn(fuel_kg: float, p_ice_w: float, dt_s: float, p: FuelParams) -> float:
    """Fuel mass after ``dt_s`` at ICE power ``p_ice_w``; never increases, never below 0."""
    burned_kg = fuel_flow_w(p_ice_w, p) * max(dt_s, 0.0) / p.energy_density_j_per_kg
    return max(fuel_kg - burned_kg, 0.0)
