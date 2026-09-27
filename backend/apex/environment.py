"""Environment model.

Weather is resolved into a small set of scalars the engine actually consumes:
grip (a multiplier on both friction ceilings), visibility (which shortens usable
perception range and therefore lengthens effective reaction distance), and spray
(which amplifies the visibility penalty specifically when following closely).

The physics is deliberately shallow. The goal is a believable ordering of
interaction dynamics across conditions, not a tyre model.
"""

from __future__ import annotations

import numpy as np

from . import assumptions as A
from .models import Environment, Weather

WEATHERS = [Weather.DRY, Weather.DAMP, Weather.WET, Weather.HEAVY_RAIN]


def make_environment(
    weather: Weather | str,
    *,
    grip_delta: float = 0.0,
    visibility_delta: float = 0.0,
    tyre_condition: float = 1.0,
    rng: np.random.Generator | None = None,
    jitter: bool = True,
) -> Environment:
    w = Weather(weather) if isinstance(weather, str) else weather
    p = A.WEATHER_PRESETS[w.value]

    grip = p["grip"] + grip_delta
    vis = p["visibility"] + visibility_delta
    spray = p["spray"]
    track_temp = p["track_temp"]
    ambient = p["ambient_temp"]
    wind = p["wind"]

    if jitter and rng is not None:
        # Within-condition variation: two "wet" sessions are not identical.
        grip += rng.normal(0.0, 0.020)
        vis += rng.normal(0.0, 0.030)
        spray = float(np.clip(spray + rng.normal(0.0, 0.05), 0.0, 1.0))
        track_temp += rng.normal(0.0, 2.5)
        ambient += rng.normal(0.0, 1.5)
        wind = float(max(0.0, wind + rng.normal(0.0, 1.5)))

    # Modelled tyre wear removes grip on top of the weather term.
    grip *= 1.0 - A.TYRE_WEAR_GRIP_LOSS * (1.0 - tyre_condition)

    return Environment(
        weather=w,
        grip=float(np.clip(grip, 0.35, 1.10)),
        visibility=float(np.clip(vis, 0.15, 1.05)),
        spray=spray,
        track_temp=float(track_temp),
        ambient_temp=float(ambient),
        wind=float(wind),
        tyre_condition=float(np.clip(tyre_condition, 0.0, 1.0)),
    )


def perception_range(env: Environment) -> float:
    """Usable perception range in metres, degraded by visibility."""
    factor = 1.0 - A.VISIBILITY_PERCEPTION_SCALE * (1.0 - env.visibility)
    return A.PERCEPTION_RANGE * max(factor, 0.1)


def spray_penalty(env: Environment, gap: np.ndarray) -> np.ndarray:
    """Extra perception degradation from running in another car's spray.

    Falls off linearly to zero at 60 m. Returns a multiplier in (0, 1].
    """
    close = np.clip(1.0 - gap / 60.0, 0.0, 1.0)
    return 1.0 - 0.45 * env.spray * close


def environment_summary(env: Environment) -> dict:
    d = env.to_dict()
    d["perception_range"] = round(perception_range(env), 1)
    d["braking_distance_100_0"] = round(
        (100 / 3.6) ** 2 / (2 * A.BRAKE_MU * env.grip * 9.81), 1
    )
    return d
