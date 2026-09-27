"""The experiment suite, and paired-seed what-if comparison.

Two kinds of comparison live here.

**Controlled experiments** hold the whole scenario space fixed except one
dimension, which is pinned to each of several values. Each arm gets its own batch
with the *same* seed base, so arm-to-arm differences come from the pinned
dimension rather than from different random draws.

**Interventions** go further: the baseline and the intervention run the identical
scenario objects, seed included, with only the named parameters changed. This is
the strongest comparison available here, because the two runs share their entire
random history — the same grid order, the same error draws, the same weather
jitter. Any difference in outcome is attributable to the change.

The language used to report both is constrained on purpose. An intervention that
reduces critical conflicts has reduced *simulated* critical conflicts under *these*
assumptions. It has not been shown to improve safety.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

import numpy as np

from .batch import run_monte_carlo, run_scenarios
from .scenario import ScenarioSpace, sample, with_intervention

# --------------------------------------------------------------------------
# Experiment definitions (numbered as in the project plan)
# --------------------------------------------------------------------------
EXPERIMENTS: dict[str, dict] = {
    "weather": dict(
        number=1, name="Dry vs wet",
        question="How do outcomes differ across the four weather presets?",
        dimension="weather",
        arms=[dict(label="Dry", pin=dict(weather="DRY")),
              dict(label="Damp", pin=dict(weather="DAMP")),
              dict(label="Wet", pin=dict(weather="WET")),
              dict(label="Heavy rain", pin=dict(weather="HEAVY_RAIN"))],
    ),
    "field_size": dict(
        number=2, name="Field size",
        question="Does the number of cars on track change conflict frequency?",
        dimension="n_cars",
        arms=[dict(label="5 cars", pin=dict(n_cars=5)),
              dict(label="11 cars", pin=dict(n_cars=11)),
              dict(label="22 cars", pin=dict(n_cars=22))],
    ),
    "aggression": dict(
        number=3, name="Low vs high aggression",
        question="Does a more aggressive field produce more critical conflicts?",
        dimension="field_mix",
        arms=[
            dict(label="Low aggression",
                 pin=dict(field_mix=None, _mix=["CONSERVATIVE", "SMOOTH",
                                                "HIGH_CONSISTENCY"])),
            dict(label="Mixed",
                 pin=dict(field_mix=None, _mix=None)),
            dict(label="High aggression",
                 pin=dict(field_mix=None, _mix=["AGGRESSIVE_OVERTAKER", "HIGH_RISK",
                                                "LATE_BRAKER"])),
        ],
    ),
    "traffic": dict(
        number=4, name="Low vs high traffic density",
        question="How does traffic density affect conflict frequency?",
        dimension="traffic_density",
        arms=[dict(label="Low (0.2)", pin=dict(traffic_density=0.2)),
              dict(label="Medium (0.5)", pin=dict(traffic_density=0.5)),
              dict(label="High (0.8)", pin=dict(traffic_density=0.8)),
              dict(label="Very high (0.95)", pin=dict(traffic_density=0.95))],
    ),
    "reaction": dict(
        number=5, name="Normal vs delayed reaction",
        question="What does raising the delayed-reaction error rate do?",
        dimension="error_rate_multiplier",
        arms=[dict(label="Low error rate", pin=dict(error_rate_multiplier=0.4)),
              dict(label="Baseline", pin=dict(error_rate_multiplier=1.0)),
              dict(label="Elevated", pin=dict(error_rate_multiplier=1.8))],
    ),
    "track_width": dict(
        number=6, name="Wide vs narrow track",
        question="Does scaling every track width change conflict outcomes?",
        dimension="track_width_multiplier",
        arms=[dict(label="Narrow (x0.85)", pin=dict(track_width_multiplier=0.85)),
              dict(label="Baseline (x1.0)", pin=dict(track_width_multiplier=1.0)),
              dict(label="Wide (x1.15)", pin=dict(track_width_multiplier=1.15))],
    ),
    "grip": dict(
        number=7, name="Normal vs reduced grip",
        question="Isolating grip from the rest of the weather preset.",
        dimension="grip_delta",
        arms=[dict(label="Grip +0.04", pin=dict(weather="DRY", grip_delta=0.04)),
              dict(label="Baseline", pin=dict(weather="DRY", grip_delta=0.0)),
              dict(label="Grip -0.10", pin=dict(weather="DRY", grip_delta=-0.10)),
              dict(label="Grip -0.20", pin=dict(weather="DRY", grip_delta=-0.20))],
    ),
}

OUTCOME_KEYS = [
    ("n_conflicts", "Conflicts per run"),
    ("n_critical", "Critical conflicts per run"),
    ("n_near_misses", "Near misses per run"),
    ("n_collisions", "Collisions per run"),
    ("n_light_contacts", "Light contacts per run"),
    ("n_off_track", "Off-track excursions per run"),
    ("n_spins", "Spins per run"),
    ("n_evasive", "Evasive manoeuvres per run"),
    ("n_overtake_attempts", "Overtake attempts per run"),
    ("n_overtakes_completed", "Overtakes completed per run"),
    ("min_ttc", "Minimum TTC (s)"),
    ("min_pet", "Minimum PET (s)"),
    ("max_closing_speed", "Peak closing speed (m/s)"),
    ("max_deceleration", "Peak deceleration (m/s^2)"),
]


def _arm_stats(store, batch_id: str) -> dict:
    rows = store.q(
        "SELECT " + ",".join(k for k, _ in OUTCOME_KEYS) +
        " FROM runs WHERE batch_id=?", (batch_id,))
    out: dict[str, Any] = dict(n_runs=len(rows))
    for key, _ in OUTCOME_KEYS:
        vals = [r[key] for r in rows if r[key] is not None]
        out[key] = dict(
            mean=round(float(np.mean(vals)), 5) if vals else None,
            median=round(float(np.median(vals)), 5) if vals else None,
            p05=round(float(np.percentile(vals, 5)), 5) if vals else None,
            min=round(float(np.min(vals)), 5) if vals else None,
            max=round(float(np.max(vals)), 5) if vals else None,
            n=len(vals),
            # Standard error of the mean, so a reader can see whether an
            # arm-to-arm difference is larger than the noise.
            sem=round(float(np.std(vals, ddof=1) / np.sqrt(len(vals))), 5)
            if len(vals) > 1 else None,
        )
    frac = store.q1(
        "SELECT AVG(CASE WHEN n_critical>0 THEN 1.0 ELSE 0.0 END) f, "
        "AVG(CASE WHEN n_collisions>0 THEN 1.0 ELSE 0.0 END) fc "
        "FROM runs WHERE batch_id=?", (batch_id,))
    out["fraction_runs_with_critical"] = round(frac["f"] or 0.0, 5)
    out["fraction_runs_with_collision"] = round(frac["fc"] or 0.0, 5)
    return out


def run_experiment(
    store, key: str, *, runs_per_arm: int = 150, seed_base: int = 900_000,
    workers: int | None = None, progress: Callable | None = None,
) -> dict:
    """Run one controlled experiment: one batch per arm, shared seed base."""
    if key not in EXPERIMENTS:
        raise KeyError(f"unknown experiment '{key}'")
    spec = EXPERIMENTS[key]
    exp_id = uuid.uuid4().hex[:12]
    arms_out = []
    batch_ids = []

    for i, arm in enumerate(spec["arms"]):
        pin = {k: v for k, v in arm["pin"].items()
               if not k.startswith("_") and v is not None}
        space = ScenarioSpace()
        mix = arm["pin"].get("_mix")
        if mix is not None:
            space.archetypes = list(mix)
            space.archetype_concentration = 6.0  # near-even mix of the chosen set
        # Every arm shares the seed base, so arm i run j and arm k run j see the
        # same underlying random draws wherever the pinned dimension allows.
        bid = run_monte_carlo(
            store, runs_per_arm, space, pin=pin, seed_base=seed_base,
            label=f"{spec['name']}: {arm['label']}", mode="experiment",
            workers=workers, replay_budget=25, progress=progress,
        )
        batch_ids.append(bid)
        arms_out.append(dict(
            label=arm["label"], batch_id=bid, pin=pin,
            archetypes=mix, stats=_arm_stats(store, bid),
        ))

    results = dict(
        experiment=key, number=spec["number"], name=spec["name"],
        question=spec["question"], dimension=spec["dimension"],
        runs_per_arm=runs_per_arm, seed_base=seed_base,
        arms=arms_out, outcomes=[dict(key=k, label=l) for k, l in OUTCOME_KEYS],
        deltas=_arm_deltas(arms_out),
        note=(
            "Arms share a seed base and differ only in the pinned dimension. "
            "Differences are differences in simulated outcomes under this model's "
            "assumptions, not measured safety effects."
        ),
    )
    store.save_experiment(exp_id, spec["name"], "controlled",
                          dict(key=key, runs_per_arm=runs_per_arm,
                               seed_base=seed_base), results, batch_ids)
    results["id"] = exp_id
    return results


def _arm_deltas(arms: list[dict]) -> list[dict]:
    """Each arm relative to the first, with the noise floor alongside."""
    if not arms:
        return []
    base = arms[0]
    out = []
    for arm in arms[1:]:
        row = dict(label=arm["label"], baseline_label=base["label"], metrics={})
        for key, label in OUTCOME_KEYS:
            b = base["stats"][key]["mean"]
            a = arm["stats"][key]["mean"]
            if b is None or a is None:
                continue
            sem_b = base["stats"][key].get("sem") or 0.0
            sem_a = arm["stats"][key].get("sem") or 0.0
            pooled = float(np.hypot(sem_a, sem_b))
            row["metrics"][key] = dict(
                label=label, baseline=b, value=a, absolute=round(a - b, 5),
                relative=round((a - b) / b, 5) if b else None,
                pooled_sem=round(pooled, 5),
                exceeds_noise=bool(abs(a - b) > 2 * pooled) if pooled else None,
            )
        out.append(row)
    return out


# --------------------------------------------------------------------------
# Paired-seed intervention (the What-If Lab)
# --------------------------------------------------------------------------
INTERVENTION_PRESETS = [
    dict(id="conservative_overtaking", name="More conservative overtaking threshold",
         description="Raises the drive required before an agent commits to a pass.",
         changes=dict(overtake_threshold_delta=0.15)),
    dict(id="aggressive_overtaking", name="More aggressive overtaking threshold",
         description="Lowers the drive required to commit.",
         changes=dict(overtake_threshold_delta=-0.15)),
    dict(id="larger_following_gap", name="Larger target following gap",
         description="Increases every agent's target following time gap by 0.15 s.",
         changes=dict(following_gap_delta=0.15)),
    dict(id="wider_track", name="Wider track (+15%)",
         description="Scales every segment width by 1.15.",
         changes=dict(track_width_multiplier=1.15)),
    dict(id="narrower_track", name="Narrower track (-15%)",
         description="Scales every segment width by 0.85.",
         changes=dict(track_width_multiplier=0.85)),
    dict(id="fewer_cars", name="Reduced field size (16 cars)",
         description="Runs the same conditions with a smaller field.",
         changes=dict(n_cars=16)),
    dict(id="lower_error_rate", name="Halved human-error rates",
         description="Scales every error rate by 0.5.",
         changes=dict(error_rate_multiplier=0.5)),
    dict(id="lower_traffic", name="Lower traffic density",
         description="Sets requested traffic density to 0.3.",
         changes=dict(traffic_density=0.3)),
]


def run_intervention(
    store, *, n_runs: int = 200, changes: dict[str, Any],
    space: ScenarioSpace | None = None, pin: dict | None = None,
    seed_base: int = 555_000, label: str = "", workers: int | None = None,
    progress: Callable | None = None,
) -> dict:
    """Run a baseline and an intervention over identical scenarios.

    The intervention scenarios are constructed by copying each baseline scenario
    and applying ``changes`` — the seed is carried over untouched.
    """
    space = space or ScenarioSpace()
    baseline_scenarios = [
        sample(seed_base + i, space, pin=pin, origin="manual")
        for i in range(n_runs)
    ]
    intervention_scenarios = [
        with_intervention(sc, changes, label=label or "intervention")
        for sc in baseline_scenarios
    ]

    base_bid = run_scenarios(
        store, baseline_scenarios, label=f"Baseline for: {label or 'intervention'}",
        mode="intervention", workers=workers, replay_budget=40, progress=progress)
    int_bid = run_scenarios(
        store, intervention_scenarios,
        label=f"Intervention: {label or 'intervention'}",
        mode="intervention", workers=workers, replay_budget=40, progress=progress)

    base_stats = _arm_stats(store, base_bid)
    int_stats = _arm_stats(store, int_bid)

    # Paired differences, run by run, matched on seed.
    base_rows = {r["seed"]: r for r in store.q(
        "SELECT seed," + ",".join(k for k, _ in OUTCOME_KEYS) +
        " FROM runs WHERE batch_id=?", (base_bid,))}
    int_rows = {r["seed"]: r for r in store.q(
        "SELECT seed," + ",".join(k for k, _ in OUTCOME_KEYS) +
        " FROM runs WHERE batch_id=?", (int_bid,))}
    paired: dict[str, Any] = {}
    common = sorted(set(base_rows) & set(int_rows))
    for key, label_ in OUTCOME_KEYS:
        diffs = [
            (int_rows[s][key] - base_rows[s][key])
            for s in common
            if int_rows[s][key] is not None and base_rows[s][key] is not None
        ]
        if not diffs:
            continue
        arr = np.array(diffs, dtype=float)
        sem = float(arr.std(ddof=1) / np.sqrt(len(arr))) if len(arr) > 1 else 0.0
        paired[key] = dict(
            label=label_, n_pairs=len(arr),
            mean_difference=round(float(arr.mean()), 5),
            sem=round(sem, 5),
            # A crude effect indicator: is the paired mean difference more than
            # two standard errors from zero?
            exceeds_noise=bool(abs(arr.mean()) > 2 * sem) if sem > 0 else None,
            improved_pairs=int((arr < 0).sum()),
            worsened_pairs=int((arr > 0).sum()),
            unchanged_pairs=int((arr == 0).sum()),
        )

    crit = paired.get("n_critical", {})
    base_crit = base_stats["n_critical"]["mean"] or 0.0
    rel = (crit.get("mean_difference", 0.0) / base_crit) if base_crit else None

    exp_id = uuid.uuid4().hex[:12]
    results = dict(
        baseline_batch_id=base_bid,
        intervention_batch_id=int_bid,
        changes=changes,
        n_runs=n_runs,
        n_pairs=len(common),
        seed_base=seed_base,
        baseline=base_stats,
        intervention=int_stats,
        paired=paired,
        outcomes=[dict(key=k, label=l) for k, l in OUTCOME_KEYS],
        headline=(
            f"In this simulation experiment, the intervention changed critical "
            f"conflict frequency by "
            f"{crit.get('mean_difference', 0.0):+.3f} per run"
            + (f" ({rel * 100:+.1f}%)" if rel is not None else "")
            + f", over {len(common)} seed-matched pairs, under the specified "
              f"assumptions."
        ),
        note=(
            "Baseline and intervention runs are matched on seed, so each pair "
            "shares its entire random history and differs only in the changed "
            "parameters. This is a statement about simulated conflict frequency "
            "under this model's assumptions. It is NOT a measured real-world "
            "safety improvement."
        ),
    )
    store.save_experiment(exp_id, label or "Intervention", "intervention",
                          dict(changes=changes, n_runs=n_runs, seed_base=seed_base,
                               pin=pin or {}),
                          results, [base_bid, int_bid])
    results["id"] = exp_id
    return results
