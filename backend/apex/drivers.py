"""Driver agents.

An agent has a *persistent* behavioural profile. Across a Monte Carlo batch the
profile does not change: what changes run to run is a small perturbation around
it, scaled by the agent's own consistency and predictability. That is the
distinction the whole study depends on — randomness here represents uncertainty
about how a given personality expresses itself on a given lap, not a personality
that is re-rolled every run.

Every number below is a simulation parameter. None is a measured property of any
real driver.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from .models import DriverProfile

# --------------------------------------------------------------------------
# Archetypes
# --------------------------------------------------------------------------
ARCHETYPES: dict[str, dict] = {
    "AGGRESSIVE_OVERTAKER": dict(
        label="Aggressive Overtaker",
        aggression=0.88, risk_tolerance=0.82, overtake_willingness=0.90,
        defensive_tendency=0.40, reaction_time=0.21, braking_consistency=0.70,
        late_braking_tendency=0.80, line_change_tendency=0.68,
        error_probability=1.35, predictability=0.52, pace_multiplier=1.010,
        note="Commits to passes from long range and brakes deep. High reward, "
             "high exposure to the defender's response.",
    ),
    "DEFENSIVE_SPECIALIST": dict(
        label="Defensive Specialist",
        aggression=0.52, risk_tolerance=0.55, overtake_willingness=0.42,
        defensive_tendency=0.90, reaction_time=0.22, braking_consistency=0.82,
        late_braking_tendency=0.45, line_change_tendency=0.62,
        error_probability=0.95, predictability=0.60, pace_multiplier=0.997,
        note="Moves early to cover the inside line, which removes lateral room "
             "from an attacker already committed.",
    ),
    "CONSERVATIVE": dict(
        label="Conservative Driver",
        aggression=0.30, risk_tolerance=0.32, overtake_willingness=0.35,
        defensive_tendency=0.45, reaction_time=0.25, braking_consistency=0.88,
        late_braking_tendency=0.22, line_change_tendency=0.30,
        error_probability=0.60, predictability=0.86, pace_multiplier=0.988,
        note="Large braking margins and early lifts. Can become an obstacle when "
             "faster traffic arrives.",
    ),
    "LATE_BRAKER": dict(
        label="Late Braker",
        aggression=0.76, risk_tolerance=0.78, overtake_willingness=0.72,
        defensive_tendency=0.48, reaction_time=0.23, braking_consistency=0.62,
        late_braking_tendency=0.94, line_change_tendency=0.45,
        error_probability=1.45, predictability=0.48, pace_multiplier=1.004,
        note="Braking points close to the theoretical limit. Sensitive to any "
             "reduction in grip, because the margin is already spent.",
    ),
    "HIGH_CONSISTENCY": dict(
        label="High Consistency Driver",
        aggression=0.58, risk_tolerance=0.50, overtake_willingness=0.55,
        defensive_tendency=0.58, reaction_time=0.20, braking_consistency=0.95,
        late_braking_tendency=0.52, line_change_tendency=0.38,
        error_probability=0.50, predictability=0.92, pace_multiplier=1.006,
        note="Repeatable braking and line. Low run-to-run variance.",
    ),
    "OPPORTUNISTIC": dict(
        label="Opportunistic Driver",
        aggression=0.70, risk_tolerance=0.68, overtake_willingness=0.80,
        defensive_tendency=0.52, reaction_time=0.20, braking_consistency=0.76,
        late_braking_tendency=0.60, line_change_tendency=0.72,
        error_probability=1.00, predictability=0.44, pace_multiplier=1.002,
        note="Waits for a mistake rather than forcing the move, then changes line "
             "abruptly. Hard for the car ahead to anticipate.",
    ),
    "HIGH_RISK": dict(
        label="High-Risk Driver",
        aggression=0.94, risk_tolerance=0.93, overtake_willingness=0.92,
        defensive_tendency=0.66, reaction_time=0.24, braking_consistency=0.55,
        late_braking_tendency=0.88, line_change_tendency=0.80,
        error_probability=1.90, predictability=0.30, pace_multiplier=1.008,
        note="Minimal margins in every dimension at once.",
    ),
    "SMOOTH": dict(
        label="Smooth Driver",
        aggression=0.46, risk_tolerance=0.44, overtake_willingness=0.50,
        defensive_tendency=0.50, reaction_time=0.19, braking_consistency=0.92,
        late_braking_tendency=0.34, line_change_tendency=0.26,
        error_probability=0.55, predictability=0.90, pace_multiplier=1.000,
        note="Gradual inputs, early and progressive braking.",
    ),
    "UNPREDICTABLE": dict(
        label="Unpredictable Driver",
        aggression=0.68, risk_tolerance=0.72, overtake_willingness=0.66,
        defensive_tendency=0.62, reaction_time=0.27, braking_consistency=0.48,
        late_braking_tendency=0.58, line_change_tendency=0.86,
        error_probability=1.70, predictability=0.18, pace_multiplier=0.995,
        note="Wide run-to-run variation around its own mean. The behaviour the "
             "surrounding agents find hardest to model.",
    ),
}

ARCHETYPE_IDS = list(ARCHETYPES.keys())

# The mix used for a full 22-car field. Chosen to give a realistic spread of
# behaviours rather than a grid of clones.
DEFAULT_FIELD_MIX = [
    "AGGRESSIVE_OVERTAKER", "DEFENSIVE_SPECIALIST", "HIGH_CONSISTENCY", "LATE_BRAKER",
    "SMOOTH", "OPPORTUNISTIC", "CONSERVATIVE", "AGGRESSIVE_OVERTAKER",
    "DEFENSIVE_SPECIALIST", "HIGH_RISK", "HIGH_CONSISTENCY", "OPPORTUNISTIC",
    "LATE_BRAKER", "SMOOTH", "UNPREDICTABLE", "CONSERVATIVE",
    "AGGRESSIVE_OVERTAKER", "DEFENSIVE_SPECIALIST", "OPPORTUNISTIC", "HIGH_RISK",
    "SMOOTH", "UNPREDICTABLE",
]

# Per-field run-to-run perturbation scale at *zero* consistency/predictability.
# Scaled down by the agent's own consistency so a High Consistency agent barely
# moves and an Unpredictable agent moves a lot.
PERTURBATION_SCALE = dict(
    aggression=0.06,
    risk_tolerance=0.06,
    overtake_willingness=0.07,
    defensive_tendency=0.06,
    reaction_time=0.045,
    late_braking_tendency=0.07,
    line_change_tendency=0.07,
    pace_multiplier=0.006,
)


def build_roster(n_cars: int = 22, mix: list[str] | None = None) -> list[DriverProfile]:
    """Build the persistent field. Stable for a given (n_cars, mix)."""
    mix = mix or DEFAULT_FIELD_MIX
    profiles: list[DriverProfile] = []
    for i in range(n_cars):
        arch_id = mix[i % len(mix)]
        a = ARCHETYPES[arch_id]
        profiles.append(
            DriverProfile(
                id=f"DRV_{i + 1:02d}",
                name=f"Driver {i + 1:02d}",
                archetype=arch_id,
                aggression=a["aggression"],
                risk_tolerance=a["risk_tolerance"],
                overtake_willingness=a["overtake_willingness"],
                defensive_tendency=a["defensive_tendency"],
                reaction_time=a["reaction_time"],
                braking_consistency=a["braking_consistency"],
                late_braking_tendency=a["late_braking_tendency"],
                line_change_tendency=a["line_change_tendency"],
                error_probability=a["error_probability"],
                predictability=a["predictability"],
                pace_multiplier=a["pace_multiplier"],
                provenance="generic_archetype",
                note=a["note"],
            )
        )
    return profiles


# Apex Passport: the traits a team may set on its own driver, and the bounds
# they are clamped to. The bounds span the archetype catalogue above with a
# little room either side -- wide enough to describe a real driver, narrow
# enough that the decision model is never driven outside the region it was
# tuned in.
TEAM_DRIVER_TRAITS: dict[str, dict] = {
    "aggression": dict(label="Aggression", min=0.0, max=1.0, step=0.01, unit="",
                       note="How hard the driver presses an advantage."),
    "risk_tolerance": dict(label="Risk tolerance", min=0.0, max=1.0, step=0.01, unit="",
                           note="How small a margin the driver will accept."),
    "overtake_willingness": dict(label="Overtake willingness", min=0.0, max=1.0,
                                 step=0.01, unit="",
                                 note="How readily a pass is attempted."),
    "defensive_tendency": dict(label="Defensive tendency", min=0.0, max=1.0,
                               step=0.01, unit="",
                               note="How early the driver moves to cover a line."),
    "reaction_time": dict(label="Reaction time", min=0.15, max=0.35, step=0.005,
                          unit="s", note="Perception delay before the driver acts."),
    "braking_consistency": dict(label="Braking consistency", min=0.3, max=1.0,
                                step=0.01, unit="",
                                note="Higher means less lap-to-lap variation."),
    "late_braking_tendency": dict(label="Late braking", min=0.0, max=1.0, step=0.01,
                                  unit="", note="How close to the limit braking points sit."),
    "line_change_tendency": dict(label="Line changes", min=0.0, max=1.0, step=0.01,
                                 unit="", note="How often the driver changes line."),
    "error_probability": dict(label="Error rate", min=0.2, max=2.5, step=0.05, unit="×",
                              note="Multiplier on the global human-error rates."),
    "predictability": dict(label="Predictability", min=0.1, max=1.0, step=0.01, unit="",
                           note="Higher means less run-to-run variation in intent."),
    "pace_multiplier": dict(label="Pace", min=0.97, max=1.03, step=0.001, unit="×",
                            note="Multiplier on the car's achievable speed."),
}


def clamp_driver_overrides(overrides: dict | None) -> dict[str, float]:
    """Keeps only known traits, each clamped to its declared bounds."""
    out: dict[str, float] = {}
    for key, value in (overrides or {}).items():
        spec = TEAM_DRIVER_TRAITS.get(key)
        if spec is None or value is None:
            continue
        out[key] = min(spec["max"], max(spec["min"], float(value)))
    return out


def team_driver_traits() -> list[dict]:
    return [dict(key=k, **v) for k, v in TEAM_DRIVER_TRAITS.items()]


def apply_team_driver(
    roster: list[DriverProfile], archetype: str | None = None,
    overrides: dict | None = None,
) -> list[DriverProfile]:
    """Apex Passport: replace grid slot 0 with the team car's driver.

    Only ever called when a scenario explicitly carries a team_car spec, so a
    scenario without one builds exactly the roster it always did. ``overrides``
    replaces individual traits of the chosen archetype (clamped to
    TEAM_DRIVER_TRAITS bounds); without it the driver is the plain archetype.
    """
    archetype = archetype or roster[0].archetype
    a = {**ARCHETYPES[archetype], **clamp_driver_overrides(overrides)}
    team = DriverProfile(
        id="TEAM", name="Team Car", archetype=archetype,
        aggression=a["aggression"], risk_tolerance=a["risk_tolerance"],
        overtake_willingness=a["overtake_willingness"],
        defensive_tendency=a["defensive_tendency"], reaction_time=a["reaction_time"],
        braking_consistency=a["braking_consistency"],
        late_braking_tendency=a["late_braking_tendency"],
        line_change_tendency=a["line_change_tendency"],
        error_probability=a["error_probability"], predictability=a["predictability"],
        pace_multiplier=a["pace_multiplier"],
        provenance="team_custom" if overrides else "generic_archetype",
        note=a["note"],
    )
    return [team] + list(roster[1:])


def perturb(
    profiles: list[DriverProfile], rng: np.random.Generator
) -> list[DriverProfile]:
    """Apply per-run variation around each persistent profile.

    The perturbation magnitude is (1 - braking_consistency) for braking-related
    fields and (1 - predictability) for intent-related fields, so the *identity*
    of the agent survives the draw.
    """
    out: list[DriverProfile] = []
    for p in profiles:
        braking_var = 1.0 - p.braking_consistency
        intent_var = 1.0 - p.predictability
        kw = {}
        for field, scale in PERTURBATION_SCALE.items():
            if field in ("reaction_time", "late_braking_tendency", "pace_multiplier"):
                var = 0.35 + 0.65 * braking_var
            else:
                var = 0.35 + 0.65 * intent_var
            base = getattr(p, field)
            delta = rng.normal(0.0, scale * var)
            val = base + delta
            if field == "reaction_time":
                val = float(np.clip(val, 0.12, 0.45))
            elif field == "pace_multiplier":
                val = float(np.clip(val, 0.96, 1.04))
            else:
                val = float(np.clip(val, 0.02, 0.99))
            kw[field] = val
        out.append(replace(p, **kw))
    return out


def archetype_catalogue() -> list[dict]:
    out = []
    for aid, a in ARCHETYPES.items():
        d = {k: v for k, v in a.items()}
        d["id"] = aid
        d["perturbation_scale"] = PERTURBATION_SCALE
        out.append(d)
    return out


def as_arrays(profiles: list[DriverProfile]) -> dict[str, np.ndarray]:
    """Pack a roster into the parameter arrays the vectorised engine consumes."""
    keys = (
        "aggression", "risk_tolerance", "overtake_willingness", "defensive_tendency",
        "reaction_time", "braking_consistency", "late_braking_tendency",
        "line_change_tendency", "error_probability", "predictability",
        "pace_multiplier",
    )
    return {k: np.array([getattr(p, k) for p in profiles], dtype=float) for k in keys}
