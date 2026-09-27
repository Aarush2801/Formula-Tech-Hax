"""Live simulation streaming.

The Live Simulation screen needs to watch a single run unfold. Rather than
streaming raw 20 Hz state for 22 cars (which would be both heavy and faster than
anything a viewer can read), the run is executed once, in full, and then streamed
back frame by frame at a controllable rate.

That ordering matters for honesty: what the viewer watches is a completed,
deterministic, seed-reproducible run — the same run the analyser scored — not a
separate real-time approximation of it. Pause, scrub and speed controls are
therefore exact, and the events shown on the feed are the events the batch
pipeline would have recorded.
"""

from __future__ import annotations

import numpy as np

from . import assumptions as A
from .circuits import get_track
from .drivers import build_roster, perturb
from .engine import CODE_TO_DECISION, RaceEngine
from .models import Scenario
from .safety import scsi
from .track import TrackGeometry

STREAM_DECIMATE = 2  # stream at 10 Hz


def run_for_streaming(scenario: Scenario) -> dict:
    """Execute a run and package the whole thing for frame-by-frame streaming."""
    track = get_track(scenario.track_id)
    geo = TrackGeometry(track, scenario.track_width_multiplier)
    rng = np.random.default_rng(scenario.seed ^ 0x5EED)
    profiles = perturb(build_roster(scenario.n_cars, scenario.field_mix or None), rng)
    result = RaceEngine(scenario, track, profiles).run()

    idx = np.arange(0, result.n_steps, STREAM_DECIMATE)
    x, y = geo.to_cartesian(result.traj_s[idx], result.traj_d[idx])

    frames = []
    for k, step in enumerate(idx):
        frames.append(dict(
            t=round(float(step * result.dt), 2),
            step=int(step),
            x=[round(float(v), 1) for v in x[k]],
            y=[round(float(v), 1) for v in y[k]],
            speed=[round(float(v), 1) for v in result.traj_v[idx[k]]],
            speed_kph=[round(float(v) * 3.6, 1) for v in result.traj_v[idx[k]]],
            brake=[round(float(v), 2) for v in result.traj_brake[idx[k]]],
            throttle=[round(float(v), 2) for v in result.traj_throttle[idx[k]]],
            accel=[round(float(v), 1) for v in result.traj_a[idx[k]]],
            d=[round(float(v), 2) for v in result.traj_d[idx[k]]],
            s=[round(float(v), 1) for v in result.traj_s[idx[k]]],
            segment=[int(v) for v in result.traj_seg[idx[k]]],
            decision=[CODE_TO_DECISION[int(v)] for v in result.traj_decision[idx[k]]],
        ))

    # Order of the field by distance covered, per frame, for the timing tower.
    order_frames = []
    total = result.traj_s.copy()
    for k, step in enumerate(idx):
        order_frames.append(
            [int(i) for i in np.argsort(-result.traj_s[step] - 0.0)]
        )

    events = []
    for e in result.events:
        ev = dict(e)
        ev["stream_frame"] = int(min(int(e["timestep"] / STREAM_DECIMATE),
                                    len(frames) - 1))
        events.append(ev)

    conflict_events = []
    for c in result.conflicts:
        conflict_events.append(dict(
            t=c["t_min_ttc"],
            stream_frame=int(min(int(c["timestep"] / STREAM_DECIMATE),
                                 len(frames) - 1)),
            event_type="conflict",
            severity=c["severity"],
            conflict_type=c["conflict_type"],
            location=c["location"],
            driver_a=c["driver_a"], driver_b=c["driver_b"],
            driver_a_index=c["driver_a_index"], driver_b_index=c["driver_b_index"],
            min_ttc=c["min_ttc"], min_pet=c["min_pet"],
            closing_speed=c["closing_speed"],
            max_deceleration=c["max_deceleration"],
            evasive_action=c["evasive_action"], collision=c["collision"],
            scsi=c["scsi"], segment_index=c["segment_index"],
        ))

    feed = sorted(events + conflict_events, key=lambda e: e["t"])

    return dict(
        run_id=scenario.id,
        seed=scenario.seed,
        scenario=scenario.to_dict(),
        track_id=scenario.track_id,
        dt=result.dt * STREAM_DECIMATE,
        n_frames=len(frames),
        duration=scenario.duration,
        drivers=[dict(index=i, id=p.id, name=p.name, archetype=p.archetype,
                      aggression=round(p.aggression, 3),
                      risk_tolerance=round(p.risk_tolerance, 3),
                      overtake_willingness=round(p.overtake_willingness, 3),
                      defensive_tendency=round(p.defensive_tendency, 3),
                      reaction_time=round(p.reaction_time, 3),
                      late_braking_tendency=round(p.late_braking_tendency, 3),
                      braking_consistency=round(p.braking_consistency, 3),
                      predictability=round(p.predictability, 3),
                      pace_multiplier=round(p.pace_multiplier, 4))
                 for i, p in enumerate(profiles)],
        frames=frames,
        order_frames=order_frames,
        feed=feed,
        environment=result.environment.to_dict(),
        summary=dict(
            n_conflicts=len(result.conflicts),
            n_critical=sum(1 for c in result.conflicts if c["severity"] == "CRITICAL"),
            n_collisions=result.n_collisions,
            n_light_contacts=result.n_light_contacts,
            n_off_track=result.n_off_track,
            n_spins=result.n_spins,
            n_evasive=result.n_evasive,
            n_overtake_attempts=result.n_overtake_attempts,
            n_overtakes_completed=result.n_overtakes_completed,
            n_driver_errors=int(sum(result.error_counts.values())),
            min_ttc=min((c["min_ttc"] for c in result.conflicts), default=None),
            min_pet=None if result.min_pet >= 1e8 else round(result.min_pet, 4),
            max_closing_speed=round(result.max_closing_speed, 3),
            max_deceleration=round(result.max_deceleration, 3),
            measured_traffic_density=round(result.measured_traffic_density, 4),
            error_counts=result.error_counts,
            dominant_error=result.dominant_error,
            wall_time_ms=round(result.wall_time_ms, 1),
        ),
        conflicts=result.conflicts,
        note=("This is a completed, deterministic run being played back. Re-running "
              "the same seed reproduces it exactly."),
    )
