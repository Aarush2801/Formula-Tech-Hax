"""Scenario discovery: pattern recurrence and guided search.

Two distinct jobs live here.

**Pattern canonicalisation.** A raw conflict record is too specific to recur — no
two runs share a floating-point traffic density. So each qualifying conflict is
reduced to a *canonical key*: where it happened, the weather, banded traffic and
field size, the two behavioural archetypes involved, the conflict type, and the
dominant human error in that run. Conflicts that reduce to the same key are the
same situation recurring. ``occurrences`` counts the number of distinct simulated
runs in which a key appeared.

That count is a property of this model under the stated assumptions. It is not a
frequency of anything in the real world, and the API and UI label it as such
everywhere it is surfaced.

**Guided search.** Random sampling spends most of its budget on scenarios that
produce nothing. The guided search instead keeps an elite set of scenarios that
did produce severe conflicts and spends the next generation's budget mutating
around them. The objective is deliberately a *search* objective and is named as
one — maximising it finds interesting regions of the parameter space, and says
nothing about real-world risk.

One safeguard matters. If the search only maximised severity it would converge on
a single lucky random draw and then report it as a recurring pattern. Two things
prevent that: mutation redraws the seed, so a child is a genuinely new run, and
elite selection is diversity-aware, keeping the best scenario per canonical
pattern rather than the best N overall.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import assumptions as A
from .batch import _worker_scenario, default_workers, summarise
from .models import Scenario
from .circuits import get_track
from .scenario import ScenarioSpace, mutate, sample, scenario_from_dict

# --------------------------------------------------------------------------
# Banding
# --------------------------------------------------------------------------
def traffic_band(density: float) -> str:
    if density < 0.30:
        return "LOW"
    if density < 0.55:
        return "MEDIUM"
    return "HIGH"


def field_band(n_cars: int) -> str:
    if n_cars <= 10:
        return "SMALL"
    if n_cars <= 16:
        return "MEDIUM"
    return "FULL"


PATTERN_SEVERITIES = ("CRITICAL", "INCIDENT")


def pattern_key(
    segment_index: int, weather: str, traffic: str, field: str,
    arch_a: str, arch_b: str, conflict_type: str, dominant_error: str | None,
) -> str:
    a, b = sorted([arch_a or "?", arch_b or "?"])
    return "|".join([
        str(segment_index), weather, traffic, field, a, b, conflict_type,
        dominant_error or "none",
    ])


# --------------------------------------------------------------------------
# Pattern discovery over a completed batch
# --------------------------------------------------------------------------
def discover_patterns(
    store, batch_id: str, *, top_n: int = 20, min_occurrences: int = 2,
    severities: tuple[str, ...] = PATTERN_SEVERITIES,
    track_id: str = "vale_park",
) -> list[dict]:
    """Group qualifying conflicts into recurring canonical patterns.

    The key is deliberately coarse: **zone x weather x traffic band x conflict
    type**. An earlier version also keyed on the archetype pair, the field size and
    the dominant error, which pushed the key space past three million combinations
    — every conflict became its own "pattern" and nothing ever recurred. A pattern
    that occurs twice in 400 runs is not a pattern, it is a coincidence with a
    label.

    The archetype pair, field size and dominant error have not been discarded.
    They are reported as the *dominant composition within* each pattern, with
    counts, which is both more useful and more honest: it says "this situation
    recurred 347 times, and the two behaviours most often involved were these"
    rather than pretending the behaviours were part of the definition.
    """
    from .track import build_zones

    runs_evaluated = store.q1(
        "SELECT COUNT(*) c FROM runs WHERE batch_id=?", (batch_id,)
    )["c"]
    if not runs_evaluated:
        return []

    track = get_track(track_id)
    zinfo = build_zones(track)
    seg2zone = zinfo["segment_to_zone"]
    zones = zinfo["zones"]

    # How many runs fell in each (weather, traffic band) cell. Without this, a
    # recurrence count conflates "this situation keeps happening" with "this band
    # was sampled often": uniform weather sampling and a wide MEDIUM traffic band
    # make DRY/MEDIUM the most populous cell by construction, so it tops the raw
    # ranking whether or not it is actually the most conflict-prone.
    band_counts: dict[tuple[str, str], int] = {}
    for r in store.q(
        """SELECT weather, traffic_density_measured FROM runs WHERE batch_id=?""",
        (batch_id,),
    ):
        key = (r["weather"], traffic_band(r["traffic_density_measured"] or 0.0))
        band_counts[key] = band_counts.get(key, 0) + 1

    placeholders = ",".join("?" * len(severities))
    rows = store.q(
        f"""
        SELECT c.*, r.dominant_error, r.traffic_density_measured,
               r.n_cars AS run_cars, r.track_id, r.has_replay, r.peak_scsi,
               r.grip, r.visibility, r.error_rate_multiplier,
               r.track_width_multiplier
        FROM conflicts c JOIN runs r ON r.id = c.run_id
        WHERE c.batch_id = ? AND c.severity IN ({placeholders})
        """,
        (batch_id, *severities),
    )
    if not rows:
        return []

    groups: dict[str, list[dict]] = {}
    for r in rows:
        zone = seg2zone.get(r["segment_index"])
        if zone is None:
            continue
        r["_zone"] = zone
        key = "|".join([
            f"T{zone}",
            r["weather"],
            traffic_band(r["traffic_density_measured"] or 0.0),
            r["conflict_type"],
        ])
        groups.setdefault(key, []).append(r)

    patterns: list[dict] = []
    for key, items in groups.items():
        run_ids = {i["run_id"] for i in items}
        occurrences = len(run_ids)
        if occurrences < min_occurrences:
            continue
        zkey, weather, traffic, ctype = key.split("|")
        zone_no = int(zkey[1:])
        zone = zones[zone_no]

        ttc = np.array([i["min_ttc"] for i in items], dtype=float)
        pet = np.array([i["min_pet"] for i in items if i["min_pet"] is not None],
                       dtype=float)
        closing = np.array([i["closing_speed"] for i in items], dtype=float)
        decel = np.array([i["max_deceleration"] for i in items], dtype=float)
        scsi_v = np.array([i["scsi"] for i in items], dtype=float)

        pair_counts = Counter(
            tuple(sorted([i["archetype_a"] or "?", i["archetype_b"] or "?"]))
            for i in items
        )
        error_counts = Counter(
            i["dominant_error"] for i in items if i["dominant_error"]
        )
        decision_counts = Counter(
            f"{i['a_decision']} / {i['b_decision']}" for i in items
            if i["a_decision"]
        )
        seg_counts = Counter(i["location"] for i in items)
        top_pair = pair_counts.most_common(1)[0] if pair_counts else (("?", "?"), 0)

        with_replay = [i["run_id"] for i in items if i["has_replay"]]
        examples = list(dict.fromkeys(with_replay))[:6]
        if len(examples) < 3:
            for rid in dict.fromkeys(i["run_id"] for i in items):
                if rid not in examples:
                    examples.append(rid)
                if len(examples) >= 3:
                    break

        patterns.append(dict(
            id=uuid.uuid4().hex[:16],
            batch_id=batch_id,
            pattern_key=key,
            track_id=track_id,
            segment_index=zone["corner_segment_index"],
            location=zone["name"],
            turn_number=zone_no,
            weather=weather,
            n_cars=int(round(float(np.mean([i["run_cars"] for i in items])))),
            traffic_band=traffic,
            # Dominant composition, NOT part of the pattern definition.
            archetype_a=top_pair[0][0],
            archetype_b=top_pair[0][1],
            conflict_type=ctype,
            dominant_error=error_counts.most_common(1)[0][0] if error_counts else None,
            occurrences=occurrences,
            runs_evaluated=runs_evaluated,
            # Runs that were drawn in this pattern's weather and traffic band, and
            # the conditional rate within them. The rate is the fairer comparison
            # across patterns; the raw count is the one the brief asks for.
            band_runs=band_counts.get((weather, traffic), 0),
            occurrence_rate=(
                occurrences / band_counts[(weather, traffic)]
                if band_counts.get((weather, traffic)) else None
            ),
            median_min_ttc=float(np.median(ttc)),
            p05_min_ttc=float(np.percentile(ttc, 5)),
            median_min_pet=float(np.median(pet)) if len(pet) else None,
            median_closing_speed=float(np.median(closing)),
            evasive_rate=float(np.mean([bool(i["evasive_action"]) for i in items])),
            collision_rate=float(np.mean([bool(i["collision"]) for i in items])),
            mean_scsi=float(np.mean(scsi_v)),
            example_run_ids_json=json.dumps(examples),
            conditions_json=json.dumps(dict(
                zone=zone["name"],
                corner_name=zone["corner_name"],
                corner_radius=zone["corner_radius"],
                zone_min_width=zone["min_width"],
                runoff_width=zone["runoff_width"],
                overtaking_opportunity=zone["overtaking_opportunity"],
                weather=weather,
                traffic_band=traffic,
                conflict_instances=len(items),
                mean_traffic_density=float(np.mean(
                    [i["traffic_density_measured"] or 0.0 for i in items])),
                mean_n_cars=float(np.mean([i["run_cars"] for i in items])),
                mean_grip=float(np.mean([i["grip"] for i in items])),
                mean_visibility=float(np.mean([i["visibility"] for i in items])),
                field_bands=dict(Counter(field_band(i["run_cars"]) for i in items)),
                dominant_archetype_pairs=[
                    dict(pair=list(p), count=c, share=round(c / len(items), 4))
                    for p, c in pair_counts.most_common(5)
                ],
                dominant_errors=[
                    dict(error=e, count=c, share=round(c / len(items), 4))
                    for e, c in error_counts.most_common(5)
                ],
                decision_pairs=[
                    dict(decisions=d, count=c) for d, c in decision_counts.most_common(5)
                ],
                segments_within_zone=[
                    dict(location=l, count=c) for l, c in seg_counts.most_common(6)
                ],
                median_max_deceleration=float(np.median(decel)),
                median_max_deceleration_g=float(np.median(decel)) / 9.81,
            )),
        ))

    # Recurrence first — the point is patterns that keep reappearing — with
    # severity as the tiebreak.
    patterns.sort(key=lambda p: (-p["occurrences"], -p["mean_scsi"]))
    for i, p in enumerate(patterns[:top_n], start=1):
        p["rank"] = i
    top = patterns[:top_n]
    store.save_patterns(batch_id, top)
    return top


# --------------------------------------------------------------------------
# Guided / adversarial search
# --------------------------------------------------------------------------
def search_objective(run_row: dict) -> float:
    """The quantity the guided search maximises.

    A SEARCH objective, not a risk measure. It rewards runs that produced severe,
    numerous conflicts, because those are the regions of the parameter space worth
    sampling more densely. Deliberately built from the same surrogate measures
    reported elsewhere so that what the search optimises is legible.
    """
    peak = run_row.get("peak_scsi") or 0.0
    n_crit = run_row.get("n_critical") or 0
    n_inc = (run_row.get("n_collisions") or 0) + (run_row.get("n_spins") or 0) \
        + (run_row.get("n_off_track") or 0)
    min_ttc = run_row.get("min_ttc")
    ttc_term = 0.0 if min_ttc is None else float(
        np.clip(1.0 - min_ttc / A.TTC_CONFLICT_THRESHOLD, 0.0, 1.0))
    return float(
        0.45 * peak
        + 0.30 * ttc_term
        + 0.15 * np.tanh(n_crit / 4.0)
        + 0.10 * np.tanh(n_inc / 3.0)
    )


@dataclass
class GenerationStats:
    generation: int
    n_runs: int
    best_objective: float
    mean_objective: float
    median_objective: float
    critical_conflicts: int
    collisions: int
    distinct_patterns: int
    elite_objective_mean: float
    wall_ms: float


def _run_population(
    store, batch_id: str, scenarios: list[Scenario], workers: int,
    progress: Callable[[dict], None] | None, generation: int, total_planned: int,
    done_so_far: int,
) -> list[dict]:
    """Execute one population, persist it, and return the run rows."""
    rows: list[dict] = []
    conf: list[dict] = []
    evs: list[dict] = []
    tasks = [(sc, batch_id, A.TTC_CRITICAL_THRESHOLD) for sc in scenarios]
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=workers) as pool:
        for res in pool.imap_unordered(_worker_scenario, tasks, chunksize=2):
            rows.append(res["run"])
            conf.extend(res["conflicts"])
            evs.extend(res["events"])
            if progress and len(rows) % 10 == 0:
                progress(dict(
                    batch_id=batch_id, phase="guided", generation=generation,
                    completed=done_so_far + len(rows), total=total_planned,
                ))
    store.insert_runs(rows)
    store.insert_conflicts(conf)
    store.insert_events(evs)
    return rows


def guided_search(
    store,
    *,
    generations: int = 6,
    population: int = 60,
    elite_size: int = 12,
    exploration_fraction: float = 0.25,
    seed_base: int = 771_337,
    space: ScenarioSpace | None = None,
    seed_batch_id: str | None = None,
    label: str = "",
    workers: int | None = None,
    batch_id: str | None = None,
    progress: Callable[[dict], None] | None = None,
    replay_budget: int = 250,
    mutation_strength: float = 1.0,
) -> dict:
    """Iteratively mutate toward regions that produce severe conflicts.

    ``seed_batch_id`` lets the search start from the elites of a completed Monte
    Carlo batch rather than from scratch, which is the intended use: random search
    establishes the baseline, guided search then concentrates on what it found.
    """
    from .batch import generate_replays

    space = space or ScenarioSpace()
    workers = workers or default_workers()
    batch_id = batch_id or uuid.uuid4().hex[:12]
    rng = np.random.default_rng(seed_base)
    t_start = time.perf_counter()
    total_planned = generations * population

    store.create_batch(
        batch_id, label or f"Guided search {generations}x{population}", "guided",
        total_planned, space.to_dict(), None,
        dict(generations=generations, population=population,
             elite_size=elite_size, exploration_fraction=exploration_fraction,
             mutation_strength=mutation_strength, seed_batch_id=seed_batch_id,
             objective="search_objective: 0.45*peak_SCSI + 0.30*(1-minTTC/1.5) "
                      "+ 0.15*tanh(n_critical/4) + 0.10*tanh(n_incident/3)"),
        seed_base,
    )

    # ---- seed the elite set ------------------------------------------------
    elites: list[tuple[float, Scenario]] = []
    if seed_batch_id:
        seed_rows = store.q(
            """SELECT scenario_json, peak_scsi, n_critical, n_collisions, n_spins,
                      n_off_track, min_ttc
               FROM runs WHERE batch_id=? AND n_conflicts>0
               ORDER BY peak_scsi DESC LIMIT ?""",
            (seed_batch_id, elite_size * 2),
        )
        for r in seed_rows:
            sc = scenario_from_dict(json.loads(r["scenario_json"]))
            elites.append((search_objective(dict(r)), sc))

    history: list[GenerationStats] = []
    seed_counter = seed_base
    completed = 0
    all_objectives: list[float] = []

    for gen in range(1, generations + 1):
        t_gen = time.perf_counter()
        pop: list[Scenario] = []

        n_explore = max(1, int(population * exploration_fraction)) if elites \
            else population
        n_exploit = population - n_explore

        for _ in range(n_explore):
            seed_counter += 1
            pop.append(sample(seed_counter, space, origin="guided"))

        if elites and n_exploit > 0:
            # Fitness-proportionate selection over the elite set, with the
            # mutation strength decaying as the search focuses.
            weights = np.array([max(o, 1e-3) for o, _ in elites], dtype=float)
            weights = weights / weights.sum()
            strength = mutation_strength * (1.0 - 0.5 * (gen - 1) / max(generations - 1, 1))
            for _ in range(n_exploit):
                seed_counter += 1
                parent = elites[int(rng.choice(len(elites), p=weights))][1]
                pop.append(mutate(parent, seed_counter, rng, space,
                                  strength=strength))

        for sc in pop:
            sc.generation = gen

        rows = _run_population(store, batch_id, pop, workers, progress, gen,
                               total_planned, completed)
        completed += len(rows)
        store.update_batch_progress(batch_id, completed)

        scored = [(search_objective(r), r) for r in rows]
        objs = [s for s, _ in scored]
        all_objectives.extend(objs)

        # ---- diversity-aware elite update ---------------------------------
        by_row = {r["id"]: r for _, r in scored}
        candidates: list[tuple[float, Scenario]] = list(elites)
        for obj, r in scored:
            candidates.append((obj, scenario_from_dict(json.loads(r["scenario_json"]))))
        # Keep the best scenario per coarse signature, so the elite set cannot
        # collapse onto many near-copies of one lucky run.
        best_by_sig: dict[tuple, tuple[float, Scenario]] = {}
        for obj, sc in sorted(candidates, key=lambda x: -x[0]):
            sig = (
                sc.environment.weather.value,
                field_band(sc.n_cars),
                traffic_band(sc.traffic_density),
                round(sc.track_width_multiplier, 1),
            )
            if sig not in best_by_sig:
                best_by_sig[sig] = (obj, sc)
        elites = sorted(best_by_sig.values(), key=lambda x: -x[0])[:elite_size]

        history.append(GenerationStats(
            generation=gen,
            n_runs=len(rows),
            best_objective=float(max(objs)) if objs else 0.0,
            mean_objective=float(np.mean(objs)) if objs else 0.0,
            median_objective=float(np.median(objs)) if objs else 0.0,
            critical_conflicts=int(sum(r["n_critical"] for r in rows)),
            collisions=int(sum(r["n_collisions"] for r in rows)),
            distinct_patterns=len(best_by_sig),
            elite_objective_mean=float(np.mean([o for o, _ in elites])) if elites else 0.0,
            wall_ms=(time.perf_counter() - t_gen) * 1000.0,
        ))

    n_replays = generate_replays(store, batch_id, replay_budget, workers,
                                progress=progress)
    wall = (time.perf_counter() - t_start) * 1000.0

    from dataclasses import asdict
    summary = dict(
        n_runs=completed,
        generations=generations,
        population=population,
        history=[asdict(h) for h in history],
        best_objective=max((h.best_objective for h in history), default=0.0),
        first_generation_mean=history[0].mean_objective if history else 0.0,
        last_generation_mean=history[-1].mean_objective if history else 0.0,
        runs_with_replay=n_replays,
        wall_time_ms=wall,
        objective_definition=(
            "0.45*peak_SCSI + 0.30*clip(1 - minTTC/1.5) + 0.15*tanh(n_critical/4) "
            "+ 0.10*tanh(n_incident/3). A search objective only."
        ),
    )
    store.finish_batch(batch_id, summary, wall)
    return dict(batch_id=batch_id, summary=summary)


def compare_search_strategies(store, random_batch_id: str,
                              guided_batch_id: str) -> dict:
    """Experiment 9: does guided search find more severe scenarios per run?"""
    out = {}
    for name, bid in (("random", random_batch_id), ("guided", guided_batch_id)):
        r = store.q1(
            """SELECT COUNT(*) runs,
                      SUM(n_critical) critical,
                      SUM(n_collisions) collisions,
                      AVG(peak_scsi) mean_peak_scsi,
                      MIN(min_ttc) lowest_min_ttc,
                      AVG(CASE WHEN n_critical>0 THEN 1.0 ELSE 0.0 END) frac_runs_critical
               FROM runs WHERE batch_id=?""",
            (bid,),
        )
        rows = store.q("SELECT peak_scsi, n_critical, n_collisions, n_spins, "
                       "n_off_track, min_ttc FROM runs WHERE batch_id=?", (bid,))
        objs = [search_objective(dict(x)) for x in rows]
        out[name] = dict(
            batch_id=bid,
            runs=r["runs"],
            critical_conflicts=r["critical"] or 0,
            collisions=r["collisions"] or 0,
            mean_peak_scsi=round(r["mean_peak_scsi"] or 0.0, 5),
            lowest_min_ttc=r["lowest_min_ttc"],
            fraction_runs_with_critical=round(r["frac_runs_critical"] or 0.0, 5),
            critical_per_run=round((r["critical"] or 0) / max(r["runs"], 1), 4),
            mean_objective=round(float(np.mean(objs)), 5) if objs else 0.0,
            p90_objective=round(float(np.percentile(objs, 90)), 5) if objs else 0.0,
        )
    if out.get("random") and out.get("guided"):
        rnd, gd = out["random"], out["guided"]
        out["delta"] = dict(
            critical_per_run_ratio=round(
                gd["critical_per_run"] / max(rnd["critical_per_run"], 1e-9), 3),
            mean_objective_ratio=round(
                gd["mean_objective"] / max(rnd["mean_objective"], 1e-9), 3),
            note=(
                "Ratios compare how efficiently each strategy finds severe "
                "simulated scenarios per run. They say nothing about real-world "
                "frequencies."
            ),
        )
    return out
