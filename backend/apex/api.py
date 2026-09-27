"""HTTP API.

Read endpoints serve cached analyses out of SQLite. Write endpoints (running a
batch, a guided search, an experiment) start background work and report progress
over Server-Sent Events, because a 10,000-run batch takes minutes and the UI needs
to fill as it goes.

One convention runs through every response that carries simulated counts: a
``note`` or ``caveat`` field stating what the numbers are. The frontend renders
these rather than inventing its own wording, so the distinction between simulated
conflict frequency and real-world risk is carried by the data and cannot be lost
in the UI layer.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import assumptions as A
from .analysis import (compute_and_store_all, conflict_breakdown,
                       environment_analysis, hotspot_detail, hotspots,
                       interaction_matrix, overview, sensitivity)
from .batch import default_workers, run_monte_carlo
from .circuits import get_track, list_tracks
from .discovery import (compare_search_strategies, discover_patterns,
                        guided_search)
from .drivers import ARCHETYPES, archetype_catalogue, build_roster
from .experiments import (EXPERIMENTS, INTERVENTION_PRESETS, run_experiment,
                          run_intervention)
from .explain import explain_hotspot, explain_run
from .jobs import JOB_LOCK, JOBS, Job, fail_job, finish_job, new_job, progress_for
from .live import run_for_streaming
from .models import Weather
from .nlquery import SUGGESTIONS, ask
from .passport_api import router as passport_router
from .report import generate_report
from .scenario import ScenarioSpace, sample, scenario_from_dict
from .storage import DEFAULT_DB, Store
from .track import TrackGeometry, build_zones

DB_PATH = os.environ.get("APEX_DB", str(DEFAULT_DB))
store = Store(DB_PATH)

app = FastAPI(
    title="APEX Safety Stress Tester",
    version="0.1.0",
    description=(
        "Multi-agent motorsport safety stress testing. All counts and rates served "
        "by this API are outputs of a simulation model under stated assumptions. "
        "None is a real-world crash probability."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Apex Passport: all car/passport/stress-test/insurance routes live in their
# own module and are mounted here, so the existing routes above are never
# touched by that feature's development.
app.include_router(passport_router)

DISCLAIMER = (
    "Simulated results under stated model assumptions. Not a real-world crash "
    "probability or safety assessment."
)


# ==========================================================================
# Job registry for long-running work -- see jobs.py (also used by passport_api)
# ==========================================================================
_new_job = new_job
_progress_for = progress_for
_finish = finish_job
_fail = fail_job


# ==========================================================================
# Reference data
# ==========================================================================
@app.get("/api/health")
def health():
    return dict(status="ok", db=DB_PATH, workers=default_workers(),
                batches=store.q1("SELECT COUNT(*) c FROM batches")["c"],
                runs=store.q1("SELECT COUNT(*) c FROM runs")["c"])


@app.get("/api/meta")
def meta():
    return dict(
        name="APEX",
        subtitle="Multi-Agent Motorsport Safety Stress Tester",
        disclaimer=DISCLAIMER,
        positioning=(
            "This is not a replacement for a professional motorsport simulator, and "
            "it does not suggest that teams or the FIA do not already perform "
            "simulation and circuit safety analysis — they do, at far higher "
            "fidelity. What this prototype adds is the layer above such a "
            "simulator: automated generation of a large scenario population, "
            "surrogate-safety scoring of every run, and discovery of which "
            "combinations of behaviour, traffic and conditions keep producing "
            "safety-critical interactions."
        ),
        tracks=list_tracks(),
        archetypes=archetype_catalogue(),
        weathers=[w.value for w in Weather],
        experiments=[dict(key=k, **{kk: vv for kk, vv in v.items() if kk != "arms"},
                          arms=[a["label"] for a in v["arms"]])
                     for k, v in EXPERIMENTS.items()],
        intervention_presets=INTERVENTION_PRESETS,
        query_suggestions=SUGGESTIONS,
        default_space=ScenarioSpace().to_dict(),
        thresholds=dict(
            ttc_conflict=A.TTC_CONFLICT_THRESHOLD,
            ttc_critical=A.TTC_CRITICAL_THRESHOLD,
            pet_conflict=A.PET_CONFLICT_THRESHOLD,
            pet_critical=A.PET_CRITICAL_THRESHOLD,
            hard_braking=A.HARD_BRAKING_THRESHOLD,
            emergency_braking=A.EMERGENCY_BRAKING_THRESHOLD,
            evasive_lateral=A.EVASIVE_LATERAL_THRESHOLD,
        ),
    )


@app.get("/api/assumptions")
def get_assumptions():
    snap = A.snapshot()
    return dict(
        groups=A.groups(),
        assumptions=snap,
        counts=dict(
            total=len(snap),
            methodology=sum(1 for a in snap if a["kind"] == "methodology"),
            assumption=sum(1 for a in snap if a["kind"] == "assumption"),
        ),
        provenance_note=(
            "Entries marked 'methodology' take their concept from established "
            "surrogate safety practice (chiefly FHWA's SSAM) — the concept is "
            "external, the exact value here may still be adapted. Entries marked "
            "'assumption' are choices made by this prototype: not measured, not "
            "validated, and changing them changes the results."
        ),
        scsi=dict(
            weights=A.SCSI_WEIGHTS,
            closing_speed_ref=A.SCSI_CLOSING_SPEED_REF,
            decel_ref=A.SCSI_DECEL_REF,
            definition=(
                "SCSI = 0.40*clip(1 - minTTC/1.5) + 0.20*clip(1 - minPET/5.0) "
                "+ 0.25*clip(closing_speed/55) + 0.15*clip(peak_decel/45). "
                "A constructed ranking aid. Not a validated severity measure and "
                "not a probability."
            ),
        ),
        references=[
            dict(label="FIA Circuit Safety", url="https://www.fia.com/circuit-safety"),
            dict(label="FIA Circuit Safety Analysis System",
                 url="https://www.fia.com/news/fia-safety-week-how-fia-has-expanded-circuit-homologation-boost-safety-and-grow-participation"),
            dict(label="FIA Activity Report 2024 — Safety",
                 url="https://activityreport2024.fia.com/sport-championships/safety-and-technological-development/"),
            dict(label="FHWA SSAM overview",
                 url="https://www.fhwa.dot.gov/publications/research/safety/10020/"),
            dict(label="FHWA SSAM technical summary (FHWA-HRT-08-049)",
                 url="https://www.fhwa.dot.gov/publications/research/safety/08049/"),
            dict(label="FHWA SSAM user manual (FHWA-HRT-08-050)",
                 url="https://www.fhwa.dot.gov/publications/research/safety/08050/"),
        ],
    )


@app.get("/api/track/{track_id}")
def get_track_geometry(track_id: str, width_multiplier: float = 1.0):
    try:
        track = get_track(track_id)
    except KeyError:
        raise HTTPException(404, f"unknown circuit '{track_id}'")
    geo = TrackGeometry(track, width_multiplier)
    zinfo = build_zones(track)
    n = len(geo.cx)
    step = max(1, n // 1400)
    left_x, left_y = geo.to_cartesian(geo.cs[::step], geo.width(geo.cs[::step]) / 2)
    right_x, right_y = geo.to_cartesian(geo.cs[::step], -geo.width(geo.cs[::step]) / 2)
    return dict(
        id=track.id, name=track.name, country=track.country,
        length=round(track.length, 2),
        closure_error=round(getattr(track, "closure_error", 0.0), 4),
        width_multiplier=width_multiplier,
        centreline=dict(
            x=[round(float(v), 2) for v in geo.cx[::step]],
            y=[round(float(v), 2) for v in geo.cy[::step]],
            s=[round(float(v), 2) for v in geo.cs[::step]],
            heading=[round(float(v), 4) for v in geo.ch[::step]],
            width=[round(float(v), 2) for v in geo.width(geo.cs[::step])],
        ),
        edges=dict(
            left=dict(x=[round(float(v), 2) for v in left_x],
                      y=[round(float(v), 2) for v in left_y]),
            right=dict(x=[round(float(v), 2) for v in right_x],
                       y=[round(float(v), 2) for v in right_y]),
        ),
        racing_line=dict(
            s=[round(float(v), 2) for v in geo.cs[::step]],
            d=[round(float(v), 3) for v in geo.racing_line(geo.cs[::step])],
        ),
        segments=[dict(
            index=s.index, name=s.name, type=s.type.value, turn_number=s.turn_number,
            length=round(s.length, 2), width=round(s.width * width_multiplier, 2),
            curvature=round(s.curvature, 6), corner_radius=s.corner_radius,
            target_speed=round(s.target_speed, 2),
            target_speed_kph=round(s.target_speed * 3.6, 1),
            is_braking_zone=s.is_braking_zone,
            overtaking_opportunity=s.overtaking_opportunity,
            runoff_width=s.runoff_width, barrier_distance=s.barrier_distance,
            s_start=round(s.s_start, 2), s_end=round(s.s_end, 2),
            s_mid=round(s.s_mid, 2),
        ) for s in track.segments],
        zones=list(zinfo["zones"].values()),
        segment_to_zone=zinfo["segment_to_zone"],
    )


@app.get("/api/drivers")
def get_drivers(n_cars: int = 22):
    roster = build_roster(n_cars)
    return dict(
        roster=[p.to_dict() for p in roster],
        archetypes=archetype_catalogue(),
        note=(
            "Every value is a simulation parameter. None is a measured property of "
            "any real driver. Profiles are generic behavioural archetypes; a "
            "profile labelled after a real driver would be a behavioural "
            "abstraction over publicly observable racing behaviour, never a digital "
            "twin."
        ),
    )


# ==========================================================================
# Batches
# ==========================================================================
class SpaceModel(BaseModel):
    track_ids: list[str] | None = None
    weathers: list[str] | None = None
    n_cars_choices: list[int] | None = None
    traffic_density: tuple[float, float] | None = None
    grid_spread: tuple[float, float] | None = None
    pace_spread: tuple[float, float] | None = None
    track_width_multiplier: tuple[float, float] | None = None
    error_rate_multiplier: tuple[float, float] | None = None
    tyre_condition: tuple[float, float] | None = None
    archetypes: list[str] | None = None
    duration: float | None = None

    def to_space(self) -> ScenarioSpace:
        sp = ScenarioSpace()
        for k, v in self.model_dump(exclude_none=True).items():
            setattr(sp, k, v)
        return sp


class RunBatchRequest(BaseModel):
    n_runs: int = Field(2000, ge=1, le=50_000)
    seed_base: int = 483_921
    label: str = ""
    space: SpaceModel | None = None
    pin: dict[str, Any] | None = None
    replay_budget: int = Field(400, ge=0, le=3000)
    workers: int | None = None
    analyse: bool = True


@app.post("/api/batches")
def start_batch(req: RunBatchRequest):
    job = _new_job("monte_carlo", req.label or f"Monte Carlo x{req.n_runs}",
                   req.n_runs)
    space = req.space.to_space() if req.space else ScenarioSpace()

    def work():
        try:
            bid = run_monte_carlo(
                store, req.n_runs, space, pin=req.pin, seed_base=req.seed_base,
                label=req.label, workers=req.workers,
                replay_budget=req.replay_budget, progress=_progress_for(job))
            job.batch_id = bid
            if req.analyse:
                job.phase = "analysing"
                job.push(dict(phase="analysing", batch_id=bid))
                compute_and_store_all(store, bid)
                discover_patterns(store, bid, top_n=20)
            _finish(job, dict(batch_id=bid), bid)
        except Exception as exc:
            _fail(job, exc)

    threading.Thread(target=work, daemon=True).start()
    return job.snapshot()


class GuidedRequest(BaseModel):
    generations: int = Field(6, ge=1, le=30)
    population: int = Field(60, ge=4, le=1000)
    elite_size: int = Field(12, ge=1, le=100)
    exploration_fraction: float = Field(0.25, ge=0.0, le=1.0)
    mutation_strength: float = Field(1.0, ge=0.1, le=3.0)
    seed_batch_id: str | None = None
    seed_base: int = 771_337
    label: str = ""
    space: SpaceModel | None = None
    analyse: bool = True


@app.post("/api/search/guided")
def start_guided(req: GuidedRequest):
    total = req.generations * req.population
    job = _new_job("guided", req.label or "Guided scenario search", total)
    space = req.space.to_space() if req.space else ScenarioSpace()

    def work():
        try:
            out = guided_search(
                store, generations=req.generations, population=req.population,
                elite_size=req.elite_size,
                exploration_fraction=req.exploration_fraction,
                mutation_strength=req.mutation_strength,
                seed_batch_id=req.seed_batch_id, seed_base=req.seed_base,
                space=space, label=req.label, progress=_progress_for(job))
            bid = out["batch_id"]
            job.batch_id = bid
            if req.analyse:
                job.phase = "analysing"
                job.push(dict(phase="analysing", batch_id=bid))
                compute_and_store_all(store, bid)
                discover_patterns(store, bid, top_n=20)
            _finish(job, out, bid)
        except Exception as exc:
            _fail(job, exc)

    threading.Thread(target=work, daemon=True).start()
    return job.snapshot()


@app.get("/api/jobs")
def list_jobs():
    with JOB_LOCK:
        return dict(jobs=[j.snapshot() for j in
                          sorted(JOBS.values(), key=lambda j: -j.started)][:40])


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    snap = job.snapshot()
    snap["result"] = job.result
    return snap


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")

    async def gen():
        yield f"data: {json.dumps(job.snapshot())}\n\n"
        last = time.time()
        while True:
            try:
                payload = job.events.get_nowait()
                snap = job.snapshot()
                snap["event"] = payload
                yield f"data: {json.dumps(snap)}\n\n"
                last = time.time()
            except queue.Empty:
                if job.status != "running":
                    snap = job.snapshot()
                    snap["result"] = job.result
                    yield f"data: {json.dumps(snap)}\n\n"
                    break
                if time.time() - last > 2.0:
                    yield ": keep-alive\n\n"
                    last = time.time()
                await asyncio.sleep(0.15)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/batches")
def list_batches(limit: int = 50):
    rows = store.q(
        "SELECT id, created_at, label, mode, n_runs_requested, n_runs_completed, "
        "status, wall_time_ms, seed_base FROM batches "
        "ORDER BY created_at DESC LIMIT ?", (limit,))
    for r in rows:
        agg = store.q1(
            "SELECT SUM(n_conflicts) conflicts, SUM(n_critical) critical, "
            "SUM(n_collisions) collisions, SUM(n_near_misses) near_misses, "
            "AVG(min_ttc) avg_min_ttc, MIN(min_ttc) lowest_min_ttc, "
            "AVG(min_pet) avg_min_pet, AVG(n_cars) avg_cars "
            "FROM runs WHERE batch_id=?", (r["id"],)) or {}
        r.update({k: (round(v, 5) if isinstance(v, float) else v)
                  for k, v in agg.items()})
    return dict(batches=rows, note=DISCLAIMER)


@app.get("/api/batches/latest")
def latest_batch():
    b = store.latest_batch()
    if not b:
        raise HTTPException(404, "no completed batch yet")
    return dict(batch_id=b["id"], label=b["label"], mode=b["mode"],
                created_at=b["created_at"],
                n_runs=b["n_runs_completed"])


@app.delete("/api/batches/{batch_id}")
def delete_batch(batch_id: str):
    for t in ("replays", "events", "conflicts", "runs", "patterns", "analysis"):
        store.exec(f"DELETE FROM {t} WHERE batch_id=?", (batch_id,))
    store.exec("DELETE FROM batches WHERE id=?", (batch_id,))
    return dict(deleted=batch_id)


# ==========================================================================
# Analysis
# ==========================================================================
def _cached(batch_id: str, kind: str, fn):
    payload = store.get_analysis(batch_id, kind)
    if payload is None:
        payload = fn()
        store.save_analysis(batch_id, kind, payload)
    return payload


@app.get("/api/analysis/{batch_id}/overview")
def api_overview(batch_id: str):
    return _cached(batch_id, "overview", lambda: overview(store, batch_id))


@app.get("/api/analysis/{batch_id}/hotspots")
def api_hotspots(batch_id: str, track_id: str = "vale_park"):
    return _cached(batch_id, "hotspots", lambda: hotspots(store, batch_id, track_id))


@app.get("/api/analysis/{batch_id}/hotspots/{segment_index}")
def api_hotspot_detail(batch_id: str, segment_index: int):
    out = explain_hotspot(store, batch_id, segment_index)
    if not out:
        raise HTTPException(404, "no data for that segment")
    return out


@app.get("/api/analysis/{batch_id}/sensitivity")
def api_sensitivity(batch_id: str):
    return _cached(batch_id, "sensitivity", lambda: sensitivity(store, batch_id))


@app.get("/api/analysis/{batch_id}/interactions")
def api_interactions(batch_id: str):
    return _cached(batch_id, "interaction_matrix",
                   lambda: interaction_matrix(store, batch_id))


@app.get("/api/analysis/{batch_id}/environment")
def api_environment(batch_id: str):
    return _cached(batch_id, "environment",
                   lambda: environment_analysis(store, batch_id))


@app.get("/api/analysis/{batch_id}/conflicts")
def api_conflict_breakdown(batch_id: str):
    return _cached(batch_id, "conflict_breakdown",
                   lambda: conflict_breakdown(store, batch_id))


@app.post("/api/analysis/{batch_id}/recompute")
def api_recompute(batch_id: str):
    out = compute_and_store_all(store, batch_id)
    pats = discover_patterns(store, batch_id, top_n=20)
    return dict(batch_id=batch_id, kinds=list(out), patterns=len(pats))


# ==========================================================================
# Patterns
# ==========================================================================
@app.get("/api/patterns/{batch_id}")
def api_patterns(batch_id: str, limit: int = 20, min_occurrences: int = 2,
                 recompute: bool = False):
    if recompute:
        discover_patterns(store, batch_id, top_n=limit,
                          min_occurrences=min_occurrences)
    rows = store.q(
        "SELECT * FROM patterns WHERE batch_id=? ORDER BY rank LIMIT ?",
        (batch_id, limit))
    if not rows:
        rows = discover_patterns(store, batch_id, top_n=limit,
                                 min_occurrences=min_occurrences)
    for r in rows:
        r["example_run_ids"] = json.loads(r.get("example_run_ids_json") or "[]")
        r["conditions"] = json.loads(r.get("conditions_json") or "{}")
        r.pop("example_run_ids_json", None)
        r.pop("conditions_json", None)
    return dict(
        batch_id=batch_id, patterns=rows,
        interpretation=(
            "An occurrence count is the number of simulated runs in which this "
            "canonical situation produced a qualifying conflict, out of the runs "
            "evaluated. It is NOT a real-world probability and must not be read as "
            "one. The pattern key is zone, weather, traffic band and conflict type; "
            "the behavioural profiles and errors shown are the dominant composition "
            "within the pattern, with their share given, not part of its definition. "
            "Read the raw count together with the rate: a pattern's raw count also "
            "reflects how often its weather and traffic band happened to be sampled, "
            "so the rate within that band is the fairer comparison between patterns."
        ),
    )


# ==========================================================================
# Runs, conflicts, events, replays
# ==========================================================================
@app.get("/api/runs")
def api_runs(
    batch_id: str | None = None,
    weather: str | None = None,
    min_cars: int | None = None,
    max_min_ttc: float | None = None,
    has_collision: bool | None = None,
    has_replay: bool | None = None,
    severity: str | None = None,
    order: str = Query("min_ttc", pattern="^(min_ttc|peak_scsi|created_at|n_critical|n_conflicts)$"),
    direction: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = 100,
    offset: int = 0,
):
    where, params = [], []
    if batch_id:
        where.append("batch_id=?"); params.append(batch_id)
    if weather:
        where.append("weather=?"); params.append(weather)
    if min_cars:
        where.append("n_cars>=?"); params.append(min_cars)
    if max_min_ttc is not None:
        where.append("min_ttc<=?"); params.append(max_min_ttc)
    if has_collision:
        where.append("n_collisions>0")
    if has_replay:
        where.append("has_replay=1")
    if severity == "CRITICAL":
        where.append("n_critical>0")
    sql = "SELECT * FROM runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    nulls = " NULLS LAST" if order == "min_ttc" and direction == "asc" else ""
    sql += f" ORDER BY {order} {direction.upper()}{nulls} LIMIT ? OFFSET ?"
    rows = store.q(sql, (*params, limit, offset))
    for r in rows:
        r["field_mix"] = json.loads(r.pop("field_mix_json", None) or "[]")
        r["error_counts"] = json.loads(r.pop("error_counts_json", None) or "{}")
        r.pop("scenario_json", None)
    total_sql = "SELECT COUNT(*) c FROM runs" + (
        " WHERE " + " AND ".join(where) if where else "")
    total = store.q1(total_sql, tuple(params))["c"]
    return dict(runs=rows, total=total, limit=limit, offset=offset, note=DISCLAIMER)


@app.get("/api/runs/{run_id}")
def api_run(run_id: str):
    run = store.q1("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run:
        raise HTTPException(404, "unknown run")
    run["field_mix"] = json.loads(run.pop("field_mix_json", None) or "[]")
    run["error_counts"] = json.loads(run.pop("error_counts_json", None) or "{}")
    run["scenario"] = json.loads(run.pop("scenario_json", None) or "{}")
    conflicts = store.q(
        "SELECT * FROM conflicts WHERE run_id=? ORDER BY min_ttc ASC", (run_id,))
    events = store.q(
        "SELECT * FROM events WHERE run_id=? ORDER BY t ASC", (run_id,))
    for e in events:
        e["detail"] = json.loads(e.pop("detail_json", None) or "{}")
    return dict(run=run, conflicts=conflicts, events=events, note=DISCLAIMER)


@app.get("/api/runs/{run_id}/replay")
def api_replay(run_id: str):
    payload = store.get_replay(run_id)
    if payload is None:
        raise HTTPException(
            404, "no replay stored for this run; only the most severe runs in a "
                 "batch retain one")
    return payload


@app.get("/api/runs/{run_id}/explain")
def api_explain(run_id: str):
    out = explain_run(store, run_id)
    if not out:
        raise HTTPException(404, "unknown run")
    return out


@app.get("/api/conflicts")
def api_conflicts(
    batch_id: str | None = None,
    severity: str | None = None,
    conflict_type: str | None = None,
    weather: str | None = None,
    segment_index: int | None = None,
    turn_number: int | None = None,
    max_ttc: float | None = None,
    max_pet: float | None = None,
    archetype: str | None = None,
    collision: bool | None = None,
    evasive: bool | None = None,
    order: str = Query("min_ttc", pattern="^(min_ttc|scsi|closing_speed|min_pet)$"),
    limit: int = 200,
    offset: int = 0,
):
    where, params = [], []
    def add(clause, *p):
        where.append(clause); params.extend(p)
    if batch_id: add("c.batch_id=?", batch_id)
    if severity: add("c.severity=?", severity)
    if conflict_type: add("c.conflict_type=?", conflict_type)
    if weather: add("c.weather=?", weather)
    if segment_index is not None: add("c.segment_index=?", segment_index)
    if turn_number is not None: add("c.turn_number=?", turn_number)
    if max_ttc is not None: add("c.min_ttc<=?", max_ttc)
    if max_pet is not None: add("c.min_pet<=?", max_pet)
    if archetype: add("(c.archetype_a=? OR c.archetype_b=?)", archetype, archetype)
    if collision is not None: add("c.collision=?", 1 if collision else 0)
    if evasive is not None: add("c.evasive_action=?", 1 if evasive else 0)
    sql = ("SELECT c.*, r.has_replay, r.grip, r.visibility, r.n_cars, "
           "r.traffic_density_measured, r.dominant_error "
           "FROM conflicts c JOIN runs r ON r.id=c.run_id")
    if where:
        sql += " WHERE " + " AND ".join(where)
    desc = " DESC" if order == "scsi" or order == "closing_speed" else " ASC"
    sql += f" ORDER BY c.{order}{desc} LIMIT ? OFFSET ?"
    rows = store.q(sql, (*params, limit, offset))
    csql = "SELECT COUNT(*) c FROM conflicts c" + (
        " WHERE " + " AND ".join(w.replace("c.", "c.") for w in where) if where else "")
    total = store.q1(csql, tuple(params))["c"]
    return dict(conflicts=rows, total=total, limit=limit, offset=offset,
                note=DISCLAIMER)


@app.get("/api/events")
def api_events(batch_id: str | None = None, event_type: str | None = None,
               severity: str | None = None, limit: int = 200):
    where, params = [], []
    if batch_id:
        where.append("batch_id=?"); params.append(batch_id)
    if event_type:
        where.append("event_type=?"); params.append(event_type)
    if severity:
        where.append("severity=?"); params.append(severity)
    sql = "SELECT * FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t ASC LIMIT ?"
    rows = store.q(sql, (*params, limit))
    for e in rows:
        e["detail"] = json.loads(e.pop("detail_json", None) or "{}")
    return dict(events=rows)


# ==========================================================================
# Live simulation
# ==========================================================================
class LiveRequest(BaseModel):
    seed: int = 483_921
    track_id: str = "vale_park"
    n_cars: int = Field(22, ge=2, le=22)
    weather: str = "WET"
    traffic_density: float = Field(0.7, ge=0.0, le=1.0)
    duration: float = Field(75.0, ge=10.0, le=180.0)
    error_rate_multiplier: float = Field(1.0, ge=0.0, le=4.0)
    track_width_multiplier: float = Field(1.0, ge=0.7, le=1.4)
    overtake_threshold_delta: float = 0.0
    field_mix: list[str] | None = None


@app.post("/api/live/run")
def api_live_run(req: LiveRequest):
    pin = dict(track_id=req.track_id, n_cars=req.n_cars, weather=req.weather,
               traffic_density=req.traffic_density, duration=req.duration,
               error_rate_multiplier=req.error_rate_multiplier,
               track_width_multiplier=req.track_width_multiplier,
               overtake_threshold_delta=req.overtake_threshold_delta)
    if req.field_mix:
        pin["field_mix"] = req.field_mix
    sc = sample(req.seed, ScenarioSpace(), pin=pin, origin="manual",
                label="live")
    return run_for_streaming(sc)


# ==========================================================================
# Experiments and what-if
# ==========================================================================
class ExperimentRequest(BaseModel):
    key: str
    runs_per_arm: int = Field(150, ge=10, le=3000)
    seed_base: int = 900_000


@app.post("/api/experiments")
def api_run_experiment(req: ExperimentRequest):
    if req.key not in EXPERIMENTS:
        raise HTTPException(404, f"unknown experiment '{req.key}'")
    spec = EXPERIMENTS[req.key]
    total = req.runs_per_arm * len(spec["arms"])
    job = _new_job("experiment", spec["name"], total)

    def work():
        try:
            out = run_experiment(store, req.key, runs_per_arm=req.runs_per_arm,
                                 seed_base=req.seed_base,
                                 progress=_progress_for(job))
            _finish(job, out)
        except Exception as exc:
            _fail(job, exc)

    threading.Thread(target=work, daemon=True).start()
    return job.snapshot()


class InterventionRequest(BaseModel):
    n_runs: int = Field(200, ge=10, le=3000)
    changes: dict[str, Any]
    pin: dict[str, Any] | None = None
    seed_base: int = 555_000
    label: str = ""


@app.post("/api/whatif")
def api_whatif(req: InterventionRequest):
    job = _new_job("intervention", req.label or "Intervention", req.n_runs * 2)

    def work():
        try:
            out = run_intervention(
                store, n_runs=req.n_runs, changes=req.changes, pin=req.pin,
                seed_base=req.seed_base, label=req.label,
                progress=_progress_for(job))
            _finish(job, out)
        except Exception as exc:
            _fail(job, exc)

    threading.Thread(target=work, daemon=True).start()
    return job.snapshot()


@app.get("/api/experiments/stored")
def api_stored_experiments(limit: int = 40):
    rows = store.q(
        "SELECT id, created_at, name, kind, config_json, batch_ids_json "
        "FROM experiments ORDER BY created_at DESC LIMIT ?", (limit,))
    for r in rows:
        r["config"] = json.loads(r.pop("config_json") or "{}")
        r["batch_ids"] = json.loads(r.pop("batch_ids_json") or "[]")
    return dict(experiments=rows)


@app.get("/api/experiments/stored/{exp_id}")
def api_stored_experiment(exp_id: str):
    r = store.q1("SELECT * FROM experiments WHERE id=?", (exp_id,))
    if not r:
        raise HTTPException(404, "unknown experiment")
    return dict(
        id=r["id"], name=r["name"], kind=r["kind"], created_at=r["created_at"],
        config=json.loads(r["config_json"] or "{}"),
        results=json.loads(r["results_json"] or "{}"),
        batch_ids=json.loads(r["batch_ids_json"] or "[]"),
    )


@app.get("/api/search/compare")
def api_compare_search(random_batch_id: str, guided_batch_id: str):
    return compare_search_strategies(store, random_batch_id, guided_batch_id)


# ==========================================================================
# Ask the simulator / report
# ==========================================================================
class AskRequest(BaseModel):
    batch_id: str
    question: str


@app.post("/api/ask")
def api_ask(req: AskRequest):
    return ask(store, req.batch_id, req.question)


@app.get("/api/report/{batch_id}")
def api_report(batch_id: str):
    return generate_report(store, batch_id)


@app.get("/api/report/{batch_id}/markdown", response_class=PlainTextResponse)
def api_report_md(batch_id: str):
    return generate_report(store, batch_id)["markdown"]
