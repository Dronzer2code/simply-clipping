"""Config loading, validation and ``UNRESOLVED`` / ``UNKNOWN`` reporting.

Every loader here reads YAML, validates it against the matching pydantic model
in :mod:`pitwall_sim.config.models`, and can report which keys still carry a
placeholder value. HR-05: rule and coefficient values come from these files,
never from code. HR-09: placeholders are reported, never invented.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from pitwall_sim.config.models import (
    UNKNOWN,
    UNRESOLVED,
    AppConfig,
    GridConfig,
    RuleSet,
    TeamPerformanceConfig,
    TrackConfig,
    TyreConfig,
)

logger = logging.getLogger(__name__)

#: The literal strings that stand in for a value the docs have not resolved.
PLACEHOLDER_VALUES: frozenset[str] = frozenset({UNRESOLVED, UNKNOWN})

DEFAULT_CONFIG_DIR = Path("config")


class ConfigError(Exception):
    """A config file is missing, unparseable, or fails schema validation."""


@dataclass(frozen=True)
class UnresolvedKey:
    """One config key whose value is still ``UNRESOLVED`` or ``UNKNOWN``."""

    source: str
    """Config file the key came from, e.g. ``config/rules/2026_pre_miami.yaml``."""

    key: str
    """Dotted path to the key, e.g. ``energy.harvest_max_mj_per_lap_race``."""

    placeholder: str
    """Either ``UNRESOLVED`` or ``UNKNOWN``."""

    def __str__(self) -> str:
        """Render as ``source: key = PLACEHOLDER`` for reports and test output."""
        return f"{self.source}: {self.key} = {self.placeholder}"


@dataclass
class LoadedConfig:
    """Everything loaded for one race setup, plus the placeholder report."""

    app: AppConfig
    rules: RuleSet
    grid: GridConfig
    teams: TeamPerformanceConfig
    tyres: TyreConfig
    track: TrackConfig | None = None
    unresolved: list[UnresolvedKey] = field(default_factory=list)


def _walk(value: Any, prefix: str, source: str, out: list[UnresolvedKey]) -> None:
    """Collect placeholder leaves of ``value`` into ``out``."""
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            _walk(getattr(value, name), f"{prefix}.{name}" if prefix else name, source, out)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            key_text = key.value if hasattr(key, "value") else str(key)
            _walk(item, f"{prefix}.{key_text}" if prefix else key_text, source, out)
    elif isinstance(value, str | bytes) is False and isinstance(value, Sequence):
        for index, item in enumerate(value):
            _walk(item, f"{prefix}[{index}]", source, out)
    elif isinstance(value, str) and value in PLACEHOLDER_VALUES:
        out.append(UnresolvedKey(source=source, key=prefix, placeholder=value))


def unresolved_keys(model: BaseModel, source: str) -> list[UnresolvedKey]:
    """Return every key in ``model`` whose value is ``UNRESOLVED`` or ``UNKNOWN``.

    Args:
        model: A validated config model.
        source: Path of the file the model was loaded from, used in the report.

    Returns:
        One :class:`UnresolvedKey` per placeholder leaf, in document order.

    """
    out: list[UnresolvedKey] = []
    _walk(model, "", source, out)
    return out


def load_yaml(path: Path) -> dict[str, Any]:
    """Read one YAML file into a mapping.

    Raises:
        ConfigError: The file is missing, unparseable, or not a mapping.

    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{path}: cannot be read: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping, got {type(data).__name__}")
    return data


def load_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    """Load and validate one YAML file against ``model``.

    Raises:
        ConfigError: Validation failed. The message names the file and every
            offending key with its expected type.

    """
    data = load_yaml(path)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        problems = "\n".join(
            f"  {'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['msg']}"
            for err in exc.errors()
        )
        raise ConfigError(f"{path}: does not match schema {model.__name__}:\n{problems}") from exc


def load_app(config_dir: Path = DEFAULT_CONFIG_DIR) -> AppConfig:
    """Load ``config/app.yaml``."""
    return load_model(config_dir / "app.yaml", AppConfig)


def load_rule_set(rule_set_id: str, config_dir: Path = DEFAULT_CONFIG_DIR) -> RuleSet:
    """Load one Rule Set by id, e.g. ``2026_post_miami`` (F03)."""
    return load_model(config_dir / "rules" / f"{rule_set_id}.yaml", RuleSet)


def load_grid(grid_id: str, config_dir: Path = DEFAULT_CONFIG_DIR) -> GridConfig:
    """Load one grid by id, e.g. ``real_2026`` or ``fictional`` (F19)."""
    return load_model(config_dir / "grid" / f"{grid_id}.yaml", GridConfig)


