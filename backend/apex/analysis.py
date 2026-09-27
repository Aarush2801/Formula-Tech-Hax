"""Analytics over a completed batch.

Every function here reads the database and returns plain dictionaries for the API
to serve. Nothing is invented: each number traces back to simulated trajectories
or to a configured assumption.

Two methodological points recur:

*Exposure normalisation.* Raw counts are misleading whenever the denominator
varies. The driver-interaction matrix is the clearest case — an archetype that
appears in more runs will accumulate more conflicts for that reason alone, so the
matrix reports conflicts per run in which both archetypes were present, and
exposes the co-presence count so the reader can see how thin any cell is.

*Association, not causation.* The sensitivity page reports how conflict frequency
varies across bands of a parameter, and a rank correlation. Because the Monte
Carlo sampler draws parameters independently, these associations are not confounded
by each other *within this model* — but they remain statements about the model, not
about racing.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

import numpy as np

from . import assumptions as A
from .circuits import get_track
from .drivers import ARCHETYPES
from .discovery import field_band, traffic_band

SEVERITY_ORDER = ["NORMAL", "WARNING", "CRITICAL", "INCIDENT"]


# ==========================================================================
# Batch overview
# ==========================================================================
def overview(store, batch_id: str) -> dict:
    b = store.q1("SELECT * FROM batches WHERE id=?", (batch_id,))
    if not b:
        return {}
    summary = json.loads(b["summary_json"]) if b["summary_json"] else {}
    agg = store.q1(
        """SELECT COUNT(*) runs, SUM(n_conflicts) conflicts, SUM(n_critical) critical,
                  SUM(n_warnings) warnings, SUM(n_near_misses) near_misses,
                  SUM(n_collisions) collisions, SUM(n_light_contacts) light_contacts,
                  SUM(n_off_track) off_track, SUM(n_spins) spins,
                  SUM(n_evasive) evasive, SUM(n_overtake_attempts) overtake_attempts,
                  SUM(n_overtakes_completed) overtakes_completed,
                  SUM(n_driver_errors) driver_errors,
                  AVG(min_ttc) avg_min_ttc, MIN(min_ttc) lowest_min_ttc,
                  AVG(min_pet) avg_min_pet, MIN(min_pet) lowest_min_pet,
                  MAX(max_closing_speed) max_closing_speed,
                  MAX(max_deceleration) max_deceleration,
                  AVG(n_cars) avg_cars, SUM(duration) total_simulated_seconds,
                  SUM(n_timesteps) total_timesteps
           FROM runs WHERE batch_id=?""",
        (batch_id,),
    ) or {}
    ttcs = [r["min_ttc"] for r in store.q(
        "SELECT min_ttc FROM runs WHERE batch_id=? AND min_ttc IS NOT NULL",
        (batch_id,))]
    runs_with_critical = store.q1(
        "SELECT COUNT(*) c FROM runs WHERE batch_id=? AND n_critical>0", (batch_id,)
    )["c"]
    runs_with_contact = store.q1(
        "SELECT COUNT(*) c FROM runs WHERE batch_id=? AND (n_collisions>0 OR "
        "n_light_contacts>0)", (batch_id,))["c"]

    return dict(
        batch_id=batch_id,
        label=b["label"],
        mode=b["mode"],
        status=b["status"],
        created_at=b["created_at"],
        n_runs_requested=b["n_runs_requested"],
        n_runs_completed=b["n_runs_completed"],
        seed_base=b["seed_base"],
        wall_time_ms=b["wall_time_ms"],
        totals={k: (int(v) if isinstance(v, (int, float)) and v is not None
                    and k not in ("avg_min_ttc", "avg_min_pet", "avg_cars",
                                  "max_closing_speed", "max_deceleration",
                                  "lowest_min_ttc", "lowest_min_pet") else v)
                for k, v in agg.items()},
        min_ttc_distribution=_distribution(ttcs, [0.0, 0.25, 0.5, 0.8, 1.0, 1.5]),
        runs_with_critical=runs_with_critical,
        runs_with_contact=runs_with_contact,
        fraction_runs_with_critical=round(
            runs_with_critical / max(agg.get("runs") or 1, 1), 5),
        summary=summary,
        config=json.loads(b["config_json"]) if b["config_json"] else {},
        space=json.loads(b["space_json"]) if b["space_json"] else {},
        pin=json.loads(b["pin_json"]) if b["pin_json"] else {},
    )


def _distribution(values: list[float], edges: list[float]) -> list[dict]:
    if not values:
        return []
    v = np.asarray(values, dtype=float)
    out = []
    bounds = list(edges) + [float("inf")]
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        n = int(((v >= lo) & (v < hi)).sum())
        out.append(dict(
            lo=lo, hi=None if hi == float("inf") else hi, count=n,
            fraction=round(n / len(v), 5),
            label=f"< {hi:g}s" if lo == 0 else (f">= {lo:g}s" if hi == float("inf")
                                                else f"{lo:g}-{hi:g}s"),
        ))
    return out


# ==========================================================================
# Spatial hotspots
# ==========================================================================
def hotspots(store, batch_id: str, track_id: str = "vale_park") -> dict:
    track = get_track(track_id)
    rows = store.q(
        """SELECT c.segment_index, c.location, c.turn_number, c.severity,
                  c.conflict_type, c.min_ttc, c.min_pet, c.closing_speed,
                  c.max_deceleration, c.evasive_action, c.collision, c.scsi,
                  c.archetype_a, c.archetype_b, c.weather, c.run_id,
                  r.traffic_density_measured, r.n_cars, r.dominant_error,
                  r.track_width_multiplier
           FROM conflicts c JOIN runs r ON r.id=c.run_id
           WHERE c.batch_id=?""",
        (batch_id,),
    )
    n_runs = store.q1("SELECT COUNT(*) c FROM runs WHERE batch_id=?",
                      (batch_id,))["c"] or 1

    by_seg: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_seg[r["segment_index"]].append(r)

    segments = []
    for seg in track.segments:
        items = by_seg.get(seg.index, [])
        n = len(items)
        ttc = np.array([i["min_ttc"] for i in items], dtype=float) if n else np.array([])
        pet = np.array([i["min_pet"] for i in items if i["min_pet"] is not None],
                       dtype=float)
        sev = Counter(i["severity"] for i in items)
        ctypes = Counter(i["conflict_type"] for i in items)
        weathers = Counter(i["weather"] for i in items)
        errors = Counter(i["dominant_error"] for i in items if i["dominant_error"])
        pairs = Counter(
            tuple(sorted([i["archetype_a"] or "?", i["archetype_b"] or "?"]))
            for i in items
        )
        segments.append(dict(
            segment_index=seg.index,
            name=seg.name,
            type=seg.type.value,
            turn_number=seg.turn_number,
            s_start=round(seg.s_start, 1),
            s_end=round(seg.s_end, 1),
            length=round(seg.length, 1),
            width=round(seg.width, 2),
            corner_radius=seg.corner_radius,
            target_speed_kph=round(seg.target_speed * 3.6, 1),
            runoff_width=seg.runoff_width,
            barrier_distance=seg.barrier_distance,
            overtaking_opportunity=seg.overtaking_opportunity,
            is_braking_zone=seg.is_braking_zone,
            # Counts are of simulated conflicts within this batch.
            conflicts=n,
            conflicts_per_run=round(n / n_runs, 5),
            conflicts_per_100m_per_run=round(
                n / n_runs / max(seg.length / 100.0, 1e-6), 6),
            critical=sev.get("CRITICAL", 0),
            incidents=sev.get("INCIDENT", 0),
            warnings=sev.get("WARNING", 0),
            collisions=int(sum(1 for i in items if i["collision"])),
            evasive=int(sum(1 for i in items if i["evasive_action"])),
            median_min_ttc=round(float(np.median(ttc)), 4) if n else None,
            p05_min_ttc=round(float(np.percentile(ttc, 5)), 4) if n else None,
            median_min_pet=round(float(np.median(pet)), 4) if len(pet) else None,
            median_closing_speed=round(float(np.median(
                [i["closing_speed"] for i in items])), 3) if n else None,
            mean_scsi=round(float(np.mean([i["scsi"] for i in items])), 5) if n else None,
            conflict_type_mix=dict(ctypes.most_common()),
            weather_mix=dict(weathers.most_common()),
            dominant_errors=dict(errors.most_common(4)),
            top_archetype_pairs=[
                dict(pair=list(p), count=c) for p, c in pairs.most_common(4)
            ],
            example_run_ids=[i["run_id"] for i in items[:6]],
        ))

    ranked = sorted(segments, key=lambda s: -s["conflicts"])
    corners_ranked = sorted(
        [s for s in segments if s["turn_number"] is not None],
        key=lambda s: -s["conflicts"],
    )
    return dict(
        batch_id=batch_id,
        track_id=track_id,
        n_runs=n_runs,
        total_conflicts=len(rows),
        segments=segments,
        ranked_segments=[s["segment_index"] for s in ranked],
        top_segments=ranked[:10],
        top_corners=corners_ranked[:8],
        note=(
            "Counts are numbers of conflicts detected in simulated trajectories "
            "within this batch, under the batch's assumptions. They are not "
            "real-world incident counts or probabilities."
        ),
    )


def hotspot_detail(store, batch_id: str, segment_index: int,
                   track_id: str = "vale_park") -> dict:
    """The "why is this location flagged?" payload for one segment."""
    hs = hotspots(store, batch_id, track_id)
    seg = next((s for s in hs["segments"] if s["segment_index"] == segment_index), None)
    if seg is None:
        return {}

    n_runs = hs["n_runs"]
    # Condition contrast: how much more often does this segment produce a conflict
    # under each condition band than the batch baseline for that band?
    weather_rows = store.q(
        """SELECT r.weather AS band, COUNT(DISTINCT r.id) AS runs,
                  SUM(CASE WHEN c.segment_index=? THEN 1 ELSE 0 END) AS seg_conflicts
           FROM runs r LEFT JOIN conflicts c ON c.run_id=r.id
           WHERE r.batch_id=? GROUP BY r.weather""",
        (segment_index, batch_id),
    )
    weather_contrast = [
        dict(band=w["band"], runs=w["runs"],
             conflicts=w["seg_conflicts"] or 0,
             conflicts_per_run=round((w["seg_conflicts"] or 0) / max(w["runs"], 1), 5))
        for w in weather_rows
    ]

    density_rows = store.q(
        """SELECT CASE WHEN r.traffic_density_measured<0.30 THEN 'LOW'
                       WHEN r.traffic_density_measured<0.55 THEN 'MEDIUM'
                       ELSE 'HIGH' END AS band,
                  COUNT(DISTINCT r.id) AS runs,
                  SUM(CASE WHEN c.segment_index=? THEN 1 ELSE 0 END) AS seg_conflicts
           FROM runs r LEFT JOIN conflicts c ON c.run_id=r.id
           WHERE r.batch_id=? GROUP BY band""",
        (segment_index, batch_id),
    )
    density_contrast = [
        dict(band=d["band"], runs=d["runs"], conflicts=d["seg_conflicts"] or 0,
             conflicts_per_run=round((d["seg_conflicts"] or 0) / max(d["runs"], 1), 5))
        for d in density_rows
    ]

    worst = store.q(
        """SELECT c.*, r.has_replay, r.weather AS run_weather,
                  r.traffic_density_measured, r.n_cars, r.dominant_error
           FROM conflicts c JOIN runs r ON r.id=c.run_id
           WHERE c.batch_id=? AND c.segment_index=?
           ORDER BY c.min_ttc ASC LIMIT 12""",
        (batch_id, segment_index),
    )
    return dict(
        segment=seg,
        n_runs=n_runs,
        weather_contrast=weather_contrast,
        density_contrast=density_contrast,
        worst_conflicts=worst,
        geometry_note=_geometry_note(seg),
        note=(
            "This segment is flagged because of the counts shown, which are "
            "simulated conflict counts under this batch's assumptions."
        ),
    )


def _geometry_note(seg: dict) -> str:
    bits = []
    if seg["corner_radius"]:
        bits.append(f"{seg['corner_radius']:.0f} m radius corner with a "
                    f"{seg['target_speed_kph']:.0f} km/h geometric speed ceiling")
    if seg["width"] <= 12.0:
        bits.append(f"{seg['width']:.1f} m wide, which leaves "
                    f"{seg['width'] - 2 * A.CAR_WIDTH:.1f} m of slack for two cars "
                    f"abreast")
    if seg["runoff_width"] <= 8.0:
        bits.append(f"only {seg['runoff_width']:.0f} m of runoff")
    if seg["is_braking_zone"]:
        bits.append(f"a braking zone rated {seg['overtaking_opportunity']:.2f} for "
                    f"overtaking")
    return "; ".join(bits) if bits else "No unusual geometric characteristics."


# ==========================================================================
# Sensitivity
# ==========================================================================
SENSITIVITY_PARAMS = [
    ("traffic_density_measured", "Traffic density (measured)", 6),
    ("n_cars", "Number of cars", None),
    ("grip", "Track grip", 6),
    ("visibility", "Visibility", 6),
    ("track_width_multiplier", "Track width multiplier", 5),
    ("error_rate_multiplier", "Human-error rate multiplier", 5),
    ("pace_spread", "Pace spread", 5),
    ("grid_spread", "Starting-gap spread", 5),
    ("tyre_condition", "Tyre condition", 5),
    ("spray", "Spray", 4),
]

# Agent-parameter sensitivities are computed from the field composition rather
# than from a single scalar, because a field is a mixture of archetypes.
FIELD_TRAIT_PARAMS = [
    ("aggression", "Mean field aggression"),
    ("risk_tolerance", "Mean field risk tolerance"),
    ("overtake_willingness", "Mean field overtake willingness"),
    ("defensive_tendency", "Mean field defensive tendency"),
    ("reaction_time", "Mean field reaction time"),
    ("late_braking_tendency", "Mean field late-braking tendency"),
]

OUTCOMES = [
    ("n_critical", "Critical conflicts per run"),
    ("n_conflicts", "Conflicts per run"),
    ("n_collisions", "Collisions per run"),
    ("n_near_misses", "Near misses per run"),
    ("n_off_track", "Off-track excursions per run"),
    ("min_ttc", "Minimum TTC (s)"),
]


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Rank correlation, implemented directly to avoid a SciPy dependency."""
    if len(x) < 3:
        return 0.0
    def rank(a):
        order = np.argsort(a, kind="mergesort")
        r = np.empty(len(a), dtype=float)
        r[order] = np.arange(len(a), dtype=float)
        # average ties
        a_sorted = a[order]
        i = 0
        while i < len(a):
            j = i
            while j + 1 < len(a) and a_sorted[j + 1] == a_sorted[i]:
                j += 1
            if j > i:
                r[order[i:j + 1]] = np.mean(r[order[i:j + 1]])
            i = j + 1
        return r
    rx, ry = rank(np.asarray(x, float)), rank(np.asarray(y, float))
    sx, sy = rx.std(), ry.std()
    if sx < 1e-12 or sy < 1e-12:
        return 0.0
    return float(np.mean((rx - rx.mean()) * (ry - ry.mean())) / (sx * sy))


