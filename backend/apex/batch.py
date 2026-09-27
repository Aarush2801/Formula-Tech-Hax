"""Batch execution.

One process per core, each running whole simulations independently. This is
embarrassingly parallel: runs share nothing, so there is no coordination beyond
handing out seeds and collecting compact result dictionaries.

What crosses the process boundary matters. Workers return summaries, conflict
records, filtered events and (only for interesting runs) one compressed replay
window — never trajectory arrays. Returning the arrays would make pickling, not
simulation, the bottleneck.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import time
import uuid
from dataclasses import asdict
from typing import Any, Callable, Iterator

import numpy as np

from . import assumptions as A
from .circuits import get_track
from .drivers import build_roster, perturb
from .engine import RaceEngine
from .models import Scenario
from .replay import extract_window, pick_focus
from .safety import scsi
from .scenario import ScenarioSpace, sample
from .storage import utcnow

# Events worth keeping in the database for every run. The rest (routine defensive
# moves, every overtake probe) are summarised as counts instead: at 10,000 runs
# they would be millions of rows that nothing queries.
KEEP_EVENT_TYPES = {
    "collision", "light_contact", "off_track", "spin", "emergency_braking",
    "evasive_manoeuvre", "overtake_aborted",
}
MAX_EVENTS_PER_RUN = 40


def build_run(scenario: Scenario) -> tuple[Any, list]:
    """Materialise and execute one scenario. Returns (RunResult, profiles)."""
    # Always the unscaled circuit: TrackGeometry applies the width multiplier.
    # Passing the multiplier here would miss the cache on every run (the value is
    # continuous), rebuilding the closure solve each time and growing the cache
    # without bound in a long-lived worker.
    track = get_track(scenario.track_id)
    rng = np.random.default_rng(scenario.seed ^ 0x5EED)
    base = build_roster(scenario.n_cars, scenario.field_mix or None)
    profiles = perturb(base, rng)
    result = RaceEngine(scenario, track, profiles).run()
    return result, profiles


def summarise(result, scenario: Scenario, batch_id: str | None,
              want_replay: bool) -> dict:
    """Flatten a RunResult into the row/record shapes the store expects."""
    conflicts = result.conflicts
    n_critical = sum(1 for c in conflicts if c["severity"] == "CRITICAL")
    n_warning = sum(1 for c in conflicts if c["severity"] == "WARNING")
    n_incident = sum(1 for c in conflicts if c["severity"] == "INCIDENT")
    # A near miss, as used throughout this project: a conflict that crossed the
    # surrogate-safety filter, involved an evasive manoeuvre, and did NOT end in
    # contact. It is a count of simulated interactions, not of real-world events.
    n_near_miss = sum(
        1 for c in conflicts if c["evasive_action"] and not c["collision"]
    )
    min_ttc = min((c["min_ttc"] for c in conflicts), default=None)
    peak = max((c["scsi"] for c in conflicts), default=0.0)
    hotspot = None
    if result.segment_conflict_counts:
        hotspot = max(result.segment_conflict_counts.items(), key=lambda kv: kv[1])[0]

    env = result.environment
    run_row = dict(
        id=scenario.id,
        batch_id=batch_id,
        created_at=utcnow(),
        seed=scenario.seed,
        track_id=scenario.track_id,
        n_cars=scenario.n_cars,
        weather=env.weather.value,
        grip=round(env.grip, 5),
        visibility=round(env.visibility, 5),
        spray=round(env.spray, 5),
        tyre_condition=round(env.tyre_condition, 5),
        track_temp=round(env.track_temp, 2),
        ambient_temp=round(env.ambient_temp, 2),
        wind=round(env.wind, 2),
        traffic_density_requested=round(scenario.traffic_density, 5),
        traffic_density_measured=round(result.measured_traffic_density, 5),
        grid_spread=round(scenario.grid_spread, 5),
        pace_spread=round(scenario.pace_spread, 5),
        track_width_multiplier=round(scenario.track_width_multiplier, 5),
        error_rate_multiplier=round(scenario.error_rate_multiplier, 5),
        overtake_threshold_delta=round(scenario.overtake_threshold_delta, 5),
        following_gap_delta=round(scenario.following_gap_delta, 5),
        duration=scenario.duration,
        n_timesteps=result.n_steps,
        wall_time_ms=round(result.wall_time_ms, 2),
        origin=scenario.origin,
        generation=scenario.generation,
        parent_scenario_id=scenario.parent_id,
        config_fingerprint=scenario.config_fingerprint(),
        n_conflicts=len(conflicts),
        n_warnings=n_warning,
        n_critical=n_critical,
        n_near_misses=n_near_miss,
        n_collisions=result.n_collisions,
        n_light_contacts=result.n_light_contacts,
        n_off_track=result.n_off_track,
        n_spins=result.n_spins,
        n_barrier_strikes=result.n_barrier_strikes,
        n_evasive=result.n_evasive,
        n_overtake_attempts=result.n_overtake_attempts,
        n_overtakes_completed=result.n_overtakes_completed,
        n_driver_errors=int(sum(result.error_counts.values())),
        min_ttc=min_ttc,
        min_pet=None if result.min_pet >= 1e8 else round(result.min_pet, 5),
        max_closing_speed=round(result.max_closing_speed, 4),
        max_deceleration=round(result.max_deceleration, 4),
        peak_scsi=round(peak, 5),
        hotspot_segment=hotspot,
        dominant_error=result.dominant_error,
        laps_completed=round(result.laps_completed, 4),
        field_mix_json=_json(scenario.field_mix),
        error_counts_json=_json(result.error_counts),
        scenario_json=_json(scenario.to_dict()),
        has_replay=0,
    )

    conflict_rows = []
    for c in conflicts:
        row = dict(c)
        row.update(
            run_id=scenario.id, batch_id=batch_id, weather=env.weather.value,
            traffic_density=round(result.measured_traffic_density, 5),
            n_cars=scenario.n_cars,
            evasive_action=int(c["evasive_action"]), collision=int(c["collision"]),
        )
        row.pop("samples", None)
        conflict_rows.append(row)

    kept = [e for e in result.events if e["event_type"] in KEEP_EVENT_TYPES]
    sev_rank = {"INCIDENT": 0, "CRITICAL": 1, "WARNING": 2, "NORMAL": 3}
    kept.sort(key=lambda e: (sev_rank.get(e["severity"], 9), e["t"]))
    kept = kept[:MAX_EVENTS_PER_RUN]
    event_rows = []
    for e in kept:
        event_rows.append(dict(
            run_id=scenario.id, batch_id=batch_id, t=e["t"], timestep=e["timestep"],
            event_type=e["event_type"], severity=e["severity"],
            segment_index=e["segment_index"], location=e["location"],
            driver_a=e["driver_a"], driver_b=e.get("driver_b"),
            driver_a_index=e.get("driver_a_index"),
            driver_b_index=e.get("driver_b_index"),
            min_ttc=e.get("min_ttc"), min_pet=e.get("min_pet"),
            closing_speed=e.get("closing_speed"),
            max_deceleration=e.get("max_deceleration"),
            lateral_rate=e.get("lateral_rate"),
            evasive_action=int(bool(e.get("evasive_action"))),
            collision=int(bool(e.get("collision"))),
            off_track=int(bool(e.get("off_track"))),
            detail_json=_json(e.get("detail", {})),
        ))

    return dict(run=run_row, conflicts=conflict_rows, events=event_rows,
                event_type_counts=_count_types(result.events),
                segment_conflicts=result.segment_conflict_counts,
                all_events_n=len(result.events))


def _count_types(events: list[dict]) -> dict:
    out: dict[str, int] = {}
    for e in events:
        out[e["event_type"]] = out.get(e["event_type"], 0) + 1
    return out


def _json(obj) -> str:
    import json
    return json.dumps(obj)


# --------------------------------------------------------------------------
# Worker entry points (must be module level to be picklable)
# --------------------------------------------------------------------------
_REPLAY_TTC_GATE = A.TTC_CRITICAL_THRESHOLD


def _worker_sample(args) -> dict:
    seed, space, pin, batch_id, origin, _gate = args
    sc = sample(seed, space, pin=pin, origin=origin)
    result, _ = build_run(sc)
    return summarise(result, sc, batch_id, False)


def _worker_scenario(args) -> dict:
    sc, batch_id, _gate = args
    result, _ = build_run(sc)
    return summarise(result, sc, batch_id, False)


def _worker_replay(args) -> tuple | None:
    """Re-run one stored scenario purely to capture its replay window."""
    import json as _j
    import zlib as _z
    from .scenario import scenario_from_dict

    scenario_json, = args
    sc = scenario_from_dict(_j.loads(scenario_json))
    result, _ = build_run(sc)
    focus = pick_focus(result)
    if focus is None:
        return None
    ts, drivers, ttc = focus
    payload = extract_window(result, ts, drivers)
    # Compress in the worker: the parent would otherwise carry every payload
    # through a pipe uncompressed and then compress them all single-threaded.
    return (sc.id, ts, drivers, ttc, _z.compress(_j.dumps(payload).encode(), 6))


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def default_workers() -> int:
    # Measured scaling on this class of machine keeps improving up to the full
    # core count, so there is no reason to hold one back.
    return max(1, min(os.cpu_count() or 2, 12))


def run_monte_carlo(
    store,
    n_runs: int,
    space: ScenarioSpace | None = None,
    *,
    pin: dict | None = None,
    seed_base: int = 483_921,
    label: str = "",
    batch_id: str | None = None,
    workers: int | None = None,
    mode: str = "monte_carlo",
    replay_budget: int = 400,
    progress: Callable[[dict], None] | None = None,
    flush_every: int = 250,
) -> str:
    """Run a Monte Carlo batch, streaming results into the store.

    Seeds are ``seed_base + i``, so a batch is fully reproducible from its
    (seed_base, n_runs, space, pin) tuple alone.
    """
    space = space or ScenarioSpace()
    batch_id = batch_id or uuid.uuid4().hex[:12]
    workers = workers or default_workers()
    store.create_batch(batch_id, label or f"Monte Carlo x{n_runs}", mode, n_runs,
                       space.to_dict(), pin or {}, dict(workers=workers), seed_base)

    tasks = [
        (seed_base + i, space, pin, batch_id, "monte_carlo", _REPLAY_TTC_GATE)
        for i in range(n_runs)
    ]
    return _execute(store, batch_id, tasks, _worker_sample, workers, n_runs,
                    replay_budget, progress, flush_every)


def run_scenarios(
    store,
    scenarios: list[Scenario],
    *,
    batch_id: str | None = None,
    label: str = "",
    mode: str = "experiment",
    workers: int | None = None,
    replay_budget: int = 200,
    progress: Callable[[dict], None] | None = None,
    flush_every: int = 250,
) -> str:
    batch_id = batch_id or uuid.uuid4().hex[:12]
    workers = workers or default_workers()
    store.create_batch(batch_id, label or f"{len(scenarios)} scenarios", mode,
                       len(scenarios), None, None, dict(workers=workers), 0)
    tasks = [(sc, batch_id, _REPLAY_TTC_GATE) for sc in scenarios]
    return _execute(store, batch_id, tasks, _worker_scenario, workers,
                    len(scenarios), replay_budget, progress, flush_every)


def _execute(store, batch_id, tasks, worker, workers, n_runs, replay_budget,
             progress, flush_every) -> str:
    t0 = time.perf_counter()
    run_buf: list[dict] = []
    conf_buf: list[dict] = []
    ev_buf: list[dict] = []
    agg = dict(
        conflicts=0, critical=0, warnings=0, near_misses=0, collisions=0,
        light_contacts=0, off_track=0, spins=0, evasive=0, overtake_attempts=0,
        overtakes_completed=0, driver_errors=0,
    )
    seg_totals: dict[int, int] = {}
    event_type_totals: dict[str, int] = {}
    ttc_values: list[float] = []
    pet_values: list[float] = []
    completed = 0

    def flush():
        nonlocal run_buf, conf_buf, ev_buf
        if run_buf:
            store.insert_runs(run_buf)
            run_buf = []
        if conf_buf:
            store.insert_conflicts(conf_buf)
            conf_buf = []
        if ev_buf:
            store.insert_events(ev_buf)
            ev_buf = []

    ctx = mp.get_context("spawn")
    chunk = max(1, min(40, n_runs // (workers * 4) or 1))
    with ctx.Pool(processes=workers) as pool:
        for res in pool.imap_unordered(worker, tasks, chunksize=chunk):
            completed += 1
            r = res["run"]
            run_buf.append(r)
            conf_buf.extend(res["conflicts"])
            ev_buf.extend(res["events"])

            agg["conflicts"] += r["n_conflicts"]
            agg["critical"] += r["n_critical"]
            agg["warnings"] += r["n_warnings"]
            agg["near_misses"] += r["n_near_misses"]
            agg["collisions"] += r["n_collisions"]
            agg["light_contacts"] += r["n_light_contacts"]
            agg["off_track"] += r["n_off_track"]
            agg["spins"] += r["n_spins"]
            agg["evasive"] += r["n_evasive"]
            agg["overtake_attempts"] += r["n_overtake_attempts"]
            agg["overtakes_completed"] += r["n_overtakes_completed"]
            agg["driver_errors"] += r["n_driver_errors"]
            if r["min_ttc"] is not None:
                ttc_values.append(r["min_ttc"])
            if r["min_pet"] is not None:
                pet_values.append(r["min_pet"])
            for k, v in res["segment_conflicts"].items():
                seg_totals[int(k)] = seg_totals.get(int(k), 0) + v
            for k, v in res["event_type_counts"].items():
                event_type_totals[k] = event_type_totals.get(k, 0) + v

            if completed % flush_every == 0:
                flush()
                store.update_batch_progress(batch_id, completed)
            if progress and (completed % 25 == 0 or completed == n_runs):
                progress(dict(
                    batch_id=batch_id, completed=completed, total=n_runs,
                    elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    **agg,
                ))

    flush()
    store.update_batch_progress(batch_id, completed)

    # Second pass: capture replay windows for the most severe runs only, by
    # re-running those scenarios. Deterministic seeding makes the re-run identical
    # to the original, so nothing is lost by not having recorded it the first time.
    n_replays = generate_replays(store, batch_id, replay_budget, workers,
                                 progress=progress)

    wall = (time.perf_counter() - t0) * 1000.0
    summary = dict(
        n_runs=completed,
        **agg,
        mean_min_ttc=float(np.mean(ttc_values)) if ttc_values else None,
        median_min_ttc=float(np.median(ttc_values)) if ttc_values else None,
        p05_min_ttc=float(np.percentile(ttc_values, 5)) if ttc_values else None,
        median_min_pet=float(np.median(pet_values)) if pet_values else None,
        runs_with_conflict=len(ttc_values),
        runs_with_replay=n_replays,
        segment_conflicts=seg_totals,
        event_type_totals=event_type_totals,
        wall_time_ms=wall,
        runs_per_second=completed / max(wall / 1000.0, 1e-6),
        workers=None,
    )
    store.update_batch_progress(batch_id, completed)
    store.finish_batch(batch_id, summary, wall)
    return batch_id


def select_replay_targets(store, batch_id: str, budget: int) -> list[dict]:
    """Which runs deserve a stored replay.

    Every run that produced contact, a spin or a barrier strike first, then the
    lowest minimum TTC, then the highest severity index — capped at the budget.
    """
    return store.q(
        """
        SELECT id, scenario_json, min_ttc, peak_scsi
        FROM runs
        WHERE batch_id = ? AND n_conflicts > 0
        ORDER BY (n_collisions + n_spins + n_barrier_strikes) DESC,
                 min_ttc ASC, peak_scsi DESC
        LIMIT ?
        """,
        (batch_id, budget),
    )


def generate_replays(
    store, batch_id: str, budget: int, workers: int | None = None,
    progress: Callable[[dict], None] | None = None,
) -> int:
    targets = select_replay_targets(store, batch_id, budget)
    if not targets:
        return 0
    workers = workers or default_workers()
    tasks = [(t["scenario_json"],) for t in targets]
    stored: list[str] = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=workers) as pool:
        for out in pool.imap_unordered(_worker_replay, tasks, chunksize=4):
            if out is None:
                continue
            run_id, ts, drivers, ttc, blob = out
            store.connect().execute(
                "INSERT OR REPLACE INTO replays (run_id, batch_id, focus_timestep, "
                "focus_drivers, min_ttc, payload) VALUES (?,?,?,?,?,?)",
                (run_id, batch_id, ts, _json(drivers), ttc, blob),
            )
            stored.append(run_id)
            if progress and len(stored) % 25 == 0:
                progress(dict(batch_id=batch_id, phase="replays",
                              completed=len(stored), total=len(targets)))

    store.exec("UPDATE runs SET has_replay=0 WHERE batch_id=?", (batch_id,))
    for i in range(0, len(stored), 400):
        chunk = stored[i:i + 400]
        qmarks = ",".join("?" * len(chunk))
        store.exec(
            f"UPDATE runs SET has_replay=1 WHERE batch_id=? AND id IN ({qmarks})",
            (batch_id, *chunk),
        )
    return len(stored)
