"""Typed configuration models (pydantic v2), one per YAML schema in TRD CONFIG SCHEMAS.

Covers F03 Rule Sets, F19 Grid Config, F01 track metadata, F02 team and tyre
coefficients, and the application defaults in ``config/app.yaml``.

Values the specification marks ``UNRESOLVED`` (a rule or decision not yet
verified) or ``UNKNOWN`` (a coefficient still to be calibrated) are kept as
those literal strings rather than invented (HR-09). Every field that may carry
one is typed with a placeholder union.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Literal placeholders allowed in config in place of a real value (HR-09).
UNRESOLVED = "UNRESOLVED"
UNKNOWN = "UNKNOWN"

type Placeholder = Literal["UNRESOLVED", "UNKNOWN"]
type MaybeFloat = float | Placeholder
type MaybeInt = int | Placeholder
type MaybeDate = date | Placeholder

type Fraction = Annotated[float, Field(ge=0.0, le=1.0)]
type Positive = Annotated[float, Field(gt=0.0)]
type HexColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]


class Compound(StrEnum):
    """Tyre compounds (TRD Tyres)."""

    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"


class EnergyMode(StrEnum):
    """Energy Mode of a car (PRD GLOSSARY)."""

    PUSH = "PUSH"
    BALANCED = "BALANCED"
    HARVEST = "HARVEST"


class StrictModel(BaseModel):
    """Base model: unknown keys and wrong types are errors, not silent defaults."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------- #
# config/rules/<rule_set>.yaml  (F03)
# --------------------------------------------------------------------------- #


class ZoneCapsKw(StrictModel):
    """MGU-K deployment power cap per zone tag, in kW."""

    acceleration_zone: MaybeFloat
    other: MaybeFloat


class PowerRules(StrictModel):
    """ICE and MGU-K power limits."""

    p_ice_max_kw_nominal: MaybeFloat
    p_k_max_kw: MaybeFloat
    zone_caps_kw: ZoneCapsKw
    boost_net_cap_kw: MaybeFloat | None
    boost_taper_start_kmh: MaybeFloat
    boost_taper_end_kmh: MaybeFloat
    wet_deploy_max_kw: float | None = None
    """Wet-race MGU-K deployment limit (post-Miami); ``null`` = not applied (owner round 16)."""


class OvertakeRules(StrictModel):
    """Overtake mode availability, taper and extra energy."""

    activation_gap_s: MaybeFloat
    taper_start_kmh: MaybeFloat
    taper_end_kmh: MaybeFloat
    extra_energy_mj_per_lap: MaybeFloat


class EnergyRules(StrictModel):
    """Energy store window, per-lap harvest and deploy limits, super-clipping."""

    e_usable_max_mj: MaybeFloat
    harvest_max_mj_per_lap_race: MaybeFloat
    harvest_max_mj_per_lap_quali: MaybeFloat
    deploy_max_mj_per_lap: MaybeFloat | None
    """``None``: no per-lap deploy limit (battery window and harvest limit only)."""
    superclip_power_kw: MaybeFloat
    energy_counter_reset: Literal["formation_lap_start", "race_start", "none"] | Placeholder
    """``none``: no mandatory reset of the per-lap energy counter (pre-Miami)."""


class CarRules(StrictModel):
    """Car construction limits."""

    min_mass_kg: MaybeFloat


class FuelRules(StrictModel):
    """Fuel energy flow limit."""

    max_fuel_energy_flow_mj_per_h: MaybeFloat


class RaceRules(StrictModel):
    """Sporting rules applied during a race."""

    track_limits_warnings_before_penalty: MaybeInt


class RuleSet(StrictModel):
    """A 2026 Rule Set (``config/rules/<rule_set>.yaml``, F03)."""

    rule_set_id: Literal["2026_pre_miami", "2026_post_miami"]
    effective_from: MaybeDate
    power: PowerRules
    overtake: OvertakeRules
    energy: EnergyRules
    car: CarRules
    fuel: FuelRules
    race: RaceRules