def sensitivity(store, batch_id: str) -> dict:
    rows = store.q(
        """SELECT id, n_cars, grip, visibility, spray, tyre_condition,
                  traffic_density_measured, traffic_density_requested,
                  grid_spread, pace_spread, track_width_multiplier,
                  error_rate_multiplier, weather, field_mix_json,
                  n_conflicts, n_critical, n_collisions, n_near_misses,
                  n_off_track, n_spins, n_evasive, min_ttc, min_pet, peak_scsi
           FROM runs WHERE batch_id=?""",
        (batch_id,),
    )
    if len(rows) < 10:
        return dict(batch_id=batch_id, n_runs=len(rows), parameters=[],
                    note="Not enough runs for a sensitivity analysis.")

    # Derive mean field traits from each run's archetype composition.
    for r in rows:
        mix = json.loads(r["field_mix_json"] or "[]")
        if mix:
            for trait, _ in FIELD_TRAIT_PARAMS:
                r[f"trait_{trait}"] = float(np.mean(
                    [ARCHETYPES[m][trait] for m in mix if m in ARCHETYPES]
                ))
        else:
            for trait, _ in FIELD_TRAIT_PARAMS:
                r[f"trait_{trait}"] = None

    params = []
    for key, label, nbins in SENSITIVITY_PARAMS:
        params.append(_param_profile(rows, key, label, nbins))
    for trait, label in FIELD_TRAIT_PARAMS:
        params.append(_param_profile(rows, f"trait_{trait}", label, 5))

    params = [p for p in params if p is not None]
    # Rank by |rho| against critical conflicts, the headline outcome.
    params.sort(key=lambda p: -abs(p["correlations"].get("n_critical", 0.0)))

    return dict(
        batch_id=batch_id,
        n_runs=len(rows),
        parameters=params,
        outcomes=[dict(key=k, label=l) for k, l in OUTCOMES],
        interactions=_two_way(rows),
        method_note=(
            "Bands are equal-count quantiles of the sampled parameter. rho is a "
            "Spearman rank correlation against the per-run outcome. Because the "
            "sampler draws these parameters independently, the associations are "
            "not confounded with one another inside this model. They describe the "
            "model's behaviour, not racing."
        ),
    )


