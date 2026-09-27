"""Apex Passport: demo data.

Seeds a database with two cars whose passports exercise every screen: part
condition across green / amber / red, a hash-chained history of races, an
inspection and a part replacement, an incident with a claim pack that shows
new damage, and a completed stress test.

The demo car's race history is not invented numbers: each race is a real
simulated race with that car as the team car, and the wear it adds comes from
the same wear model a stress test uses. Every such race event says so in its
details (``source: "simulated for demo"``), so the demo can't be mistaken for
recorded data. The starting part condition, set by an intake inspection, is
the one hand-chosen input -- picked so that every part status and policy state
appears on screen.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from .batch import build_run
from .car_profiles import from_preset
from .insurance import log_incident
from .passport import (
    HistoryEventType, create_car, get_car, get_parts, record_event, replace_part,
    set_part_life,
)
from .scenario import ScenarioSpace, sample
from .stress_test import run_stress_test
from .wear import wear_for_race

DEMO_CAR_NAME = "Car #7 (demo)"
DEMO_STUDENT_CAR_NAME = "Student car (demo)"

DEMO_TRACK = "vale_park"
DEMO_SEED = 910_000

# Condition at the intake inspection, % life used. Chosen so the finished demo
# shows every state: suspension_fl red then replaced, wheels red (policy
# "at risk"), brakes amber, harness/seat partway through their service life.
INTAKE_CONDITION = {
    "suspension_fl": 92.0,
    "suspension_fr": 38.0,
    "suspension_rl": 44.0,
    "suspension_rr": 41.0,
    "wheels": 91.0,
    "brakes": 72.0,
    "harness": 55.0,
    "seat": 30.0,
}

# The races on the demo car's record, oldest first.
DEMO_RACES = [
    dict(weather="DRY", days_ago=28),
    dict(weather="DAMP", days_ago=21),
    dict(weather="WET", days_ago=14),
    dict(weather="DRY"),               # today: the race with the incident
]

# Extra life used on the struck corner in the incident race, on top of the
# simulated wear. Makes the claim pack's before/after difference visible.
INCIDENT_DAMAGE = {"suspension_fr": 30.0, "wheels": 4.0}


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _simulate_race(car: dict, weather: str, seed: int) -> dict:
    """One simulated race with this car as the team car; returns its telemetry."""
    sc = sample(seed, ScenarioSpace(),
                pin=dict(track_id=DEMO_TRACK, weather=weather, n_cars=22),
                origin="manual", label=f"passport_demo:{car['id']}")
    sc.team_car = dict(car_profile=car["car_profile"],
                       driver_archetype=car["team_driver"]["archetype"],
                       driver_overrides=car["team_driver"]["overrides"] or None)
    result, _ = build_run(sc)
    return result.team_car_telemetry or {}


def _apply_race(store, car: dict, race_no: int, weather: str, time: str | None,
                seed: int, extra_damage: dict[str, float] | None = None,
                incident_id: str | None = None) -> dict:
    telemetry = _simulate_race(car, weather, seed)
    wear = wear_for_race(telemetry)
    for part, amount in (extra_damage or {}).items():
        wear[part] = wear.get(part, 0.0) + amount
    current = {p["name"]: p["life_used_pct"] for p in get_parts(store, car["id"])}
    for part, amount in wear.items():
        if amount:
            set_part_life(store, car["id"], part, current.get(part, 0.0) + amount)
    details = dict(
        race=race_no, track_id=DEMO_TRACK, weather=weather, seed=seed,
        source="simulated for demo",
        kerb_strikes=len(telemetry.get("kerb_strikes", [])),
        contacts=len(telemetry.get("contacts", [])),
        life_used_added={k: round(v, 2) for k, v in wear.items() if v},
    )
    if incident_id:
        details["incident_id"] = incident_id
    return record_event(store, car["id"], HistoryEventType.RACE, details, time=time)


def seed_passport_demo(
    store, n_races: int = 100, workers: int | None = None, force: bool = False,
    log: Callable[[str], None] = print,
    progress: Callable[[dict], None] | None = None,
) -> dict:
    """Creates the demo cars and their history. Skips (returning the existing
    demo car) if a demo car is already present, unless ``force``."""
    existing = store.q1("SELECT id FROM cars WHERE name=?", (DEMO_CAR_NAME,))
    if existing and not force:
        log(f"Demo car already present ({existing['id']}); use --force to add another.")
        return dict(car_id=existing["id"], created=False)

    now = datetime.now(timezone.utc)

    # -- A fresh car for contrast. Created first so Car #7, the newer of the
    # two, is the car the Passport screens open on. -------------------------
    student_id = create_car(
        store, DEMO_STUDENT_CAR_NAME, "FORMULA_STUDENT", from_preset("FORMULA_STUDENT"),
        dict(archetype="SMOOTH", overrides={}),
    )
    log(f"Created {DEMO_STUDENT_CAR_NAME} ({student_id})")

    # -- Car #7: an F4 car with an aggressive late-braking driver -----------
    car_id = create_car(
        store, DEMO_CAR_NAME, "F4", from_preset("F4"),
        dict(archetype="LATE_BRAKER", overrides=dict(aggression=0.82)),
    )
    car = get_car(store, car_id)
    log(f"Created {DEMO_CAR_NAME} ({car_id})")

    intake_time = now - timedelta(days=35)
    for part, pct in INTAKE_CONDITION.items():
        set_part_life(store, car_id, part, pct)
    record_event(store, car_id, HistoryEventType.INSPECTION, dict(
        kind="intake", note="Condition recorded when the car joined the passport.",
        life_used_pct=INTAKE_CONDITION,
    ), time=_iso(intake_time))

    for i, race in enumerate(DEMO_RACES[:2], start=1):
        _apply_race(store, car, i, race["weather"],
                    _iso(now - timedelta(days=race["days_ago"])), DEMO_SEED + i)
        log(f"  race {i} ({race['weather'].lower()}) recorded")

    replace_part(store, car_id, "suspension_fl", time=_iso(now - timedelta(days=17)))
    log("  front-left suspension replaced")

    race = DEMO_RACES[2]
    _apply_race(store, car, 3, race["weather"],
                _iso(now - timedelta(days=race["days_ago"])), DEMO_SEED + 3)
    log(f"  race 3 ({race['weather'].lower()}) recorded")

    # Race 4: the incident is logged first, which freezes the pre-damage
    # condition; the race's wear and the impact damage are applied after.
    incident = log_incident(
        store, car_id,
        "Contact with car #12 at the Turn 6 hairpin; right-front impact.",
        occurred_at=_iso(now - timedelta(hours=2)),
        affected_parts=["suspension_fr", "wheels"],
    )
    # time=None stamps it as recorded, after the incident event just written.
    _apply_race(store, car, 4, DEMO_RACES[3]["weather"], None, DEMO_SEED + 4,
                extra_damage=INCIDENT_DAMAGE, incident_id=incident["incident_id"])
    log("  race 4 recorded, with an incident and claim pack")

    log(f"  stress test: {n_races} simulated races (dry)…")
    result = run_stress_test(store, car_id, track_id=DEMO_TRACK, weather="DRY",
                             n_races=n_races, base_seed=DEMO_SEED + 100,
                             workers=workers, progress=progress)

    return dict(car_id=car_id, student_car_id=student_id,
                incident_id=incident["incident_id"],
                stress_test_batch_id=result["batch_id"], created=True)