# --------------------------------------------------------------------------- #
# config/grid/<grid>.yaml  (F19)
# --------------------------------------------------------------------------- #


class DriverEntry(StrictModel):
    """One driver on the grid. Code references ``driver_id`` only (HR-06)."""

    driver_id: str
    code: str = Field(min_length=2, max_length=4)
    display_name: str
    number: int = Field(ge=0, le=99)
    skill_pace: float
    skill_racecraft: float
    skill_consistency: float


class TeamEntry(StrictModel):
    """One team on the grid, with its drivers."""

    team_id: str
    display_name: str
    pu_maker: str | Placeholder
    color_hex: HexColor | Placeholder
    drivers: list[DriverEntry] = Field(min_length=1)


class GridConfig(StrictModel):
    """A grid file: real 2026 grid or fictional grid (F19)."""

    grid_id: str
    teams: list[TeamEntry] = Field(min_length=1)

    @property
    def driver_ids(self) -> list[str]:
        """Every ``driver_id`` on the grid, in file order."""
        return [d.driver_id for t in self.teams for d in t.drivers]

    @property
    def team_ids(self) -> list[str]:
        """Every ``team_id`` on the grid, in file order."""
        return [t.team_id for t in self.teams]


# --------------------------------------------------------------------------- #
# config/teams/performance.yaml  (F02, FR-SIM-02)
# --------------------------------------------------------------------------- #


class TeamPerformance(StrictModel):
    """Per-team power unit, aero and strategy coefficients."""

    p_ice_max_kw: MaybeFloat
    pu_power_scale: MaybeFloat
    """Per-team ICE power multiplier on ``p_ice_max_kw`` (T-026)."""
    p_k_max_kw: MaybeFloat
    battery_discharge_efficiency: MaybeFloat
    """Battery energy -> MGU-K electrical power (TRD Battery ``eta_discharge``)."""
    brake_harvest_share: MaybeFloat
    """Fraction of braking power the MGU-K recovers (TRD Battery ``harvest_share``)."""
    partial_harvest_max_kw: MaybeFloat
    """Part-throttle harvest power cap (TRD Battery)."""
    ice_efficiency: MaybeFloat
    fuel_energy_density_mj_per_kg: MaybeFloat
    """Lower heating value of the team's fuel (TRD Fuel ``fuel_energy_density``)."""
    driveline_efficiency: MaybeFloat
    cda_straight: MaybeFloat
    cda_corner: MaybeFloat
    cla_straight: MaybeFloat
    cla_corner: MaybeFloat
    long_grip_ratio: MaybeFloat
    """``mu_long = mu_lat * long_grip_ratio`` in the friction ellipse."""
    reliability_dnf_p_per_race: MaybeFloat
    aggression: MaybeFloat
    strategy_style: Literal["AGGRESSIVE", "BALANCED", "CONSERVATIVE"] | Placeholder


class TeamPerformanceConfig(StrictModel):
    """``config/teams/performance.yaml``: one entry per ``team_id``."""

    teams: dict[str, TeamPerformance] = Field(min_length=1)


# --------------------------------------------------------------------------- #
# config/tyres.yaml  (F02)
# --------------------------------------------------------------------------- #


class CompoundCoefficients(StrictModel):
    """Grip, wear and temperature coefficients for one compound (TRD Tyres)."""

    mu_base: MaybeFloat
    k_wear: MaybeFloat
    cliff_w: MaybeFloat
    a_wear: MaybeFloat
    b_wear: MaybeFloat
    heat_gain: MaybeFloat
    cool_rate: MaybeFloat
    t_optimal_c: MaybeFloat
    wet_grip_factor: MaybeFloat
    c_rr: MaybeFloat
    """Rolling resistance coefficient."""


class LoadSensitivity(StrictModel):
    """``mu(N) = mu * (N / n_ref_n)^(-k_load)`` (owner round 14)."""

    n_ref_n: Positive
    k_load: float = Field(ge=0.0, lt=1.0)