def _param_profile(rows: list[dict], key: str, label: str,
                   nbins: int | None) -> dict | None:
    vals = np.array([r[key] for r in rows if r.get(key) is not None], dtype=float)
    if len(vals) < 10 or float(np.nanstd(vals)) < 1e-9:
        return None
    subset = [r for r in rows if r.get(key) is not None]

    if nbins is None:
        uniq = sorted({float(r[key]) for r in subset})
        bands = [(u, u) for u in uniq]
    else:
        qs = np.linspace(0, 100, nbins + 1)
        edges = np.unique(np.percentile(vals, qs))
        if len(edges) < 3:
            return None
        bands = list(zip(edges[:-1], edges[1:]))

    out_bands = []
    for lo, hi in bands:
        if lo == hi:
            sel = [r for r in subset if float(r[key]) == lo]
        else:
            # The top band is closed on the right so the maximum value is not lost.
            is_last = hi == bands[-1][1]
            if is_last:
                sel = [r for r in subset if lo <= float(r[key]) <= hi]
            else:
                sel = [r for r in subset if lo <= float(r[key]) < hi]
        if not sel:
            continue
        band = dict(
            lo=round(float(lo), 4), hi=round(float(hi), 4), runs=len(sel),
            mid=round(float((lo + hi) / 2), 4),
        )
        for okey, _ in OUTCOMES:
            v = [r[okey] for r in sel if r[okey] is not None]
            band[okey] = round(float(np.mean(v)), 5) if v else None
        band["fraction_runs_with_critical"] = round(
            float(np.mean([1.0 if (r["n_critical"] or 0) > 0 else 0.0 for r in sel])), 5)
        out_bands.append(band)

    correlations = {}
    for okey, _ in OUTCOMES:
        pair = [(float(r[key]), float(r[okey])) for r in subset
                if r.get(key) is not None and r.get(okey) is not None]
        if len(pair) >= 10:
            xs, ys = zip(*pair)
            correlations[okey] = round(_spearman(np.array(xs), np.array(ys)), 4)

    return dict(key=key, label=label, bands=out_bands, correlations=correlations,
                n=len(subset),
                range=[round(float(vals.min()), 4), round(float(vals.max()), 4)])