def load_team_performance(config_dir: Path = DEFAULT_CONFIG_DIR) -> TeamPerformanceConfig:
    """Load ``config/teams/performance.yaml`` (F02)."""
    return load_model(config_dir / "teams" / "performance.yaml", TeamPerformanceConfig)


def load_tyres(config_dir: Path = DEFAULT_CONFIG_DIR) -> TyreConfig:
    """Load ``config/tyres.yaml`` (F02)."""
    return load_model(config_dir / "tyres.yaml", TyreConfig)


def load_track(track_id: str, config_dir: Path = DEFAULT_CONFIG_DIR) -> TrackConfig:
    """Load one track config by id, e.g. ``suzuka`` (F01)."""
    return load_model(config_dir / "tracks" / f"{track_id}.yaml", TrackConfig)


def check_grid_against_teams(grid: GridConfig, teams: TeamPerformanceConfig) -> None:
    """Verify every ``team_id`` on the grid has a performance entry.

    Raises:
        ConfigError: One or more grid teams are missing from
            ``config/teams/performance.yaml``.

    """
    missing = [team_id for team_id in grid.team_ids if team_id not in teams.teams]
    if missing:
        raise ConfigError(
            f"grid {grid.grid_id}: team_ids missing from teams/performance.yaml: "
            f"{', '.join(missing)}"
        )


def resolve_harvest_limit_mj(
    rules: RuleSet,
    track: TrackConfig | None = None,
    user_value_mj: float | None = None,
) -> float:
    """Race harvest limit per lap for one race, in MJ.

    Precedence: the value the user set on Race Setup (S1), then the track's
    optional override, then the Rule Set default. The Overtake extra energy is
    NOT included; it is added on top while Overtake is active.

    Raises:
        ConfigError: The chosen value is not positive, or the Rule Set default
            is still a placeholder and nothing overrides it.

    """
    if user_value_mj is not None:
        if user_value_mj <= 0:
            raise ConfigError(f"harvest limit must be positive, got {user_value_mj} MJ/lap")
        return user_value_mj
    if track is not None and track.harvest_max_mj_per_lap_race is not None:
        return track.harvest_max_mj_per_lap_race
    default = rules.energy.harvest_max_mj_per_lap_race
    if isinstance(default, str):
        raise ConfigError(
            f"rule set {rules.rule_set_id}: energy.harvest_max_mj_per_lap_race is {default}"
        )
    return default


def load_race_config(
    rule_set_id: str,
    grid_id: str,
    track_id: str | None = None,
    config_dir: Path = DEFAULT_CONFIG_DIR,
) -> LoadedConfig:
    """Load every config file needed for one race setup.

    Args:
        rule_set_id: Rule Set id, ``2026_pre_miami`` or ``2026_post_miami``.
        grid_id: Grid id, ``real_2026`` or ``fictional``.
        track_id: Track id to load, or ``None`` to skip the track file.
        config_dir: Root of the config tree.

    Returns:
        A :class:`LoadedConfig` with ``unresolved`` listing every key across all
        loaded files that still holds ``UNRESOLVED`` or ``UNKNOWN`` (HR-09).

    Raises:
        ConfigError: Any file is missing, invalid, or the grid references a
            ``team_id`` with no performance entry.

    """
    app = load_app(config_dir)
    rules = load_rule_set(rule_set_id, config_dir)
    grid = load_grid(grid_id, config_dir)
    teams = load_team_performance(config_dir)
    tyres = load_tyres(config_dir)
    track = load_track(track_id, config_dir) if track_id is not None else None

    check_grid_against_teams(grid, teams)

    sources: list[tuple[BaseModel, str]] = [
        (app, "config/app.yaml"),
        (rules, f"config/rules/{rule_set_id}.yaml"),
        (grid, f"config/grid/{grid_id}.yaml"),
        (teams, "config/teams/performance.yaml"),
        (tyres, "config/tyres.yaml"),
    ]
    if track is not None:
        sources.append((track, f"config/tracks/{track_id}.yaml"))

    unresolved: list[UnresolvedKey] = []
    for model, source in sources:
        unresolved.extend(unresolved_keys(model, source))

    if unresolved:
        logger.warning(
            "%d config keys are still UNRESOLVED or UNKNOWN; see LoadedConfig.unresolved",
            len(unresolved),
        )

    return LoadedConfig(
        app=app,
        rules=rules,
        grid=grid,
        teams=teams,
        tyres=tyres,
        track=track,
        unresolved=unresolved,
    )


def format_unresolved(keys: Iterable[UnresolvedKey]) -> str:
    """Render an unresolved-key list as one line per key, for task reports."""
    lines = [str(key) for key in keys]
    return "\n".join(lines) if lines else "(none)"