class TyreConfig(StrictModel):
    """``config/tyres.yaml``: one entry per :class:`Compound`."""

    wear_norm_j: Positive
    """Tyre work (J) per unit wear at k_wear = abrasiveness = management = 1."""
    load_sensitivity: LoadSensitivity
    compounds: dict[Compound, CompoundCoefficients] = Field(min_length=1)


# --------------------------------------------------------------------------- #
# config/tracks/<track_id>.yaml  (F01)
# --------------------------------------------------------------------------- #


class OutlineSource(StrictModel):
    """A public circuit outline that supplies the curvature at some corners (T-02D)."""

    provider: str
    file: str
    """GeoJSON file, relative to ``paths.tracks``."""
    licence: str
    revision: str
    """Provider's revision (commit) of the file."""
    corners: list[str] = Field(default_factory=list)
    """Corners that take the outline's curvature (``calibration.corner_sources``)."""


class GeometrySource(StrictModel):
    """Which FastF1 session and lap the centre line was built from."""

    year: int
    session: str
    driver: str
    source: Literal["fastf1", "openf1"] | None = None
    """Provider used for the last successful build; written by the track builder."""
    outline: OutlineSource | None = None


class Zone(StrictModel):
    """A tagged stretch of track, in metres along the centre line.

    ``s_end_m < s_start_m`` means the zone crosses the timing line (s = 0).
    """

    zone_id: str
    type: Literal["straight", "braking", "acceleration", "overtaking", "pit_lane"]
    s_start_m: float = Field(ge=0.0)
    s_end_m: float = Field(ge=0.0)
    tags: list[str] = Field(default_factory=list)


class Corner(StrictModel):
    """A named corner at a distance along the centre line."""

    corner_id: str
    s_m: float = Field(ge=0.0)
    name: str
    aliases: list[str] = Field(default_factory=list)
    """Other names the engineer may say on the radio (H2), e.g. "Spoon"."""


class PitConfig(StrictModel):
    """Pit entry, exit, speed limit and time loss."""

    entry_s_m: float = Field(ge=0.0)
    exit_s_m: float = Field(ge=0.0)
    lane_speed_kmh: MaybeFloat
    lane_loss_s: MaybeFloat
    limit_length_m: Positive | None = None
    """Speed-limited part of the lane, centred on the box; ``None`` = entry to exit (T-035)."""


class TrackWeatherConfig(StrictModel):
    """Per-track weather statistics (R2)."""

    rain_p_per_race: MaybeFloat
    transition_matrix: list[list[float]] | Placeholder


class TrackEventsConfig(StrictModel):
    """Per-track incident statistics (R2)."""

    incident_rate_per_lap: MaybeFloat
    sc_share: MaybeFloat


class TrackConfig(StrictModel):
    """``config/tracks/<track_id>.yaml`` (F01)."""

    track_id: str
    fastf1_event: str
    geometry_source: GeometrySource
    official_length_m: MaybeFloat
    """Published lap length; the built centre line must match it (T-010)."""
    race_laps: MaybeInt | None = None
    """Grand Prix race distance in laps (T-033)."""
    sector_ends_m: list[float] = Field(default_factory=list)
    """Ends of timing sectors 1 and 2 (sector 3 ends at the line), metres (T-033)."""
    zones: list[Zone] = Field(default_factory=list)
    detection_points_m: list[float] = Field(default_factory=list)
    corners: list[Corner] = Field(default_factory=list)
    pit: PitConfig
    abrasiveness: MaybeFloat
    zone_difficulty: dict[str, MaybeFloat] = Field(default_factory=dict)
    weather: TrackWeatherConfig
    events: TrackEventsConfig
    evolution_per_lap: MaybeFloat
    harvest_max_mj_per_lap_race: Positive | None = None
    """Optional override of the Rule Set race harvest default for this track."""
    acceleration_zones_source: Literal["fia", "manual", "derived"] | None = None
    derived_acceleration_zones: list[tuple[float, float]] = Field(default_factory=list)
    """T-027 zones (start, end) m; stored, used only when the source is ``derived``."""
    air_temp_c: MaybeFloat | None = None
    air_pressure_hpa: MaybeFloat | None = None
    """Race-day air; both needed for air density, else ``physics.rho_fallback``."""
    fuel_start_kg: MaybeFloat | None = None
    quali_fuel_kg: MaybeFloat | None = None
    """Fuel load of the qualifying reference lap (calibration)."""
    """Where the ``acceleration_zone`` tags come from; FIA-published zones always win."""