def _two_way(rows: list[dict]) -> list[dict]:
    """Selected parameter pairs against critical-conflict frequency."""
    pairs = [
        ("traffic_density_measured", "grip", "Traffic density x grip"),
        ("traffic_density_measured", "trait_aggression",
         "Traffic density x field aggression"),
        ("grip", "trait_late_braking_tendency", "Grip x late-braking tendency"),
        ("track_width_multiplier", "traffic_density_measured",
         "Track width x traffic density"),
    ]
    out = []
    for ka, kb, label in pairs:
        sub = [r for r in rows if r.get(ka) is not None and r.get(kb) is not None]
        if len(sub) < 40:
            continue
        a = np.array([float(r[ka]) for r in sub])
        b = np.array([float(r[kb]) for r in sub])
        ea = np.unique(np.percentile(a, [0, 33, 66, 100]))
        eb = np.unique(np.percentile(b, [0, 33, 66, 100]))
        if len(ea) < 3 or len(eb) < 3:
            continue
        cells = []
        for i in range(len(ea) - 1):
            for j in range(len(eb) - 1):
                last_i = i == len(ea) - 2
                last_j = j == len(eb) - 2
                m = ((a >= ea[i]) & ((a <= ea[i + 1]) if last_i else (a < ea[i + 1]))
                     & (b >= eb[j]) & ((b <= eb[j + 1]) if last_j else (b < eb[j + 1])))
                sel = [s for s, keep in zip(sub, m) if keep]
                if not sel:
                    continue
                cells.append(dict(
                    i=i, j=j,
                    a_lo=round(float(ea[i]), 4), a_hi=round(float(ea[i + 1]), 4),
                    b_lo=round(float(eb[j]), 4), b_hi=round(float(eb[j + 1]), 4),
                    runs=len(sel),
                    critical_per_run=round(float(np.mean(
                        [s["n_critical"] or 0 for s in sel])), 4),
                    conflicts_per_run=round(float(np.mean(
                        [s["n_conflicts"] or 0 for s in sel])), 4),
                    collisions_per_run=round(float(np.mean(
                        [s["n_collisions"] or 0 for s in sel])), 4),
                ))
        out.append(dict(label=label, a_key=ka, b_key=kb, cells=cells,
                        a_edges=[round(float(x), 4) for x in ea],
                        b_edges=[round(float(x), 4) for x in eb]))
    return out


