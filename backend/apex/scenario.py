"""Scenario generation.

A scenario is a complete, reproducible experiment definition. The generator's job
is to sample the *space* of scenarios, not to simulate any of them.

Two sampling modes are provided:

``sample`` — random Monte Carlo over the whole space, optionally with dimensions
pinned. This is the baseline search.

``mutate`` — a local perturbation of an existing scenario, used by the guided
search in ``discovery.py`` to explore around a region of the space that has
already produced interesting conflicts.

An important discipline: driver *personalities* are not part of what gets
randomised here. What varies is which archetypes are present, where they start,
and the conditions they race in. The archetypes themselves are fixed, because a
finding of the form "aggressive overtaker against defensive specialist recurs at
Turn 7" is only meaningful if those two labels mean the same thing in every run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from . import assumptions as A
from .drivers import ARCHETYPE_IDS, DEFAULT_FIELD_MIX, build_roster
from .environment import make_environment
from .models import Environment, Scenario, Weather

WEATHER_IDS = ["DRY", "DAMP", "WET", "HEAVY_RAIN"]


@dataclass
class ScenarioSpace:
    """The searchable space. Every field is either a set of choices or a range."""

    track_ids: list[str] = field(default_factory=lambda: ["vale_park"])
    weathers: list[str] = field(default_factory=lambda: list(WEATHER_IDS))
    weather_weights: list[float] | None = None
    n_cars_choices: list[int] = field(default_factory=lambda: [8, 12, 16, 20, 22])
    traffic_density: tuple[float, float] = (0.15, 0.95)
    grid_spread: tuple[float, float] = (0.7, 1.4)
    pace_spread: tuple[float, float] = (0.4, 2.0)
    track_width_multiplier: tuple[float, float] = (0.85, 1.15)
    error_rate_multiplier: tuple[float, float] = (0.4, 1.8)
    grip_delta: tuple[float, float] = (-0.06, 0.04)
    visibility_delta: tuple[float, float] = (-0.08, 0.05)
    tyre_condition: tuple[float, float] = (0.45, 1.0)
    duration: float = A.SIM_DURATION
    # Archetype composition. Sampling a Dirichlet over these lets a run be
    # dominated by one behaviour or be a broad mix, which is what makes the
    # driver-interaction matrix fill in.
    archetypes: list[str] = field(default_factory=lambda: list(ARCHETYPE_IDS))
    archetype_concentration: float = 0.9
    # Intervention dials. Zero in baseline search; set explicitly by the what-if lab.
    overtake_threshold_delta: tuple[float, float] = (0.0, 0.0)
    following_gap_delta: tuple[float, float] = (0.0, 0.0)

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


def _u(rng: np.random.Generator, rng_range: tuple[float, float]) -> float:
    lo, hi = rng_range
    if hi <= lo:
        return float(lo)
    return float(rng.uniform(lo, hi))


def sample_field_mix(
    rng: np.random.Generator, n_cars: int, space: ScenarioSpace
) -> list[str]:
    """Draw the archetype composition of the field.

    A Dirichlet draw over the archetype weights, then a multinomial assignment of
    grid slots. Low concentration gives lopsided fields (almost everyone
    aggressive), high concentration gives even mixes. Both are worth searching.
    """
    k = len(space.archetypes)
    weights = rng.dirichlet(np.full(k, space.archetype_concentration))
    counts = rng.multinomial(n_cars, weights)
    mix: list[str] = []
    for arch, c in zip(space.archetypes, counts):
        mix.extend([arch] * int(c))
    while len(mix) < n_cars:
        mix.append(space.archetypes[int(rng.integers(k))])
    mix = mix[:n_cars]
    # Shuffle so composition and grid order are independent dimensions.
    order = rng.permutation(len(mix))
    return [mix[i] for i in order]


def sample(
    seed: int,
    space: ScenarioSpace | None = None,
    *,
    pin: dict[str, Any] | None = None,
    label: str = "",
    origin: str = "monte_carlo",
    batch_rng: np.random.Generator | None = None,
) -> Scenario:
    """Draw one scenario.

    ``seed`` is both the scenario's identity for reproduction *and* the seed the
    engine will use. ``pin`` fixes named dimensions, which is how the experiment
    suite holds everything constant but one variable.
    """
    space = space or ScenarioSpace()
    pin = pin or {}
    rng = np.random.default_rng(seed)

    def pinned(name, fallback):
        return pin[name] if name in pin else fallback

    track_id = pinned("track_id", space.track_ids[int(rng.integers(len(space.track_ids)))])
    if "weather" in pin:
        weather = pin["weather"]
    else:
        w = space.weather_weights
        p = np.array(w, dtype=float) / np.sum(w) if w else None
        weather = str(rng.choice(space.weathers, p=p))
    n_cars = int(pinned(
        "n_cars",
        space.n_cars_choices[int(rng.integers(len(space.n_cars_choices)))],
    ))

    env = make_environment(
        Weather(weather),
        grip_delta=float(pinned("grip_delta", _u(rng, space.grip_delta))),
        visibility_delta=float(pinned("visibility_delta",
                                      _u(rng, space.visibility_delta))),
        tyre_condition=float(pinned("tyre_condition", _u(rng, space.tyre_condition))),
        rng=rng,
        jitter=True,
    )

    mix = pinned("field_mix", sample_field_mix(rng, n_cars, space))
    roster = build_roster(n_cars, mix)

    return Scenario(
        id=uuid.uuid4().hex[:16],
        seed=int(seed),
        track_id=track_id,
        n_cars=n_cars,
        environment=env,
        driver_ids=[p.id for p in roster],
        field_mix=list(mix),
        grid_spread=float(pinned("grid_spread", _u(rng, space.grid_spread))),
        traffic_density=float(pinned("traffic_density", _u(rng, space.traffic_density))),
        pace_spread=float(pinned("pace_spread", _u(rng, space.pace_spread))),
        track_width_multiplier=float(pinned(
            "track_width_multiplier", _u(rng, space.track_width_multiplier))),
        error_rate_multiplier=float(pinned(
            "error_rate_multiplier", _u(rng, space.error_rate_multiplier))),
        overtake_threshold_delta=float(pinned(
            "overtake_threshold_delta", _u(rng, space.overtake_threshold_delta))),
        following_gap_delta=float(pinned(
            "following_gap_delta", _u(rng, space.following_gap_delta))),
        duration=float(pinned("duration", space.duration)),
        label=label,
        origin=origin,
    )


# --------------------------------------------------------------------------
# Mutation, for the guided search
# --------------------------------------------------------------------------
MUTABLE_CONTINUOUS = {
    "traffic_density": (0.10, 0.98, 0.12),
    "grid_spread": (0.6, 1.5, 0.15),
    "pace_spread": (0.3, 2.2, 0.25),
    "track_width_multiplier": (0.8, 1.2, 0.05),
    "error_rate_multiplier": (0.3, 2.5, 0.3),
}


def mutate(
    parent: Scenario,
    seed: int,
    rng: np.random.Generator,
    space: ScenarioSpace | None = None,
    *,
    strength: float = 1.0,
    resample_seed: bool = True,
) -> Scenario:
    """Perturb a scenario to explore near it.

    Roughly two or three dimensions move at a time. The seed is redrawn by
    default, so a mutated scenario is genuinely a different run and not just the
    same run relabelled — otherwise the search would happily converge onto one
    lucky random draw and report it as a recurring pattern.
    """
    space = space or ScenarioSpace()
    child = replace(
        parent,
        id=uuid.uuid4().hex[:16],
        seed=int(seed) if resample_seed else parent.seed,
        parent_id=parent.id,
        generation=parent.generation + 1,
        origin="guided",
        label="",
    )

    choices = list(MUTABLE_CONTINUOUS.items())
    n_moves = int(rng.integers(2, 4))
    picked = rng.permutation(len(choices))[:n_moves]
    for idx in picked:
        name, (lo, hi, sigma) = choices[idx]
        cur = getattr(child, name)
        val = float(np.clip(cur + rng.normal(0.0, sigma * strength), lo, hi))
        setattr(child, name, val)

    # Discrete moves, each with its own probability.
    if rng.random() < 0.30 * strength:
        cur_i = WEATHER_IDS.index(child.environment.weather.value)
        step = int(rng.choice([-1, 1]))
        new_w = WEATHER_IDS[int(np.clip(cur_i + step, 0, len(WEATHER_IDS) - 1))]
        child.environment = make_environment(
            Weather(new_w), tyre_condition=child.environment.tyre_condition,
            rng=rng, jitter=True,
        )
    if rng.random() < 0.25 * strength:
        opts = [c for c in space.n_cars_choices]
        cur_i = int(np.argmin([abs(c - child.n_cars) for c in opts]))
        cur_i = int(np.clip(cur_i + int(rng.choice([-1, 1])), 0, len(opts) - 1))
        child.n_cars = opts[cur_i]
        child.field_mix = sample_field_mix(rng, child.n_cars, space)
        child.driver_ids = [p.id for p in build_roster(child.n_cars, child.field_mix)]
    if rng.random() < 0.35 * strength:
        # Nudge the archetype composition: swap a few grid slots.
        mix = list(child.field_mix)
        for _ in range(max(1, child.n_cars // 6)):
            i = int(rng.integers(len(mix)))
            mix[i] = space.archetypes[int(rng.integers(len(space.archetypes)))]
        child.field_mix = mix
        child.driver_ids = [p.id for p in build_roster(child.n_cars, mix)]
    if rng.random() < 0.20 * strength:
        child.environment = make_environment(
            child.environment.weather,
            tyre_condition=float(np.clip(
                child.environment.tyre_condition + rng.normal(0, 0.18), 0.3, 1.0)),
            rng=rng, jitter=True,
        )
    return child


def with_intervention(
    base: Scenario, changes: dict[str, Any], *, label: str = ""
) -> Scenario:
    """Duplicate a scenario with named parameters changed, keeping the seed.

    Keeping the seed is the whole point of the what-if lab: the baseline and the
    intervention see the same random draws, so any difference in outcome is
    attributable to the change rather than to a different roll of the dice.
    """
    child = replace(
        base,
        id=uuid.uuid4().hex[:16],
        parent_id=base.id,
        origin="intervention",
        label=label or "intervention",
    )
    env_keys = {"weather", "grip", "visibility", "spray", "tyre_condition"}
    env_changes = {k: v for k, v in changes.items() if k in env_keys}
    for k, v in changes.items():
        if k in env_keys:
            continue
        if not hasattr(child, k):
            raise KeyError(f"unknown scenario parameter '{k}'")
        setattr(child, k, v)
    if env_changes:
        if "weather" in env_changes:
            child.environment = make_environment(
                Weather(env_changes["weather"]),
                tyre_condition=env_changes.get(
                    "tyre_condition", base.environment.tyre_condition),
                jitter=False,
            )
        for k, v in env_changes.items():
            if k != "weather":
                setattr(child.environment, k, v)
    if "n_cars" in changes:
        mix = base.field_mix[:child.n_cars] if base.field_mix else DEFAULT_FIELD_MIX
        while len(mix) < child.n_cars:
            mix = list(mix) + list(mix)
        child.field_mix = list(mix)[:child.n_cars]
        child.driver_ids = [
            p.id for p in build_roster(child.n_cars, child.field_mix)
        ]
    return child


def scenario_from_dict(d: dict) -> Scenario:
    """Rebuild a Scenario from its serialised form.

    Used to re-run a stored run exactly. Because the engine is deterministic in
    the scenario's seed, re-running reproduces the original trajectories
    bit-for-bit, which is what lets replay windows be generated in a second pass
    instead of being carried through the batch.
    """
    env_d = dict(d["environment"])
    env = Environment(
        weather=Weather(env_d["weather"]),
        grip=env_d["grip"], visibility=env_d["visibility"], spray=env_d["spray"],
        track_temp=env_d["track_temp"], ambient_temp=env_d["ambient_temp"],
        wind=env_d["wind"], tyre_condition=env_d.get("tyre_condition", 1.0),
    )
    fields = {
        k: v for k, v in d.items() if k not in ("environment",)
    }
    return Scenario(environment=env, **fields)
