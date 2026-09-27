"""Replay window extraction.

Storing every trajectory of every run would be gigabytes per batch and almost all
of it would be cars driving uneventfully. Instead, for runs that produced
something worth looking at, we keep a window around the moment of minimum TTC,
for the cars involved plus their immediate neighbours.

The window is what makes the "why did this happen" panel possible: the causal
chain is reconstructed from the trajectory leading into the event, not from a
stored verdict.
"""

from __future__ import annotations

import numpy as np

from . import assumptions as A
from .engine import CODE_TO_DECISION, RunResult
from .track import TrackGeometry

WINDOW_BEFORE = 5.0   # s of lead-in: enough to show the braking phase
WINDOW_AFTER = 3.0    # s of follow-through: enough to show the resolution
DECIMATE = 2          # store at 10 Hz; the engine runs at 20 Hz
NEIGHBOUR_RADIUS = 75.0  # m of track either side of the conflict


def extract_window(
    result: RunResult,
    focus_timestep: int,
    focus_drivers: list[int],
    geo: TrackGeometry | None = None,
) -> dict:
    geo = geo or TrackGeometry(_track_of(result), result.scenario.track_width_multiplier)
    dt = result.dt
    n_steps = result.n_steps
    i0 = max(int(focus_timestep - WINDOW_BEFORE / dt), 0)
    i1 = min(int(focus_timestep + WINDOW_AFTER / dt) + 1, n_steps)
    idx = np.arange(i0, i1, DECIMATE)

    s = result.traj_s[idx]
    d = result.traj_d[idx]

    # Include the cars involved plus anyone nearby at the focus moment: a chain
    # reaction is only legible if the cars that were not directly involved are
    # visible too.
    ref = result.traj_s[focus_timestep]
    anchor = float(np.mean([ref[k] for k in focus_drivers]))
    L = geo.length
    delta = (ref - anchor + L / 2.0) % L - L / 2.0
    include = sorted(set(focus_drivers) | set(np.nonzero(np.abs(delta) <= NEIGHBOUR_RADIUS)[0].tolist()))

    x, y = geo.to_cartesian(s, d)
    cars = []
    for k in include:
        prof = result.profiles[k]
        cars.append(
            dict(
                driver_index=int(k),
                driver_id=prof.id,
                name=prof.name,
                archetype=prof.archetype,
                is_focus=k in focus_drivers,
                x=[round(float(v), 2) for v in x[:, k]],
                y=[round(float(v), 2) for v in y[:, k]],
                s=[round(float(v), 2) for v in s[:, k]],
                d=[round(float(v), 3) for v in d[:, k]],
                speed=[round(float(v), 2) for v in result.traj_v[idx, k]],
                accel=[round(float(v), 2) for v in result.traj_a[idx, k]],
                throttle=[round(float(v), 3) for v in result.traj_throttle[idx, k]],
                brake=[round(float(v), 3) for v in result.traj_brake[idx, k]],
                lateral_rate=[round(float(v), 3) for v in result.traj_lat[idx, k]],
                segment=[int(v) for v in result.traj_seg[idx, k]],
                decision=[CODE_TO_DECISION[int(v)] for v in result.traj_decision[idx, k]],
            )
        )

    # Pairwise TTC trace for the focus pair, so the timeline can show TTC falling.
    ttc_trace = []
    if len(focus_drivers) >= 2:
        a, b = focus_drivers[0], focus_drivers[1]
        from .safety import _overlap_interval
        ds = (result.traj_s[idx, b] - result.traj_s[idx, a] + L / 2) % L - L / 2
        dd = result.traj_d[idx, b] - result.traj_d[idx, a]
        dvs = result.traj_v[idx, b] - result.traj_v[idx, a]
        dvd = result.traj_lat[idx, b] - result.traj_lat[idx, a]
        lo1, hi1 = _overlap_interval(ds, dvs, A.CAR_LENGTH)
        lo2, hi2 = _overlap_interval(dd, dvd, A.CAR_WIDTH)
        lo = np.maximum(lo1, lo2)
        hi = np.minimum(hi1, hi2)
        ttc = np.where((lo <= hi) & (hi >= 0), np.maximum(lo, 0.0), np.nan)
        gap = np.hypot(ds, dd)
        closing = -(ds * dvs + dd * dvd) / np.maximum(gap, 1e-6)
        for k in range(len(idx)):
            ttc_trace.append(
                dict(
                    t=round(float(idx[k] * dt), 3),
                    ttc=None if not np.isfinite(ttc[k]) else round(float(ttc[k]), 4),
                    gap=round(float(gap[k]), 2),
                    closing_speed=round(float(closing[k]), 3),
                    lateral_separation=round(float(dd[k]), 3),
                )
            )

    # Events inside the window, so the replay timeline is annotated.
    t0, t1 = i0 * dt, (i1 - 1) * dt
    window_events = [
        e for e in result.events if t0 <= e["t"] <= t1
        and (e.get("driver_a_index") in include or e.get("driver_b_index") in include)
    ]

    return dict(
        run_id=result.scenario.id,
        track_id=result.track_id,
        dt=dt * DECIMATE,
        t_start=round(t0, 3),
        t_end=round(t1, 3),
        t_focus=round(focus_timestep * dt, 3),
        n_frames=len(idx),
        frame_times=[round(float(v * dt), 3) for v in idx],
        cars=cars,
        ttc_trace=ttc_trace,
        events=window_events,
        environment=result.environment.to_dict(),
        error_log=[
            dict(t=t_, driver_index=i_, kind=k_)
            for (t_, i_, k_) in result.error_log
            if t0 - 3.0 <= t_ <= t1 and i_ in include
        ],
    )


def _track_of(result: RunResult):
    from .circuits import get_track
    return get_track(result.track_id)


def pick_focus(result: RunResult) -> tuple[int, list[int], float] | None:
    """Choose what a run's replay should be centred on.

    Priority: an actual collision, then the lowest TTC. Returns None for runs with
    nothing worth replaying, which is most of them.
    """
    if not result.conflicts:
        return None
    collisions = [c for c in result.conflicts if c["collision"]]
    pool = collisions or result.conflicts
    worst = min(pool, key=lambda c: (c["min_ttc"], -c["scsi"]))
    return (
        int(worst["timestep"]),
        [int(worst["driver_a_index"]), int(worst["driver_b_index"])],
        float(worst["min_ttc"]),
    )