# ==========================================================================
# Driver interaction matrix
# ==========================================================================
def interaction_matrix(store, batch_id: str) -> dict:
    """Archetype x archetype conflict rates, normalised by co-presence.

    Raw conflict counts would mostly reflect how often each archetype happened to
    be sampled into a field. The denominator here is the number of runs in which
    both archetypes were present, so a cell reads as "conflicts per run in which
    these two behaviours were both on track".
    """
    runs = store.q(
        "SELECT id, field_mix_json, n_cars FROM runs WHERE batch_id=?", (batch_id,))
    archetypes = list(ARCHETYPES.keys())
    idx = {a: i for i, a in enumerate(archetypes)}
    n = len(archetypes)

    co_runs = np.zeros((n, n), dtype=float)
    present_runs = np.zeros(n, dtype=float)
    for r in runs:
        mix = set(json.loads(r["field_mix_json"] or "[]"))
        present = [a for a in mix if a in idx]
        for a in present:
            present_runs[idx[a]] += 1
        for a in present:
            for b in present:
                co_runs[idx[a], idx[b]] += 1

    conflicts = store.q(
        """SELECT archetype_a, archetype_b, severity, min_ttc, min_pet,
                  closing_speed, collision, evasive_action, scsi, conflict_type,
                  weather, run_id
           FROM conflicts WHERE batch_id=?""",
        (batch_id,),
    )
    counts = np.zeros((n, n), dtype=float)
    critical = np.zeros((n, n), dtype=float)
    collisions = np.zeros((n, n), dtype=float)
    ttc_acc: dict[tuple[int, int], list[float]] = defaultdict(list)
    ctx: dict[tuple[int, int], Counter] = defaultdict(Counter)
    weather_ctx: dict[tuple[int, int], Counter] = defaultdict(Counter)

    for c in conflicts:
        a, b = c["archetype_a"], c["archetype_b"]
        if a not in idx or b not in idx:
            continue
        i, j = idx[a], idx[b]
        for (p, q) in ((i, j), (j, i)):
            counts[p, q] += 1
            if c["severity"] == "CRITICAL":
                critical[p, q] += 1
            if c["collision"]:
                collisions[p, q] += 1
            if c["min_ttc"] is not None:
                ttc_acc[(p, q)].append(c["min_ttc"])
            ctx[(p, q)][c["conflict_type"]] += 1
            weather_ctx[(p, q)][c["weather"]] += 1

    cells = []
    for i, a in enumerate(archetypes):
        for j, b in enumerate(archetypes):
            denom = co_runs[i, j]
            tt = ttc_acc.get((i, j), [])
            cells.append(dict(
                a=a, b=b, i=i, j=j,
                co_present_runs=int(denom),
                conflicts=int(counts[i, j]),
                critical=int(critical[i, j]),
                collisions=int(collisions[i, j]),
                conflicts_per_co_present_run=round(counts[i, j] / denom, 5)
                if denom else None,
                critical_per_co_present_run=round(critical[i, j] / denom, 5)
                if denom else None,
                median_min_ttc=round(float(np.median(tt)), 4) if tt else None,
                dominant_conflict_type=(ctx[(i, j)].most_common(1)[0][0]
                                        if ctx.get((i, j)) else None),
                conflict_type_mix=dict(ctx[(i, j)].most_common(3)),
                weather_mix=dict(weather_ctx[(i, j)].most_common(4)),
                sparse=bool(denom < 15),
            ))

    return dict(
        batch_id=batch_id,
        archetypes=[dict(id=a, label=ARCHETYPES[a]["label"],
                         note=ARCHETYPES[a]["note"],
                         present_in_runs=int(present_runs[i]))
                    for i, a in enumerate(archetypes)],
        cells=cells,
        n_runs=len(runs),
        note=(
            "Cells are conflicts per run in which both behavioural profiles were "
            "present, so they are not distorted by how often each profile was "
            "sampled. Cells marked sparse rest on fewer than 15 co-present runs. "
            "No profile is 'unsafe': these are simulation parameters, and a higher "
            "cell means these two parameterisations produced more critical "
            "interactions under this model's assumptions."
        ),
    )