# --------------------------------------------------------------------------- #
# config/app.yaml
# --------------------------------------------------------------------------- #


class PathsConfig(StrictModel):
    """Filesystem locations for caches and generated data."""

    fastf1_cache: str
    openf1_cache: str
    multiviewer_cache: str
    tracks: str
    real_races: str
    calibration: str
    runs: str
    cost_cache: str = "data/cost_cache"
    """Decision-cost results by snapshot (hackathon H1); a rehearsal fills it."""


class SimConfig(StrictModel):
    """Time stepping (TRD Time stepping)."""

    dt_s: Positive
    decision_tick_s: Positive
    default_seed: int


class FeedConfig(StrictModel):
    """Public Feed rate, dropout and noise (TRD PUBLIC FEED, F10)."""

    rate_hz: Positive
    drop_p: Fraction
    speed_noise_kmh: float = Field(ge=0.0)
    throttle_noise_pct: float = Field(ge=0.0)
    position_noise_m: float = Field(ge=0.0)
    window_s: Positive
    """How long frames are kept for EngineerView and the Radar (T-050)."""
    gear_upshift_kmh: list[float] = Field(min_length=1)
    """Speeds at which the feed's derived gear goes up (gears are not simulated)."""


class UiConfig(StrictModel):
    """Window identity, refresh rate (NFR-03) and the team-colour fallback."""

    window_title: str
    refresh_hz: Positive
    fallback_palette: list[HexColor] = Field(min_length=1)
    """Used for any team whose ``color_hex`` is missing from the grid file."""
    default_race_laps: int = Field(default=15, ge=1)
    """Race laps the setup screen starts with (hackathon H7)."""


class RadarConfig(StrictModel):
    """Rival Battery Radar constants (F11).

    These are the Radar's own model constants, deliberately NOT the simulator's
    true team values, so the Radar Estimate carries realistic model error
    (TRD RIVAL BATTERY RADAR).
    """

    resample_hz: Positive
    savgol_window: int = Field(gt=0)
    savgol_order: int = Field(ge=0)
    mass_kg: Positive
    p_ice_kw: Positive
    p_elec_max_kw: Positive
    e_max_mj: Positive
    eta: Positive
    """Driveline efficiency in ``P_elec = P_wheel/eta - P_ICE``."""
    rho: Positive
    """Air density, kg/m^3."""
    c_rr: Positive
    min_confidence: Fraction
    """Estimates and alerts below this confidence are shown greyed."""
    confidence_half_life_s: Positive
    full_throttle_pct: Positive
    lift_throttle_pct: Positive
    state_threshold_kw: Positive
    fit_min_speed_kmh: Positive
    fit_max_speed_kmh: Positive
    fit_min_samples: int = Field(gt=0)
    anchor_min_s: Positive
    start_prior_confidence: Fraction = 0.0
    """Confidence of the race-start prior (battery ``start_energy_mj``) before the first anchor."""
    start_energy_mj: float = Field(ge=0.0)
    missing_window_s: Positive


