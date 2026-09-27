"""Apex Passport HTTP routes.

Mounted onto the main app in api.py via `app.include_router(passport_router)`.
Kept in its own module/router so this feature's routes are additive to the
existing API surface -- nothing here modifies an existing endpoint.

The same "not a real-world probability / not a quote or claim decision"
framing used throughout api.py is repeated in these payloads.
"""
from __future__ import annotations

import os
import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .car_profiles import CLASS_PRESETS, car_profile_from_dict, catalogue, from_preset
from .drivers import team_driver_traits
from .insurance import (
    build_claim_pack, evidence_pack, evidence_pack_html, insurer_risk_summary,
    list_incidents, log_incident, policy_conditions,
)
from .jobs import JOBS, fail_job, finish_job, new_job, progress_for
from .passport import (
    create_car, get_car, get_history, get_parts, list_cars, replace_part,
    set_team_driver, verify_chain,
)
from .storage import DEFAULT_DB, Store
from .stress_test import latest_stress_test, run_stress_test

router = APIRouter(prefix="/api", tags=["passport"])

# Same DB path resolution as api.py (APEX_DB env override, else DEFAULT_DB).
# sqlite3 connections are per-thread (see storage.Store.connect), so sharing
# this Store instance across api.py and passport_api.py is safe and gives
# both modules a consistent view of the same file.
store = Store(os.environ.get("APEX_DB", str(DEFAULT_DB)))

PASSPORT_DISCLAIMER = (
    "Simulated results under stated model assumptions. Not a real-world crash "
    "probability, an insurance quote, or a claim decision."
)


# ==========================================================================
# Cars
# ==========================================================================
class TeamDriverRequest(BaseModel):
    archetype: str | None = None
    overrides: dict[str, float] | None = None


class CarCreateRequest(BaseModel):
    name: str
    car_class: str = "CUSTOM"
    car_profile: dict[str, Any] | None = None
    team_driver: TeamDriverRequest | None = None


@router.get("/car-presets")
def get_car_presets():
    return dict(presets=catalogue(), classes=list(CLASS_PRESETS),
                driver_traits=team_driver_traits())


@router.get("/cars")
def api_list_cars():
    return dict(cars=list_cars(store), note=PASSPORT_DISCLAIMER)


@router.post("/cars")
def api_create_car(req: CarCreateRequest):
    if req.car_profile is not None:
        profile = car_profile_from_dict({**req.car_profile, "class_name": req.car_class})
    elif req.car_class in CLASS_PRESETS:
        profile = from_preset(req.car_class)
    else:
        raise HTTPException(
            400, f"unknown car_class '{req.car_class}' and no car_profile supplied")
    team_driver = req.team_driver.model_dump() if req.team_driver else None
    try:
        car_id = create_car(store, req.name, req.car_class, profile, team_driver)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return get_car(store, car_id)


@router.put("/cars/{car_id}/driver")
def api_set_team_driver(car_id: str, req: TeamDriverRequest):
    try:
        return set_team_driver(store, car_id, req.model_dump())
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/cars/{car_id}/passport")
def api_car_passport(car_id: str):
    car = get_car(store, car_id)
    if not car:
        raise HTTPException(404, f"unknown car '{car_id}'")
    return dict(
        car=car, parts=get_parts(store, car_id), history=get_history(store, car_id),
        chain_verification=verify_chain(store, car_id),
        policy_conditions=policy_conditions(store, car_id),
        note=PASSPORT_DISCLAIMER,
    )


@router.get("/cars/{car_id}/verify")
def api_verify_chain(car_id: str):
    if not get_car(store, car_id):
        raise HTTPException(404, f"unknown car '{car_id}'")
    return verify_chain(store, car_id)


# ==========================================================================
# Parts
# ==========================================================================
@router.post("/cars/{car_id}/parts/{part_name}/replace")
def api_replace_part(car_id: str, part_name: str):
    if not get_car(store, car_id):
        raise HTTPException(404, f"unknown car '{car_id}'")
    try:
        event = replace_part(store, car_id, part_name)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return dict(event=event, parts=get_parts(store, car_id))


# ==========================================================================
# Incidents / claim pack
# ==========================================================================
class IncidentCreateRequest(BaseModel):
    description: str
    occurred_at: str | None = None
    affected_parts: list[str] | None = None


@router.post("/cars/{car_id}/incidents")
def api_log_incident(car_id: str, req: IncidentCreateRequest):
    try:
        result = log_incident(store, car_id, req.description, req.occurred_at,
                              req.affected_parts)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    return result


@router.get("/cars/{car_id}/incidents")
def api_list_incidents(car_id: str):
    if not get_car(store, car_id):
        raise HTTPException(404, f"unknown car '{car_id}'")
    return dict(incidents=list_incidents(store, car_id))


@router.get("/cars/{car_id}/claim-pack/{incident_id}")
def api_claim_pack(car_id: str, incident_id: str):
    try:
        return build_claim_pack(store, car_id, incident_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


# ==========================================================================
# Stress test
# ==========================================================================
class StressTestRequest(BaseModel):
    track_id: str = "vale_park"
    weather: str = "DRY"
    n_races: int | None = Field(None, ge=10, le=5000)
    # None uses the car's saved team driver; naming an archetype runs this one
    # test with that plain archetype instead.
    driver_archetype: str | None = None
    base_seed: int = 600_000


@router.post("/cars/{car_id}/stress-test")
def api_start_stress_test(car_id: str, req: StressTestRequest):
    car = get_car(store, car_id)
    if not car:
        raise HTTPException(404, f"unknown car '{car_id}'")
    job = new_job("stress_test", f"Stress test: {car['name']}",
                 req.n_races or 200)

    def work():
        try:
            result = run_stress_test(
                store, car_id, track_id=req.track_id, weather=req.weather,
                n_races=req.n_races, base_seed=req.base_seed,
                driver_archetype=req.driver_archetype, progress=progress_for(job),
            )
            finish_job(job, result, result.get("batch_id"))
        except Exception as exc:
            fail_job(job, exc)

    threading.Thread(target=work, daemon=True).start()
    return job.snapshot()


@router.get("/stress-test/{job_id}")
def api_stress_test_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown stress-test job")
    snap = job.snapshot()
    snap["result"] = job.result
    return snap


@router.get("/cars/{car_id}/stress-tests/latest")
def api_latest_stress_test(car_id: str):
    if not get_car(store, car_id):
        raise HTTPException(404, f"unknown car '{car_id}'")
    return dict(result=latest_stress_test(store, car_id), note=PASSPORT_DISCLAIMER)


# ==========================================================================
# Insurance
# ==========================================================================
@router.get("/cars/{car_id}/insurer-summary")
def api_insurer_summary(car_id: str):
    try:
        return insurer_risk_summary(store, car_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@router.get("/cars/{car_id}/evidence-pack")
def api_evidence_pack(car_id: str, format: str = "json"):
    try:
        if format == "html":
            return HTMLResponse(evidence_pack_html(store, car_id))
        return evidence_pack(store, car_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