# ==========================================================================
# Environment analysis
# ==========================================================================
def environment_analysis(store, batch_id: str) -> dict:
    by_weather = store.q(
        """SELECT weather,
                  COUNT(*) runs, AVG(grip) grip, AVG(visibility) visibility,
                  AVG(spray) spray,
                  AVG(n_conflicts) conflicts_per_run,
                  AVG(n_critical) critical_per_run,
                  AVG(n_near_misses) near_misses_per_run,
                  AVG(n_collisions) collisions_per_run,
                  AVG(n_light_contacts) light_contacts_per_run,
                  AVG(n_off_track) off_track_per_run,
                  AVG(n_spins) spins_per_run,
                  AVG(n_evasive) evasive_per_run,
                  AVG(n_overtake_attempts) overtake_attempts_per_run,
                  AVG(n_overtakes_completed) overtakes_completed_per_run,
                  AVG(min_ttc) mean_min_ttc, MIN(min_ttc) lowest_min_ttc,
                  AVG(min_pet) mean_min_pet,
                  AVG(max_deceleration) mean_max_decel,
                  AVG(max_closing_speed) mean_max_closing
           FROM runs WHERE batch_id=? GROUP BY weather""",
        (batch_id,),
    )
    order = {"DRY": 0, "DAMP": 1, "WET": 2, "HEAVY_RAIN": 3}
    by_weather.sort(key=lambda r: order.get(r["weather"], 9))
    for r in by_weather:
        for k, v in list(r.items()):
            if isinstance(v, float):
                r[k] = round(v, 5)

    ctype = store.q(
        """SELECT weather, conflict_type, COUNT(*) n, AVG(min_ttc) mean_ttc
           FROM conflicts WHERE batch_id=? GROUP BY weather, conflict_type""",
        (batch_id,),
    )
    seg = store.q(
        """SELECT weather, location, turn_number, COUNT(*) n
           FROM conflicts WHERE batch_id=? GROUP BY weather, segment_index
           ORDER BY n DESC""",
        (batch_id,),
    )
    top_by_weather: dict[str, list[dict]] = defaultdict(list)
    for r in seg:
        if len(top_by_weather[r["weather"]]) < 5:
            top_by_weather[r["weather"]].append(
                dict(location=r["location"], turn_number=r["turn_number"], n=r["n"]))

    return dict(
        batch_id=batch_id,
        by_weather=by_weather,
        conflict_types_by_weather=ctype,
        top_locations_by_weather=dict(top_by_weather),
        presets=A.WEATHER_PRESETS,
        note=(
            "All rates are per simulated run of the configured window length. "
            "Weather presets are modelling assumptions, listed on the Model "
            "Assumptions screen."
        ),
    )