class TrackBuilderConfig(StrictModel):
    """F01 track builder parameters (PF-01)."""

    resample_m: Positive
    length_tolerance: Positive
    """Allowed relative error of the built length vs ``official_length_m``."""
    max_closure_gap_m: Positive
    """Largest gap between the lap's first and last position sample."""
    smoothing_rms_m: Positive
    """Expected RMS position noise; sets the ``splprep`` smoothing tolerance."""
    centre_line_fit: Literal["splprep", "penalized"] = "splprep"
    """Centre-line fit: adaptive-knot ``splprep`` (T-010) or a penalized spline (T-02A)."""
    smoothing_lambda_m3: Positive = 5000.0
    """Roughness penalty of the penalized fit."""
    straight_max_curvature_per_m: Positive
    straight_min_length_m: Positive
    pool_laps: int = Field(ge=1)
    """Fastest clean laps (one per driver) averaged into the centre line (T-029)."""
    pool_bin_m: Positive
    """Bin length along the lap for averaging the pooled samples."""
    normalize_length: bool
    """Scale the built line uniformly so its length equals ``official_length_m``."""
    outline_window_max_m: Positive = 80.0
    """Outline corner window: half-way to the neighbouring corners, at most this each side."""
    outline_blend_m: Positive = 20.0
    """Cosine taper at both ends of an outline corner window."""


class PhysicsConfig(StrictModel):
    """Vehicle-dynamics defaults (TRD Longitudinal dynamics)."""

    rho_fallback: Positive
    v_min_ms: Positive


class AeroConfig(StrictModel):
    """Active aero switching (TRD Active aero)."""

    straight_mode_throttle_min: Fraction


class DirtyAirConfig(StrictModel):
    """Wake of the car ahead (TRD Dirty air and slipstream, F02)."""

    range_m: Positive
    downforce_loss_max: Fraction


class SlipstreamConfig(StrictModel):
    """Drag reduction behind the car ahead (TRD Dirty air and slipstream, F02)."""

    drag_reduction_max: Fraction


class RaceEngineConfig(StrictModel):
    """Race start and timing (T-033, TRD Per-step order)."""

    grid_slot_spacing_m: Positive
    pole_offset_m: Positive
    start_battery_fraction: Fraction
    start_compound: Compound
    timing_loop_spacing_m: Positive
    max_race_factor: Positive


class OvertakeConfig(StrictModel):
    """Overtake model (TRD OVERTAKE MODEL, PF-11, T-034)."""

    trigger_gap_m: Positive
    follow_gap_m: Positive
    w_dv_per_ms: float
    w_grip: float
    w_overtake_mode: float
    w_racecraft: float
    w_defend: float
    w_attack: float = 0.0
    """An ATTACK instruction's pull on the pass logit (sprint day 4)."""
    w_difficulty: float
    zone_difficulty_default: float
    braking_zone_difficulty: float
    braking_trigger_min_drop_kmh: Positive
    fail_time_loss_s: float = Field(ge=0.0)


class PitStopConfig(StrictModel):
    """Pit-stop stationary time and box position (TRD PIT LANE, T-035)."""

    stop_mean_s: Positive
    stop_sd_s: float = Field(ge=0.0)
    stop_min_s: Positive
    slow_stop_p: Fraction
    slow_stop_extra_s: float = Field(ge=0.0)
    box_fraction: Fraction
    entry_decel_ms2: Positive


class RivalStrategyConfig(StrictModel):
    """Rival Strategy AI (F08, T-041; STRUCTURAL defaults)."""

    stop_fraction: dict[Literal["AGGRESSIVE", "BALANCED", "CONSERVATIVE"], Fraction]
    teammate_offset_laps: int = Field(ge=0)
    stop_jitter_laps: int = Field(ge=0)
    window_laps: int = Field(ge=0)
    wear_threshold: Fraction
    critical_wear: Fraction
    no_stop_last_laps: int = Field(ge=0)
    undercut_gap_s: Positive
    battle_gap_s: Positive
    attack_margin_mj: float = Field(ge=0.0)
    defend_margin_mj: float = Field(ge=0.0)
    low_battery_mj: float = Field(ge=0.0)
    recover_battery_mj: float = Field(ge=0.0)
    push_final_laps: int = Field(ge=0)


