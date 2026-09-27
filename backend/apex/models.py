"""Domain data model.

These types are the contract between the four layers of the system (engine,
analysis, storage, API). The engine is free to be replaced wholesale as long as
it still emits ``TrajectoryPoint``/``VehicleState``/``SafetyEvent`` records and a
``SimulationRun`` summary — nothing downstream of the engine reaches into engine
internals.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


# ==========================================================================
# Enumerations
# ==========================================================================
class SegmentType(str, Enum):
    STRAIGHT = "STRAIGHT"
    BRAKING_ZONE = "BRAKING_ZONE"
    CORNER = "CORNER"
    CORNER_EXIT = "CORNER_EXIT"
    CHICANE = "CHICANE"


class Weather(str, Enum):
    DRY = "DRY"
    DAMP = "DAMP"
    WET = "WET"
    HEAVY_RAIN = "HEAVY_RAIN"


class Severity(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    INCIDENT = "INCIDENT"


class ConflictType(str, Enum):
    REAR_END = "REAR_END"
    SIDE_BY_SIDE = "SIDE_BY_SIDE"
    LANE_CHANGE = "LANE_CHANGE"
    CROSSING = "CROSSING"
    OVERTAKING = "OVERTAKING"
    DEFENSIVE = "DEFENSIVE"
    MULTI_CAR_CHAIN = "MULTI_CAR_CHAIN"


class EventType(str, Enum):
    CONFLICT = "conflict"
    NEAR_MISS = "near_miss"
    COLLISION = "collision"
    LIGHT_CONTACT = "light_contact"
    OFF_TRACK = "off_track"
    SPIN = "spin"
    HARD_BRAKING = "hard_braking"
    EMERGENCY_BRAKING = "emergency_braking"
    EVASIVE_MANOEUVRE = "evasive_manoeuvre"
    OVERTAKE_ATTEMPT = "overtake_attempt"
    OVERTAKE_COMPLETE = "overtake_complete"
    OVERTAKE_ABORTED = "overtake_aborted"
    DEFENSIVE_MOVE = "defensive_move"
    DRIVER_ERROR = "driver_error"


class Decision(str, Enum):
    ACCELERATE = "accelerate"
    BRAKE = "brake"
    COAST = "coast"
    MAINTAIN_LINE = "maintain_line"
    MOVE_LEFT = "move_left"
    MOVE_RIGHT = "move_right"
    INITIATE_OVERTAKE = "initiate_overtake"
    DEFEND_INSIDE = "defend_inside"
    DEFEND_OUTSIDE = "defend_outside"
    YIELD = "yield"
    ABORT_OVERTAKE = "abort_overtake"
    AVOID_COLLISION = "avoid_collision"
    RETURN_TO_LINE = "return_to_racing_line"


DECISION_ORDER = [d.value for d in Decision]


# ==========================================================================
# Track
# ==========================================================================
@dataclass
class TrackSegment:
    index: int
    name: str
    type: SegmentType
    length: float                 # m along the centreline
    width: float                  # m, full track width
    curvature: float              # 1/m, signed (+ left, - right); 0 on a straight
    corner_radius: float | None   # m, None on a straight
    target_speed: float           # m/s, geometric speed ceiling at reference grip
    is_braking_zone: bool
    overtaking_opportunity: float  # 0..1 qualitative rating used by the agent model
    runoff_width: float            # m of runoff beyond the track edge
    barrier_distance: float        # m from track edge to barrier
    s_start: float = 0.0
    s_end: float = 0.0
    turn_number: int | None = None

    @property
    def s_mid(self) -> float:
        return 0.5 * (self.s_start + self.s_end)


@dataclass
class Track:
    id: str
    name: str
    country: str
    length: float
    segments: list[TrackSegment]
    # Centreline polyline in metres, plus per-node heading and arc length.
    centreline_x: list[float] = field(default_factory=list)
    centreline_y: list[float] = field(default_factory=list)
    centreline_s: list[float] = field(default_factory=list)
    centreline_heading: list[float] = field(default_factory=list)
    centreline_width: list[float] = field(default_factory=list)

    def segment_at(self, s: float) -> TrackSegment:
        s = s % self.length
        for seg in self.segments:
            if seg.s_start <= s < seg.s_end:
                return seg
        return self.segments[-1]

    @property
    def corners(self) -> list[TrackSegment]:
        return [s for s in self.segments if s.turn_number is not None
                and s.type == SegmentType.CORNER]


# ==========================================================================
# Drivers
# ==========================================================================
@dataclass
class DriverProfile:
    """A persistent behavioural profile.

    Every field is a *simulation parameter*. None of these values is a measured
    property of any real driver. Where a profile is labelled as inspired by a
    real driver it is a behavioural abstraction over publicly observable racing
    behaviour, not a digital twin.
    """

    id: str
    name: str
    archetype: str
    aggression: float
    risk_tolerance: float
    overtake_willingness: float
    defensive_tendency: float
    reaction_time: float          # s
    braking_consistency: float    # 0..1, higher = less run-to-run variation
    late_braking_tendency: float
    line_change_tendency: float
    error_probability: float      # multiplier on the global error rates
    predictability: float
    pace_multiplier: float
    provenance: str = "generic_archetype"
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ==========================================================================
# Environment / scenario
# ==========================================================================
@dataclass
class Environment:
    weather: Weather
    grip: float
    visibility: float
    spray: float
    track_temp: float
    ambient_temp: float
    wind: float
    tyre_condition: float = 1.0   # 1.0 fresh -> 0.0 fully worn (as modelled)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["weather"] = self.weather.value
        return d


@dataclass
class Scenario:
    """A fully specified, reproducible experiment definition."""

    id: str
    seed: int
    track_id: str
    n_cars: int
    environment: Environment
    driver_ids: list[str]
    # Which archetype occupies each grid slot. Part of the configuration, so two
    # runs with the same field_mix are the same experiment.
    field_mix: list[str] = field(default_factory=list)
    # Per-run perturbations (the Monte Carlo dimensions)
    grid_spread: float = 1.0          # multiplier on the starting gaps
    traffic_density: float = 0.5      # 0..1 derived-but-overridable field density
    pace_spread: float = 1.0          # multiplier on inter-car pace differences
    track_width_multiplier: float = 1.0
    error_rate_multiplier: float = 1.0
    overtake_threshold_delta: float = 0.0   # intervention dial
    following_gap_delta: float = 0.0        # intervention dial
    duration: float = 75.0
    label: str = ""
    parent_id: str | None = None      # set when produced by mutation
    generation: int = 0
    origin: str = "monte_carlo"       # monte_carlo | guided | manual | intervention
    # Apex Passport: optional team car. None (the default) means every car is
    # field-generated exactly as before -- see engine.RaceEngine.__init__ for
    # the equivalence this preserves. When set: {"car_profile": {...CarProfile
    # fields...}, "driver_archetype": "<ARCHETYPE_ID>"}. Grid slot 0 is
    # replaced with a driver of id "TEAM" using that archetype as its
    # starting personality.
    team_car: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["environment"] = self.environment.to_dict()
        return d

    def config_fingerprint(self) -> str:
        """Hash of everything except the seed.

        Two scenarios with the same fingerprint are the same experiment under
        different random draws — which is exactly what lets us count how often a
        configuration reproduces a conflict.
        """
        d = self.to_dict()
        for k in ("id", "seed", "label", "parent_id", "generation", "origin"):
            d.pop(k, None)
        return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


# ==========================================================================
# Simulation output
# ==========================================================================
@dataclass
class VehicleState:
    driver_id: str
    s: float          # arc length along centreline, m
    d: float          # lateral offset from centreline, m (+ left)
    speed: float      # m/s
    acceleration: float
    heading: float    # rad, absolute
    lap: int
    segment_index: int


@dataclass
class TrajectoryPoint:
    t: float
    driver_index: int
    x: float
    y: float
    s: float
    d: float
    speed: float
    acceleration: float
    heading: float
    throttle: float
    braking: float
    segment_index: int
    decision: str
    nearby: list[int] = field(default_factory=list)


@dataclass
class SafetyEvent:
    run_id: str
    t: float
    timestep: int
    event_type: EventType
    severity: Severity
    segment_index: int
    location: str
    driver_a: str
    driver_b: str | None = None
    conflict_type: ConflictType | None = None
    min_ttc: float | None = None
    min_pet: float | None = None
    closing_speed: float | None = None
    max_deceleration: float | None = None
    lateral_rate: float | None = None
    evasive_action: bool = False
    collision: bool = False
    off_track: bool = False
    scsi: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        d["severity"] = self.severity.value
        d["conflict_type"] = self.conflict_type.value if self.conflict_type else None
        return d


@dataclass
class Conflict:
    """A pairwise interaction that crossed the surrogate-safety filter."""

    run_id: str
    driver_a: str
    driver_b: str
    conflict_type: ConflictType
    severity: Severity
    t_min_ttc: float
    timestep: int
    segment_index: int
    location: str
    min_ttc: float
    min_pet: float | None
    closing_speed: float
    max_deceleration: float
    evasive_action: bool
    collision: bool
    scsi: float
    a_decision: str = ""
    b_decision: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["conflict_type"] = self.conflict_type.value
        d["severity"] = self.severity.value
        return d


@dataclass
class SimulationRun:
    id: str
    scenario: Scenario
    batch_id: str | None
    created_at: str
    duration_simulated: float
    n_timesteps: int
    wall_time_ms: float
    # Aggregate outcomes — every one of these is a count within the simulated
    # window under the scenario's assumptions.
    n_conflicts: int
    n_warnings: int
    n_critical: int
    n_near_misses: int
    n_collisions: int
    n_off_track: int
    n_spins: int
    n_evasive: int
    n_overtake_attempts: int
    n_overtakes_completed: int
    n_driver_errors: int
    min_ttc: float | None
    min_pet: float | None
    max_closing_speed: float
    max_deceleration: float
    peak_scsi: float
    config_fingerprint: str
    hotspot_segment: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scenario"] = self.scenario.to_dict()
        return d


@dataclass
class ScenarioPattern:
    """A recurring, canonicalised conflict situation discovered across runs.

    ``occurrences`` is a count of *simulated runs* in which this pattern
    produced a qualifying conflict. It is not, and must not be presented as, a
    real-world frequency or probability.
    """

    id: str
    pattern_key: str
    rank: int
    track_id: str
    segment_index: int
    location: str
    weather: str
    n_cars: int
    traffic_band: str
    archetype_a: str
    archetype_b: str
    conflict_type: str
    dominant_error: str | None
    occurrences: int
    runs_evaluated: int
    median_min_ttc: float
    p05_min_ttc: float
    median_min_pet: float | None
    median_closing_speed: float
    evasive_rate: float
    collision_rate: float
    mean_scsi: float
    example_run_ids: list[str] = field(default_factory=list)
    conditions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Intervention:
    id: str
    name: str
    description: str
    changes: dict[str, Any]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalysisResult:
    id: str
    batch_id: str
    kind: str          # hotspots | sensitivity | interaction_matrix | environment
    payload: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)