# ==========================================================================
# Conflict-type and severity breakdowns
# ==========================================================================
def conflict_breakdown(store, batch_id: str) -> dict:
    by_type = store.q(
        """SELECT conflict_type, severity, COUNT(*) n, AVG(min_ttc) mean_ttc,
                  AVG(min_pet) mean_pet, AVG(closing_speed) mean_closing,
                  AVG(max_deceleration) mean_decel, SUM(collision) collisions,
                  SUM(evasive_action) evasive
           FROM conflicts WHERE batch_id=? GROUP BY conflict_type, severity""",
        (batch_id,),
    )
    decisions = store.q(
        """SELECT a_decision, b_decision, COUNT(*) n, AVG(min_ttc) mean_ttc
           FROM conflicts WHERE batch_id=?
           GROUP BY a_decision, b_decision ORDER BY n DESC LIMIT 20""",
        (batch_id,),
    )
    errors = store.q(
        """SELECT dominant_error, COUNT(*) runs, AVG(n_critical) critical_per_run,
                  AVG(min_ttc) mean_min_ttc, AVG(n_collisions) collisions_per_run
           FROM runs WHERE batch_id=? GROUP BY dominant_error
           ORDER BY runs DESC""",
        (batch_id,),
    )
    for rows in (by_type, decisions, errors):
        for r in rows:
            for k, v in list(r.items()):
                if isinstance(v, float):
                    r[k] = round(v, 5)
    return dict(batch_id=batch_id, by_type_and_severity=by_type,
                decision_pairs=decisions, by_dominant_error=errors)


def compute_and_store_all(store, batch_id: str, track_id: str = "vale_park") -> dict:
    """Run every analysis and cache the results for the API."""
    out = {}
    for kind, fn in (
        ("overview", lambda: overview(store, batch_id)),
        ("hotspots", lambda: hotspots(store, batch_id, track_id)),
        ("sensitivity", lambda: sensitivity(store, batch_id)),
        ("interaction_matrix", lambda: interaction_matrix(store, batch_id)),
        ("environment", lambda: environment_analysis(store, batch_id)),
        ("conflict_breakdown", lambda: conflict_breakdown(store, batch_id)),
    ):
        payload = fn()
        store.save_analysis(batch_id, kind, payload)
        out[kind] = payload
    return out