class AiDriverConfig(StrictModel):
    """AI Driver settings (F04, T-031)."""

    boost_reserve_mj: float = Field(ge=0.0)
    boost_gap_s: Positive
    hold_gap_s: Positive
    grip_margin: Fraction
    push_lap_grip_margin: Fraction
    manage_tyres_grip_margin: Fraction
    push_lap_mgmt_factor: Positive
    manage_tyres_mgmt_factor: Positive
    harvest_target_mj_per_lap: float = Field(ge=0.0)
    balanced_headroom_mj: float = Field(ge=0.0)
    energy_feedback_gain: Fraction
    lift_coast_m: float = Field(ge=0.0)
    lift_coast_min_drop_kmh: float = Field(ge=0.0)
    superclip_zone_m: float = Field(ge=0.0)
    lift_min_speed_share: Fraction = 0.8
    """The plan's lift and coast applies only at or above this share of the reference speed."""


class AccelerationZonesConfig(StrictModel):
    """Acceleration zones derived from the speed profile (T-027)."""

    min_length_m: Positive
    """Shortest corner-exit -> braking-point stretch that becomes a zone."""
    min_speed_change_kmh: Positive
    """A speed minimum / maximum counts only if it differs this much from its neighbours."""
    reference_rule_set: str
    """Rule Set of the reference profile (the one that uses the zones)."""


class AlertsConfig(StrictModel):
    """Pit-wall alerts (sprint A-1, docs/planning/SPRINT.md): provider and rule thresholds."""

    provider: str
    """``simply_clipping_lite`` (built-in) or ``external:<module.path>``."""
    attack_gap_s: Positive
    defend_gap_s: Positive
    energy_margin_mj: Positive
    repass_window_s: Positive
    repass_battery_mj: Positive
    repass_straight_m: Positive
    closing_dv_kmh: Positive
    closing_range_m: Positive
    closing_min_straight_left_m: float = Field(ge=0.0)
    """CLOSING_SPEED_RISK only with this much straight ahead of the slow car."""
    suppress_laps: Positive
    expiry_s: Positive
    min_confidence: Fraction
    """No alert fires below this confidence."""
    low_confidence: Fraction
    """Alerts below this Radar confidence are shown greyed."""
    hold_s: float = Field(ge=0.0)
    """A condition must hold this long before its alert fires."""
    detection_min_share: Fraction = 0.7
    """Observed-clip ATTACK: share of the rival's feed samples on that straight needed."""
    battery_reserve_mj: float = Field(default=0.3, ge=0.0)
    """Own-battery DEFEND: energy kept back from full deployment."""
    clip_min_s: float = Field(default=1.0, ge=0.0)
    """A rival counts as seen clipping only after a CLIP this long on a straight."""


class ExportConfig(StrictModel):
    """Race export for Simply Clipping (sprint S-1, docs/planning/SPRINT.md Part 5)."""

    truth_hz: Positive = 10.0
    """Ground Truth sample rate."""
    stream_rate_hz: tuple[float, float] = (3.7, 4.0)
    """Each raw stream's rate is drawn from this range (FastF1: ~3.7-4 Hz)."""
    jitter_s: float = Field(default=0.03, ge=0.0)
    drop_p: Fraction = 0.05
    """Single dropped frames."""
    gap_rate_per_min: float = Field(default=0.5, ge=0.0)
    """Longer gaps per stream per minute."""
    gap_s: tuple[float, float] = (0.5, 2.0)
    speed_noise_kmh: float = Field(default=0.5, ge=0.0)
    position_noise_m: float = Field(default=1.0, ge=0.0)


class EngineerConfig(StrictModel):
    """Engineer Command validation (F12, T-060; TRD ENGINEER COMMANDS)."""

    let_teammate_by_gap_s: Positive
    """LET_TEAMMATE_BY only with the teammate this close behind."""
    push_lap_max_laps: int = Field(ge=1)
    """PUSH_LAP takes 1..this many laps."""
    call_max_laps: int = Field(default=2, ge=1)
    """ATTACK and DEFEND last at most this many laps (owner, sprint day 5)."""
    defend_clear_gap_s: Positive = 1.0
    """DEFEND ends once the threat is more than this far behind (or has passed)."""


