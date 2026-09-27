"""Apex Passport step 3: stress test.

Given a car, track, weather and N simulated races, runs N scenarios with that
car as the team car and reports: predicted life used per part at race end
(median and range across the N races), how many of those N races crossed the
red threshold, close calls/contacts involving the team car, a cost forecast,
and plain recommendations. Logged as a history event on completion.

Deliberately reuses batch.build_run/summarise and storage.Store.insert_runs
unmodified -- the only new code here is the orchestration and the wear
aggregation, so a stress test's runs behave exactly like any other simulated
run for every existing analysis/replay tool.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import statistics
import uuid
from datetime import datetime, timezone
from typing import Callable

from . import assumptions as A
from .batch import build_run, default_workers, generate_replays, summarise
from .passport import HistoryEventType, get_car, get_parts, part_status_for, record_event
from .scenario import ScenarioSpace, sample
from .wear import estimated_repair_cost, wear_for_race


def _worker_stress_run(args):
    scenario, batch_id = args
    result, _profiles = build_run(scenario)
    row = summarise(result, scenario, batch_id, False)
    return row["run"], row["conflicts"], row["events"], result.team_car_telemetry


def _build_scenarios(car: dict, track_id: str, weather: str, n_races: int,
                     base_seed: int, driver: dict, n_cars: int):
    team_car = dict(car_profile=car["car_profile"], driver_archetype=driver["archetype"],
                    driver_overrides=driver["overrides"] or None)
    scenarios = []
    for i in range(n_races):
        sc = sample(base_seed + i, ScenarioSpace(),
                   pin=dict(track_id=track_id, weather=weather, n_cars=n_cars),
                   origin="manual", label=f"stress_test:{car['id']}")
        sc.team_car = team_car
        scenarios.append(sc)
    return scenarios


def run_stress_test(
    store, car_id: str, track_id: str = "vale_park", weather: str = "DRY",
    n_races: int | None = None, base_seed: int = 600_000,
    driver_archetype: str | None = None, n_cars: int = 22,
    workers: int | None = None, progress: Callable[[dict], None] | None = None,
) -> dict:
    car = get_car(store, car_id)
    if not car:
        raise KeyError(f"unknown car '{car_id}'")
    n_races = n_races or A.STRESS_TEST_DEFAULT_N_RACES
    workers = workers or default_workers()
    batch_id = uuid.uuid4().hex[:12]
    # The car's saved team driver, unless the caller names an archetype for
    # this one test -- then that plain archetype is used, with no overrides.
    driver = (dict(archetype=driver_archetype, overrides={}) if driver_archetype
              else car["team_driver"])

    scenarios = _build_scenarios(car, track_id, weather, n_races, base_seed,
                                 driver, n_cars)
    store.create_batch(batch_id, f"Stress test: {car['name']}", "stress_test",
                      n_races, None, None, dict(car_id=car_id, workers=workers),
                      base_seed)

    run_rows, conflict_rows, event_rows, telemetries = [], [], [], []
    ctx = mp.get_context("spawn")
    completed = 0
    with ctx.Pool(processes=workers) as pool:
        for run_row, conflicts, events, telemetry in pool.imap_unordered(
            _worker_stress_run, [(sc, batch_id) for sc in scenarios], chunksize=4,
        ):
            run_rows.append(run_row)
            conflict_rows.extend(conflicts)
            event_rows.extend(events)
            telemetries.append(telemetry)
            completed += 1
            if progress and (completed % 10 == 0 or completed == n_races):
                progress(dict(batch_id=batch_id, completed=completed, total=n_races))

    store.insert_runs(run_rows)
    store.insert_conflicts(conflict_rows)
    store.insert_events(event_rows)
    store.update_batch_progress(batch_id, completed)
    n_replays = generate_replays(store, batch_id, budget=min(60, n_races), workers=workers)
    # run_rows were built before the replay pass, so their has_replay flags
    # are stale; refresh them so close calls link to the replays that exist.
    replayed = {r["id"] for r in store.q(
        "SELECT id FROM runs WHERE batch_id=? AND has_replay=1", (batch_id,))}
    for row in run_rows:
        row["has_replay"] = row["id"] in replayed
    store.finish_batch(batch_id, dict(n_runs=completed, runs_with_replay=n_replays), 0.0)

    result = _summarise(store, car, batch_id, track_id, weather, n_races, run_rows, telemetries)
    result["driver"] = driver

    store.exec(
        "INSERT INTO stress_tests (id, car_id, created_at, track_id, weather, "
        "n_races, batch_id, status, results_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex[:12], car_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
         track_id, weather, n_races, batch_id, "complete", json.dumps(result)),
    )

    record_event(store, car_id, HistoryEventType.STRESS_TEST, dict(
        batch_id=batch_id, track_id=track_id, weather=weather, n_races=n_races,
        driver=driver, parts_crossing_red=result["parts_crossing_red_count"],
        total_cost_forecast=result["cost_forecast"]["total"],
    ))
    return result


def latest_stress_test(store, car_id: str) -> dict | None:
    row = store.q1(
        "SELECT * FROM stress_tests WHERE car_id=? AND status='complete' "
        "ORDER BY created_at DESC LIMIT 1", (car_id,))
    if not row:
        return None
    return {**json.loads(row["results_json"]), "created_at": row["created_at"]}


def _summarise(store, car: dict, batch_id: str, track_id: str, weather: str,
              n_races: int, run_rows: list[dict], telemetries: list[dict | None]) -> dict:
    current_parts = {p["name"]: p for p in get_parts(store, car["id"])}

    per_part_end_of_race: dict[str, list[float]] = {p: [] for p in A.PASSPORT_PARTS}
    for telemetry in telemetries:
        increment = wear_for_race(telemetry)
        for part in A.PASSPORT_PARTS:
            current = current_parts.get(part, {}).get("life_used_pct", 0.0)
            per_part_end_of_race[part].append(
                min(100.0, current + increment.get(part, 0.0)))

    parts_report = []
    parts_crossing_red_count = 0
    for part, values in per_part_end_of_race.items():
        crossings = sum(1 for v in values if v >= A.PASSPORT_LIFE_RED_PCT)
        if crossings > 0:
            parts_crossing_red_count += 1
        parts_report.append(dict(
            part=part,
            current_life_used_pct=round(current_parts.get(part, {}).get("life_used_pct", 0.0), 2),
            predicted_median_pct=round(statistics.median(values), 2),
            predicted_min_pct=round(min(values), 2),
            predicted_max_pct=round(max(values), 2),
            races_crossing_red=crossings,
            races_evaluated=n_races,
            status=part_status_for(statistics.median(values)),
        ))
    parts_report.sort(key=lambda p: p["predicted_median_pct"], reverse=True)

    close_calls = [
        dict(run_id=r["id"], min_ttc=r["min_ttc"], min_pet=r["min_pet"],
            n_collisions=r["n_collisions"], n_light_contacts=r["n_light_contacts"],
            has_replay=bool(r["has_replay"]))
        for r in run_rows if r["min_ttc"] is not None and r["min_ttc"] < A.TTC_CRITICAL_THRESHOLD
    ]
    close_calls.sort(key=lambda c: c["min_ttc"])

    wear_cost = sum(
        current_parts.get(p["part"], {}).get("part_cost", 0.0) * (p["races_crossing_red"] / n_races)
        for p in parts_report
    )
    repair_cost = statistics.mean(
        [estimated_repair_cost(t) for t in telemetries]) if telemetries else 0.0
    cost_forecast = dict(
        expected_wear_replacement_cost=round(wear_cost, 2),
        expected_repair_cost_per_race=round(repair_cost, 2),
        total=round(wear_cost + repair_cost, 2),
    )

    recommendations = []
    for p in parts_report:
        if p["status"] == "red":
            recommendations.append(
                f"Replace {p['part'].replace('_', ' ')} before the next race -- "
                f"predicted {p['predicted_median_pct']}% life used "
                f"(crossed the red threshold in {p['races_crossing_red']}/{n_races} "
                "simulated races).")
        elif p["status"] == "amber":
            recommendations.append(
                f"Inspect {p['part'].replace('_', ' ')} before the next race -- "
                f"predicted {p['predicted_median_pct']}% life used.")
    if not recommendations:
        recommendations.append(
            "No part is predicted to reach the amber threshold across the simulated races.")

    return dict(
        batch_id=batch_id, car_id=car["id"], car_name=car["name"],
        track_id=track_id, weather=weather, n_races=n_races,
        parts=parts_report, parts_crossing_red_count=parts_crossing_red_count,
        close_calls=close_calls[:20], n_close_calls=len(close_calls),
        cost_forecast=cost_forecast, recommendations=recommendations,
        note=(
            f"All figures describe {n_races} simulated races under the stated "
            "assumptions (track, weather, driver archetype, and this car's "
            "current part condition). 'N of M simulated races' is a simulated "
            "frequency, not a real-world probability of failure or crash."
        ),
    )
