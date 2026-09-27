"""Central registry of every tunable number in the simulator.

Provenance discipline
---------------------
Every entry carries a ``kind`` that tells the UI (and the reader) what sort of
claim the number represents:

``methodology``
    Comes from an established surrogate-safety or vehicle-dynamics practice.
    The *concept* is external; the exact value here may still be adapted.
``assumption``
    A modelling choice made by this prototype. Not measured, not validated.
    Changing it changes the results.
``derived``
    Computed from other entries at runtime.

Nothing in this file is a real-world crash statistic, and no entry should ever
be presented as one. The whole point of surfacing this registry in the UI is so
that a reader can see exactly which dials produced a given result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Kind = Literal["methodology", "assumption", "derived"]


@dataclass(frozen=True)
class Assumption:
    key: str
    value: Any
    unit: str
    kind: Kind
    group: str
    label: str
    note: str
    reference: str = ""
    tunable: bool = True
    range: tuple[float, float] | None = None


REGISTRY: dict[str, Assumption] = {}


def declare(
    key: str,
    value: Any,
    *,
    unit: str = "",
    kind: Kind = "assumption",
    group: str = "general",
    label: str = "",
    note: str = "",
    reference: str = "",
    tunable: bool = True,
    range: tuple[float, float] | None = None,
) -> Any:
    a = Assumption(
        key=key,
        value=value,
        unit=unit,
        kind=kind,
        group=group,
        label=label or key.replace("_", " ").title(),
        note=note,
        reference=reference,
        tunable=tunable,
        range=range,
    )
    REGISTRY[key] = a
    return value


# --------------------------------------------------------------------------
# Integration / timing
# --------------------------------------------------------------------------
DT = declare(
    "dt", 0.05, unit="s", kind="assumption", group="Integration",
    label="Simulation timestep",
    note="20 Hz. Fine enough that a 0.7 s TTC event is resolved over ~14 steps, "
         "coarse enough that 10,000 runs are tractable on a laptop.",
    range=(0.01, 0.1),
)
SIM_DURATION = declare(
    "sim_duration", 75.0, unit="s", kind="assumption", group="Integration",
    label="Simulated window per run",
    note="Each run simulates a rolling-start racing window rather than a full "
         "race distance. Conflicts are a per-window count, not a per-race count.",
    range=(20.0, 300.0),
)

# --------------------------------------------------------------------------
# Vehicle model (deliberately simplified single-track point-mass)
# --------------------------------------------------------------------------
CAR_LENGTH = declare(
    "car_length", 5.6, unit="m", kind="assumption", group="Vehicle",
    label="Car length",
    note="Approximate current-generation open-wheel single-seater length. Used "
         "for the longitudinal extent of the collision box.",
)
CAR_WIDTH = declare(
    "car_width", 2.0, unit="m", kind="assumption", group="Vehicle",
    label="Car width",
    note="Used for the lateral extent of the collision box and for the "
         "'is there room for two cars' width check.",
)
CAR_MASS = declare(
    "car_mass", 800.0, unit="kg", kind="assumption", group="Vehicle",
    label="Car mass",
)
ENGINE_POWER = declare(
    "engine_power", 760_000.0, unit="W", kind="assumption", group="Vehicle",
    label="Usable power",
    note="Power-limited acceleration at speed is P/(m*v). Not a manufacturer figure.",
)
TRACTION_ACCEL = declare(
    "traction_accel", 13.0, unit="m/s^2", kind="assumption", group="Vehicle",
    label="Traction-limited acceleration",
    note="Low-speed acceleration ceiling before the power limit takes over.",
)
DRAG_COEFF = declare(
    "drag_coeff", 1.05, unit="-", kind="assumption", group="Vehicle",
    label="Lumped drag coefficient (CdA-like)",
    note="Combined with air density into a single quadratic drag term.",
)
AIR_DENSITY = declare("air_density", 1.2, unit="kg/m^3", kind="assumption", group="Vehicle")
BRAKE_MU = declare(
    "brake_mu", 1.75, unit="-", kind="assumption", group="Vehicle",
    label="Longitudinal braking friction ceiling (dry)",
    note="Effective mu including aerodynamic load. Scaled down by the grip factor "
         "of the active environment.",
    range=(1.0, 2.5),
)
LATERAL_MU = declare(
    "lateral_mu", 1.85, unit="-", kind="assumption", group="Vehicle",
    label="Lateral friction ceiling (dry)",
    note="Sets cornering speed via v = sqrt(mu * g * R). Scaled by grip factor.",
    range=(1.0, 2.5),
)
AERO_REF_SPEED = declare(
    "aero_ref_speed", 80.0, unit="m/s", kind="assumption", group="Vehicle",
    label="Aerodynamic reference speed",
    note="Downforce scales with v^2. Both friction ceilings gain an aero term "
         "k*(v/v_ref)^2 on top of their mechanical value, which is why braking "
         "and cornering capability in this model fall off sharply as speed drops. "
         "Without this term a 2.5 g deceleration would be unreachable and the "
         "hard-braking thresholds below would never fire.",
)
AERO_BRAKE_GAIN = declare(
    "aero_brake_gain", 3.20, unit="-", kind="assumption", group="Vehicle",
    label="Aerodynamic braking gain",
    note="At the reference speed this puts peak deceleration near 5 g, which is "
         "the right order for a current-generation car. Not a measured figure.",
    range=(0.0, 5.0),
)
AERO_LATERAL_GAIN = declare(
    "aero_lateral_gain", 2.40, unit="-", kind="assumption", group="Vehicle",
    label="Aerodynamic cornering gain",
)
MAX_CORNER_SPEED = declare(
    "max_corner_speed", 92.0, unit="m/s", kind="assumption", group="Vehicle",
    label="Cornering speed cap",
    note="The aero-dependent cornering equation has no finite solution for very "
         "large radii, so the result is capped here. Above this radius a corner is "
         "effectively flat out, which is the intended behaviour.",
)
MAX_LATERAL_RATE = declare(
    "max_lateral_rate", 7.0, unit="m/s", kind="assumption", group="Vehicle",
    label="Maximum lateral repositioning rate",
    note="How fast a car can translate across the track at full lateral budget. "
         "Reduced by the friction-ellipse term when braking hard.",
)
LATERAL_JERK_LIMIT = declare(
    "lateral_jerk_limit", 18.0, unit="m/s^2", kind="assumption", group="Vehicle",
    label="Rate limit on lateral velocity change",
    note="Also used as the deceleration available to arrest a lateral move, which "
         "is what stops the line-change controller overshooting its target.",
)
SLIPSTREAM_RANGE = declare(
    "slipstream_range", 45.0, unit="m", kind="assumption", group="Vehicle",
    label="Slipstream range",
    note="Following car within this longitudinal gap and roughly in line gets a "
         "drag reduction, which is what makes closing speeds on straights possible.",
)
SLIPSTREAM_GAIN = declare(
    "slipstream_gain", 0.40, unit="fraction", kind="assumption", group="Vehicle",
    label="Peak drag reduction in slipstream",
)
DIRTY_AIR_GRIP_LOSS = declare(
    "dirty_air_grip_loss", 0.10, unit="fraction", kind="assumption", group="Vehicle",
    label="Peak cornering grip loss in dirty air",
    note="Following closely through a corner costs grip, which is one mechanism "
         "by which traffic density feeds into conflict frequency in this model.",
)

# --------------------------------------------------------------------------
# Surrogate safety thresholds
# --------------------------------------------------------------------------
TTC_CONFLICT_THRESHOLD = declare(
    "ttc_conflict_threshold", 1.5, unit="s", kind="methodology", group="Safety thresholds",
    label="TTC conflict threshold",
    note="SSAM's default maximum time-to-collision for flagging a road-traffic "
         "conflict is 1.5 s. Retained here unchanged so the filter is inherited "
         "rather than invented, even though racing closing speeds differ.",
    reference="FHWA SSAM (FHWA-HRT-08-049 / 08-050)",
    range=(0.5, 3.0),
)
TTC_CRITICAL_THRESHOLD = declare(
    "ttc_critical_threshold", 0.8, unit="s", kind="assumption", group="Safety thresholds",
    label="Critical-conflict TTC threshold",
    note="Below this TTC the interaction is classed CRITICAL rather than WARNING. "
         "This split is a choice made by this prototype, not an SSAM default.",
    range=(0.2, 1.5),
)
PET_CONFLICT_THRESHOLD = declare(
    "pet_conflict_threshold", 5.0, unit="s", kind="methodology", group="Safety thresholds",
    label="PET conflict threshold",
    note="SSAM's default maximum post-encroachment time for a flagged conflict.",
    reference="FHWA SSAM (FHWA-HRT-08-049)",
    range=(1.0, 10.0),
)
PET_CRITICAL_THRESHOLD = declare(
    "pet_critical_threshold", 0.6, unit="s", kind="assumption", group="Safety thresholds",
    label="Critical PET threshold",
    note="Prototype choice for when spatial-temporal proximity counts as critical.",
    range=(0.1, 2.0),
)
CONFLICT_ANGLE_REAR_END = declare(
    "conflict_angle_rear_end", 30.0, unit="deg", kind="methodology", group="Safety thresholds",
    label="Rear-end conflict angle limit",
    note="SSAM types a conflict by the angle between vehicle headings at minimum "
         "TTC: below this it is rear-end.",
    reference="FHWA SSAM (FHWA-HRT-08-049)",
)
CONFLICT_ANGLE_CROSSING = declare(
    "conflict_angle_crossing", 85.0, unit="deg", kind="methodology", group="Safety thresholds",
    label="Crossing conflict angle limit",
    note="Above this angle SSAM types the conflict as crossing; between the two "
         "limits it is a lane-change conflict.",
    reference="FHWA SSAM (FHWA-HRT-08-049)",
)
CONTACT_SEVERE_CLOSING_SPEED = declare(
    "contact_severe_closing_speed", 5.0, unit="m/s", kind="assumption",
    group="Safety thresholds", label="Closing speed separating contact from collision",
    note="Box overlap alone says two cars touched, not how hard. Most overlaps this "
         "model produces are wheel-to-wheel rubs at 2-3 m/s inside a corner, where "
         "the lateral grip budget leaves an agent almost no authority to separate. "
         "Counting those as collisions would badly overstate the outcome, and "
         "suppressing them would hide a real interaction, so they are reported "
         "separately as light contact.",
    range=(1.0, 15.0),
)
CONTACT_SEVERE_OVERLAP = declare(
    "contact_severe_overlap", 0.5, unit="m", kind="assumption",
    group="Safety thresholds", label="Lateral overlap depth counting as a collision",
)
HARD_BRAKING_THRESHOLD = declare(
    "hard_braking_threshold", 25.0, unit="m/s^2", kind="assumption", group="Safety thresholds",
    label="Hard-braking event threshold",
    note="Deceleration above this is logged as a hard-braking event. Set high "
         "because routine braking in this vehicle model already exceeds 1 g.",
    range=(10.0, 45.0),
)
EMERGENCY_BRAKING_THRESHOLD = declare(
    "emergency_braking_threshold", 38.0, unit="m/s^2", kind="assumption", group="Safety thresholds",
    label="Emergency-braking event threshold",
    range=(20.0, 55.0),
)
EVASIVE_LATERAL_THRESHOLD = declare(
    "evasive_lateral_threshold", 3.2, unit="m/s", kind="assumption", group="Safety thresholds",
    label="Evasive lateral-rate threshold",
    note="A lateral repositioning rate above this inside a conflict window is "
         "recorded as an evasive manoeuvre.",
    range=(1.0, 6.0),
)
PET_CELL_LENGTH = declare(
    "pet_cell_length", 8.0, unit="m", kind="methodology", group="Safety thresholds",
    label="PET conflict-cell length",
    note="PET is measured by cell occupancy: the track is diced into cells and PET "
         "is the gap between one car clearing a cell and the next entering it. "
         "Cell size is the spatial resolution of that measurement.",
    reference="Post-encroachment time, as used in FHWA SSAM",
)
PET_CELL_WIDTH = declare(
    "pet_cell_width", 2.4, unit="m", kind="methodology", group="Safety thresholds",
    label="PET conflict-cell width",
)

# --------------------------------------------------------------------------
# Simulation Conflict Severity Index  (explicitly a constructed index)
# --------------------------------------------------------------------------
SCSI_WEIGHTS = declare(
    "scsi_weights",
    {"ttc": 0.40, "pet": 0.20, "closing_speed": 0.25, "deceleration": 0.15},
    unit="-", kind="assumption", group="Conflict Severity Index",
    label="SCSI component weights",
    note="The Simulation Conflict Severity Index is a presentation-layer ranking "
         "aid, NOT a validated severity measure and NOT a crash probability. It is "
         "a weighted sum of four normalised surrogate measures, each clipped to "
         "[0,1]: (1 - TTC/threshold), (1 - PET/threshold), closing speed over its "
         "reference, and peak deceleration over its reference. Raw metrics are "
         "shown alongside it everywhere it appears, and all ranking in the "
         "scenario explorer can be switched to raw minimum TTC.",
)
SCSI_CLOSING_SPEED_REF = declare(
    "scsi_closing_speed_ref", 55.0, unit="m/s", kind="assumption",
    group="Conflict Severity Index", label="Closing-speed normalisation reference",
)
SCSI_DECEL_REF = declare(
    "scsi_decel_ref", 45.0, unit="m/s^2", kind="assumption",
    group="Conflict Severity Index", label="Deceleration normalisation reference",
)

# --------------------------------------------------------------------------
# Human error model — all rates are configurable modelling assumptions
# --------------------------------------------------------------------------
ERROR_RATES = declare(
    "error_rates",
    {
        "missed_braking_point": 0.020,
        "delayed_reaction": 0.010,
        "unexpected_line_change": 0.012,
        "grip_loss": 0.050,
        "concentration_lapse": 0.008,
        "over_aggressive_overtake": 0.030,
        "incorrect_defensive_response": 0.015,
        "spin": 0.00040,
        "slow_response_to_car_ahead": 0.012,
    },
    unit="probability per exposure", kind="assumption", group="Human error",
    label="Error event rates",
    note="Per-exposure probabilities, where an exposure is one decision point "
         "(corner entry for braking errors, one second of racing for the rest). "         "The spin rate in particular is low because it is sampled per agent per "
         "second of cornering: at 0.0035 it produced roughly one spin per 75-second "
         "window across a full field, which is far more than any real session. "
         "These are NOT measured incident rates for any real driver or series. "
         "They are dials: the sensitivity page exists precisely so you can see "
         "how much the conclusions depend on them.",
)
ERROR_EFFECTS = declare(
    "error_effects",
    {
        "missed_braking_point_m": 14.0,
        "delayed_reaction_multiplier": 2.4,
        "delayed_reaction_window_s": 1.5,
        "unexpected_line_change_m": 2.2,
        "grip_loss_factor": 0.80,
        "grip_loss_window_s": 1.2,
        "concentration_lapse_window_s": 0.9,
        "over_aggressive_threshold_delta": -0.30,
        "spin_speed_retention": 0.35,
        "spin_lateral_m": 6.0,
    },
    unit="mixed", kind="assumption", group="Human error",
    label="Error event magnitudes",
    note="What each error actually does to the agent's effective parameters, and "
         "for how long.",
)

# --------------------------------------------------------------------------
# Environment presets
# --------------------------------------------------------------------------
WEATHER_PRESETS = declare(
    "weather_presets",
    {
        "DRY": dict(grip=1.00, visibility=1.00, spray=0.00, track_temp=42.0,
                    ambient_temp=26.0, wind=2.0),
        "DAMP": dict(grip=0.88, visibility=0.92, spray=0.20, track_temp=26.0,
                     ambient_temp=19.0, wind=4.0),
        "WET": dict(grip=0.74, visibility=0.72, spray=0.60, track_temp=19.0,
                    ambient_temp=16.0, wind=6.0),
        "HEAVY_RAIN": dict(grip=0.62, visibility=0.48, spray=0.90, track_temp=15.0,
                           ambient_temp=14.0, wind=9.0),
    },
    unit="mixed", kind="assumption", group="Environment",
    label="Weather presets",
    note="Grip is a multiplier on both friction ceilings. Visibility scales how "
         "far ahead an agent perceives reliably, which lengthens effective "
         "reaction. Spray amplifies the visibility penalty when following closely. "
         "These are plausible orderings, not measured track data.",
)
TYRE_WEAR_GRIP_LOSS = declare(
    "tyre_wear_grip_loss", 0.12, unit="fraction", kind="assumption", group="Environment",
    label="Grip loss at full modelled tyre wear",
)
VISIBILITY_PERCEPTION_SCALE = declare(
    "visibility_perception_scale", 0.55, unit="fraction", kind="assumption",
    group="Environment", label="Perception-range sensitivity to visibility",
    note="At visibility 0 the agent's usable perception range falls to "
         "(1 - this) of nominal.",
)

# --------------------------------------------------------------------------
# Agent decision model
# --------------------------------------------------------------------------
PERCEPTION_RANGE = declare(
    "perception_range", 150.0, unit="m", kind="assumption", group="Agent model",
    label="Nominal perception range",
)
LOOKAHEAD_HORIZON = declare(
    "lookahead_horizon", 224.0, unit="m", kind="assumption", group="Agent model",
    label="Corner-lookahead horizon",
    note="The worst braking event on this circuit (top speed into the slowest "
         "corner in heavy rain) needs about 125 m including the agent's margin, so "
         "this horizon is comfortably sufficient. It was originally 430 m, which "
         "tripled the cost of the dominant array operation in the run loop for no "
         "behavioural benefit.",
)
LOOKAHEAD_STEP = declare(
    "lookahead_step", 8.0, unit="m", kind="assumption", group="Agent model",
    label="Corner-lookahead resolution",
)
BASE_BRAKING_MARGIN = declare(
    "base_braking_margin", 1.14, unit="-", kind="assumption", group="Agent model",
    label="Baseline braking-distance safety margin",
    note="An agent with zero late-braking tendency brakes at this multiple of the "
         "theoretical minimum braking distance. Late-braking tendency erodes the "
         "margin toward 1.0 and beyond.",
    range=(1.0, 1.4),
)
LATE_BRAKING_MARGIN_SPAN = declare(
    "late_braking_margin_span", 0.20, unit="-", kind="assumption", group="Agent model",
    label="Margin erosion at maximum late-braking tendency",
)
CORNER_SPEED_MARGIN = declare(
    "corner_speed_margin", 0.955, unit="fraction", kind="assumption",
    group="Agent model", label="Fraction of the cornering limit agents target",
    note="Agents aim slightly below the geometric limit. This is not a detail: at "
         "exactly the limit the friction ellipse leaves almost no lateral grip, so "
         "two cars side by side through a corner physically cannot separate and "
         "end up rubbing. Holding a small margin returns enough lateral authority "
         "for ordinary racecraft, and it is what a real driver does.",
    range=(0.85, 1.0),
)
OVERTAKE_MIN_SPEED_ADVANTAGE = declare(
    "overtake_min_speed_advantage", 2.8, unit="m/s", kind="assumption", group="Agent model",
    label="Minimum closing speed to consider an overtake",
)
OVERTAKE_COMMIT_RANGE = declare(
    "overtake_commit_range", 32.0, unit="m", kind="assumption", group="Agent model",
    label="Gap at which an overtake can be committed",
)
DEFEND_TRIGGER_RANGE = declare(
    "defend_trigger_range", 40.0, unit="m", kind="assumption", group="Agent model",
    label="Gap at which a defender reacts to a following car",
)
AVOIDANCE_TTC = declare(
    "avoidance_ttc", 1.1, unit="s", kind="assumption", group="Agent model",
    label="TTC at which collision avoidance overrides racing intent",
    note="Below this projected TTC the agent abandons its racing decision and "
         "brakes and/or steers away. This is the modelled last line of defence, "
         "and it is why many critical conflicts in this model end without contact.",
    range=(0.4, 2.0),
)
AVOIDANCE_TTC_LATERAL = declare(
    "avoidance_ttc_lateral", 0.55, unit="s", kind="assumption", group="Agent model",
    label="TTC at which side-by-side conflict triggers avoidance",
    note="Deliberately lower than the rear-end avoidance threshold. Two cars "
         "running alongside sit at a permanently low TTC by construction, since "
         "any lateral convergence at all projects to contact. Using the rear-end "
         "threshold here would leave every side-by-side pair in continuous "
         "avoidance and the field would simply stop racing.",
    range=(0.2, 1.2),
)
AVOIDANCE_LATERAL_LIFT = declare(
    "avoidance_lateral_lift", 0.30, unit="fraction", kind="assumption",
    group="Agent model", label="Braking applied during lateral avoidance",
    note="A lateral conflict is resolved by steering, not by stopping. Only a "
         "partial lift is applied, unlike the full-brake rear-end response.",
)
SIDE_MIN_CLEARANCE = declare(
    "side_min_clearance", 0.55, unit="m", kind="assumption", group="Agent model",
    label="Lateral clearance an agent maintains from a car alongside",
    note="Cars are 2.0 m wide, so centres closer than 2.0 m are in contact. Agents "
         "actively hold this much clearance on top of that whenever a car is "
         "alongside — which is what a driver leaving a car's width is doing. When "
         "the track is too narrow to grant it, the clearance cannot be held and "
         "contact follows. That is the mechanism by which corner width feeds into "
         "contact frequency in this model, rather than any direct rule.",
)
OVERTAKE_PROGRESS_WINDOW = declare(
    "overtake_progress_window", 2.0, unit="s", kind="assumption", group="Agent model",
    label="Commitment extension while a pass is progressing",
    note="An attempt is sustained while the attacker is still gaining and expires "
         "once it stalls, rather than running on a fixed clock. With a fixed clock "
         "almost every attempt expired mid-move regardless of whether it was "
         "working.",
)
OVERTAKE_COOLDOWN = declare(
    "overtake_cooldown", 2.5, unit="s", kind="assumption", group="Agent model",
    label="Cooldown after an overtake resolves",
    note="Without it an agent whose move was aborted re-commits on the very next "
         "timestep, producing attempt/abort churn rather than racing.",
)
OVERTAKE_MIN_ZONE_RATING = declare(
    "overtake_min_zone_rating", 0.30, unit="-", kind="assumption",
    group="Agent model", label="Minimum overtaking rating to commit",
)
OVERTAKE_SIDE_CLEARANCE = declare(
    "overtake_side_clearance", 0.90, unit="m", kind="assumption", group="Agent model",
    label="Lateral clearance sought when going alongside",
)
WARMUP = declare(
    "warmup", 8.0, unit="s", kind="assumption", group="Integration",
    label="Warm-up period excluded from safety accounting",
    note="The grid is an artificial arrangement: the field starts maximally "
         "bunched and its very worst overlaps occur immediately. Those seconds are "
         "simulated but not counted, so conflicts reflect racing rather than the "
         "way the field happened to be placed. At 4 s a visible spike of conflicts "
         "still landed in the first instant after counting opened, and every "
         "replay of a worst-case run centred on it; 8 s removes that artefact. "
         "A gentler decline in conflict rate remains across the window and is "
         "real — a pack that starts together strings out as it races.",
    range=(0.0, 20.0),
)
PACK_START_RANDOM = declare(
    "pack_start_random", True, unit="bool", kind="assumption", group="Integration",
    label="Randomise where the pack starts each run",
    note="Critical for validity. If every run began at the same point, the "
         "hotspots the search discovers would partly encode the author's arbitrary "
         "choice of starting line rather than the circuit's characteristics. The "
         "pack's starting arc length is drawn uniformly around the lap instead.",
)
FOLLOWING_TIME_GAP = declare(
    "following_time_gap", 0.55, unit="s", kind="assumption", group="Agent model",
    label="Target following time gap",
    note="Scaled per agent by risk tolerance. Racing agents follow far closer "
         "than road-traffic car-following models would allow.",
)


def snapshot() -> list[dict]:
    """Serialise the registry for the Model Assumptions screen."""
    out = []
    for a in REGISTRY.values():
        out.append(
            dict(
                key=a.key, value=a.value, unit=a.unit, kind=a.kind, group=a.group,
                label=a.label, note=a.note, reference=a.reference,
                tunable=a.tunable, range=list(a.range) if a.range else None,
            )
        )
    return out


def groups() -> list[str]:
    seen: list[str] = []
    for a in REGISTRY.values():
        if a.group not in seen:
            seen.append(a.group)
    return seen