class WeatherConfig(StrictModel):
    """Weather dynamics (F07, T-039); track statistics are in the track config."""

    step_s: Positive
    """Markov step of the condition (TRD: per minute)."""
    rain_intensity: dict[Literal["DRY", "DAMP", "WET", "HEAVY_WET"], Fraction]
    wetting_per_min: float = Field(ge=0.0)
    drying_per_min: float = Field(ge=0.0)
    car_drying_per_min: float = Field(ge=0.0)
    """Extra drying with the whole field on track."""
    evolution_wash_per_min: float = Field(ge=0.0)
    forecast_horizon_s: Positive
    forecast_noise_sd: float = Field(ge=0.0)
    replan_grip_step: Positive
    """Car plans are rebuilt when a car's grip moves by this much."""


MistakeKind = Literal["LOCK_UP", "OFF_TRACK", "SPIN", "CRASH"]


class MistakesConfig(StrictModel):
    """AI Driver mistakes (F04, T-037): per corner passed, from skill, tyre wear, wetness."""

    base_p_per_corner: Fraction
    """Probability per corner of a fully consistent driver on new tyres in the dry."""
    consistency_gain: float = Field(ge=0.0)
    """Factor ``1 + gain x (1 - skill_consistency)``."""
    wear_gain: float = Field(ge=0.0)
    """Factor ``1 + gain x tyre_wear``."""
    wet_gain: float = Field(ge=0.0)
    """Factor ``1 + gain x track_wetness``."""
    kind_shares: dict[MistakeKind, Fraction]
    """Share of each outcome among mistakes (sums to 1)."""
    speed_factor: dict[Literal["LOCK_UP", "OFF_TRACK", "SPIN"], Fraction]
    """Speed kept after the mistake (the time loss follows from the drive)."""
    lock_up_wear: Fraction
    """Tyre wear added by a lock-up (flat spot)."""

    @model_validator(mode="after")
    def _shares_sum_to_one(self) -> MistakesConfig:
        if abs(sum(self.kind_shares.values()) - 1.0) > 1e-9:
            raise ValueError("mistakes.kind_shares must sum to 1")
        return self


class OpenF1Config(StrictModel):
    """OpenF1 REST API access: backup source for track geometry (F01)."""

    base_url: str
    max_requests_per_s: int = Field(gt=0)
    max_requests_per_min: int = Field(gt=0)
    timeout_s: Positive


class MultiViewerConfig(StrictModel):
    """MultiViewer circuit API: corner positions for track configs (T-011)."""

    base_url: str


class PredictorConfig(StrictModel):
    """Strategy Predictor sampling (F13, R2)."""

    n_samples: int = Field(gt=0)
    horizon_laps: int = Field(gt=0)


class DebriefConfig(StrictModel):
    """Debrief scoring parameters (F16, R3)."""

    k_alternatives: int = Field(gt=0)
    n_seeds: int = Field(gt=0)
    score_scale_s: MaybeFloat


class RadioConfig(StrictModel):
    """Two-Way Radio settings (F14, R3). MVP must not load the model."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model_path: str | Placeholder
    model_variant: Literal["gemma-3-270m-it"] | Placeholder
    radio_latency_s: float = Field(ge=0.0)
    parse_timeout_s: Positive
    reply_timeout_s: Positive


class RadioLlmConfig(StrictModel):
    """Hosted LLM on the team radio (hackathon H2 commands, H3 driver replies).

    ``provider`` null = off: the keyword parser and the reply templates only.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    provider: Literal["openai", "anthropic"] | None = None
    """Owner decision (open): which hosted API the radio calls."""
    model: str | None = None
    api_key_env: str | None = None
    """Name of the environment variable holding the key (never the key itself)."""
    base_url: str | None = None
    """Optional endpoint override (an OpenAI-compatible server, a proxy)."""
    timeout_s: Positive = 2.0
    """Owner H2: no answer within this many wall seconds -> keyword parser."""
    driver_replies: bool = True
    """H3: let the LLM write the driver's unprompted lines (fact-checked)."""
    max_reply_words: int = Field(default=20, ge=1)
    """H3: longer replies fall back to the template."""


class VoiceInputConfig(StrictModel):
    """Push-to-talk speech-to-text (hackathon H2, local faster-whisper)."""

    enabled: bool = True
    model: str = "base.en"
    """faster-whisper model name (``tiny.en`` is faster, ``base.en`` more accurate)."""
    model_dir: str = "models/stt"
    """Download / cache directory (gitignored), relative to the repository root."""
    compute_type: str = "int8"
    max_record_s: Positive = 15.0
    """A longer hold is cut here."""
    key: str = "`"
    """Hold this key to talk (the button works too)."""


class CalibrationConfig(StrictModel):
    """Calibration pass thresholds (F20)."""

    speed_rmse_kmh: Positive
    speed_rmse_kmh_provisional: Positive
    """Relaxed RMSE limit for a provisional calibration (owner round 11)."""
    lap_time_tolerance: Positive
    """Allowed relative lap-time error vs the reference (NFR-06)."""
    max_order_error: int = Field(ge=0)
    """Allowed difference between simulated and real team positions."""
    bounds: dict[str, tuple[float, float]]
    """Fit bounds per calibrated coefficient (T-026)."""
    coverage_section_m: Positive
    min_section_coverage: int = Field(ge=1)
    max_lateral_g: Positive
    max_braking_g: Positive
    esses_corners: list[str] = Field(default_factory=list)
    esses_max_excess_kmh: Positive
    """Reference speed traces must have samples in this many sections (owner round 13)."""


class RaceEventsConfig(StrictModel):
    """Safety Car and VSC (hackathon H4, simplified T-038)."""

    vsc_delta_factor: float = Field(default=1.35, gt=1.0)
    sc_pace_factor: float = Field(default=1.40, gt=1.0)
    car_length_m: Positive = 5.5
    sc_gap_m: Positive = 55.0
    sc_catch_up_scale: float = Field(default=0.9, gt=0.0, le=1.0)
    sc_laps: int = Field(default=3, ge=1)
    vsc_duration_s: Positive = 100.0
    crash_on_line_p: Fraction = 0.5
    rival_box_window_laps: int = Field(default=5, ge=0)
    rival_box_min_laps_left: int = Field(default=3, ge=0)


class StrategyPanelConfig(StrictModel):
    """Strategy panel (hackathon H5): background pit-plan forks."""

    workers: int = Field(default=3, ge=1)
    """Worker processes (each ~0.3 GB; the race keeps its own core)."""


class DemoConfig(StrictModel):
    """Demo switches (hackathon)."""

    scripted_sc_lap: int | None = None
    """Force a Safety Car when the leader starts this lap."""


class AppConfig(StrictModel):
    """``config/app.yaml``."""

    paths: PathsConfig
    sim: SimConfig
    feed: FeedConfig
    ui: UiConfig
    radar: RadarConfig
    track_builder: TrackBuilderConfig
    physics: PhysicsConfig
    aero: AeroConfig
    dirty_air: DirtyAirConfig
    slipstream: SlipstreamConfig
    overtake: OvertakeConfig
    pit: PitStopConfig
    rival_strategy: RivalStrategyConfig
    ai_driver: AiDriverConfig
    mistakes: MistakesConfig
    weather: WeatherConfig
    engineer: EngineerConfig
    alerts: AlertsConfig
    race_events: RaceEventsConfig = RaceEventsConfig()
    demo: DemoConfig = DemoConfig()
    strategy_panel: StrategyPanelConfig = StrategyPanelConfig()
    export: ExportConfig = ExportConfig()
    acceleration_zones: AccelerationZonesConfig
    race_engine: RaceEngineConfig
    openf1: OpenF1Config
    multiviewer: MultiViewerConfig
    predictor: PredictorConfig
    debrief: DebriefConfig
    radio: RadioConfig
    radio_llm: RadioLlmConfig = RadioLlmConfig()
    voice_input: VoiceInputConfig = VoiceInputConfig()
    calibration: CalibrationConfig
