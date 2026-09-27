"""Command-line entry points.

Everything the API can start can also be run from here, which is how the demo
database is seeded and how the engine is exercised without a browser.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import assumptions as A
from .analysis import compute_and_store_all
from .batch import default_workers, run_monte_carlo
from .circuits import list_tracks
from .discovery import compare_search_strategies, discover_patterns, guided_search
from .experiments import EXPERIMENTS, run_experiment, run_intervention
from .report import generate_report
from .scenario import ScenarioSpace
from .storage import DEFAULT_DB, Store


def _progress(p: dict):
    phase = p.get("phase", "simulating")
    done, total = p.get("completed", 0), p.get("total", 0)
    if not total:
        return
    pct = 100.0 * done / total
    extra = ""
    if "critical" in p:
        extra = (f"  conflicts={p.get('conflicts', 0)} "
                 f"critical={p.get('critical', 0)} "
                 f"collisions={p.get('collisions', 0)}")
    gen = f" gen {p['generation']}" if p.get("generation") else ""
    sys.stdout.write(f"\r  [{phase}{gen}] {done}/{total} ({pct:5.1f}%){extra}   ")
    sys.stdout.flush()


def cmd_batch(args):
    store = Store(args.db)
    space = ScenarioSpace()
    if args.weather:
        space.weathers = args.weather
    if args.cars:
        space.n_cars_choices = args.cars
    t0 = time.time()
    print(f"Monte Carlo: {args.n} runs on {args.workers or default_workers()} workers")
    bid = run_monte_carlo(store, args.n, space, seed_base=args.seed,
                         label=args.label, workers=args.workers,
                         replay_budget=args.replays, progress=_progress)
    print(f"\n  batch {bid} in {time.time() - t0:.1f}s")
    print("  analysing...")
    compute_and_store_all(store, bid)
    pats = discover_patterns(store, bid, top_n=20)
    print(f"  {len(pats)} recurring patterns")
    if pats:
        for p in pats[:5]:
            print(f"    #{p['rank']} {p['location']} / {p['weather']} / "
                  f"{p['traffic_band']} / {p['conflict_type']}: "
                  f"{p['occurrences']}/{p['runs_evaluated']} runs, "
                  f"median min TTC {p['median_min_ttc']:.2f}s")
    print(f"  batch_id: {bid}")
    return bid


def cmd_guided(args):
    store = Store(args.db)
    seed_batch = args.seed_batch
    if seed_batch is None:
        b = store.latest_batch("monte_carlo")
        seed_batch = b["id"] if b else None
        if seed_batch:
            print(f"  seeding elites from latest Monte Carlo batch {seed_batch}")
    out = guided_search(store, generations=args.generations,
                        population=args.population, elite_size=args.elites,
                        seed_batch_id=seed_batch, seed_base=args.seed,
                        label=args.label, progress=_progress)
    bid = out["batch_id"]
    print(f"\n  batch {bid}")
    compute_and_store_all(store, bid)
    pats = discover_patterns(store, bid, top_n=20)
    h = out["summary"]["history"]
    print(f"  objective: generation 1 mean {h[0]['mean_objective']:.4f} -> "
          f"generation {len(h)} mean {h[-1]['mean_objective']:.4f} "
          f"(best {out['summary']['best_objective']:.4f})")
    print(f"  {len(pats)} recurring patterns")
    if seed_batch:
        cmp = compare_search_strategies(store, seed_batch, bid)
        d = cmp.get("delta", {})
        print(f"  vs random: critical/run ratio "
              f"{d.get('critical_per_run_ratio')}, mean objective ratio "
              f"{d.get('mean_objective_ratio')}")
    return bid


def cmd_experiment(args):
    store = Store(args.db)
    keys = [args.key] if args.key != "all" else list(EXPERIMENTS)
    for k in keys:
        print(f"Experiment: {EXPERIMENTS[k]['name']}")
        out = run_experiment(store, k, runs_per_arm=args.runs, progress=_progress)
        print()
        for arm in out["arms"]:
            s = arm["stats"]
            print(f"  {arm['label']:<18} conflicts/run "
                  f"{s['n_conflicts']['mean']:.3f}  critical/run "
                  f"{s['n_critical']['mean']:.3f}  contacts/run "
                  f"{s['n_collisions']['mean']:.3f}  min TTC "
                  f"{s['min_ttc']['mean']}")
        print()


def cmd_whatif(args):
    store = Store(args.db)
    changes = json.loads(args.changes)
    out = run_intervention(store, n_runs=args.n, changes=changes,
                           label=args.label, progress=_progress)
    print()
    print("  " + out["headline"])
    for key, p in out["paired"].items():
        if key in ("n_critical", "n_conflicts", "n_collisions", "n_near_misses",
                   "min_ttc"):
            print(f"    {p['label']:<32} {p['mean_difference']:+.4f} "
                  f"(±{p['sem']:.4f} sem, exceeds noise: {p['exceeds_noise']})")


def cmd_report(args):
    store = Store(args.db)
    bid = args.batch_id
    if not bid:
        b = store.latest_batch()
        if not b:
            print("no batches"); return
        bid = b["id"]
    rep = generate_report(store, bid)
    if args.out:
        with open(args.out, "w") as f:
            f.write(rep["markdown"])
        print(f"wrote {args.out} ({len(rep['markdown'])} chars, "
              f"{len(rep['sections'])} sections)")
    else:
        print(rep["markdown"])


def cmd_info(args):
    store = Store(args.db)
    print("Circuits:")
    for t in list_tracks():
        print(f"  {t['id']:<14} {t['name']:<22} {t['length']:>8.1f} m  "
              f"{t['n_corners']} corners  width {t['min_width']}-{t['max_width']} m  "
              f"closure {t['closure_error']} m")
    snap = A.snapshot()
    print(f"\nAssumptions: {len(snap)} entries in {len(A.groups())} groups "
          f"({sum(1 for a in snap if a['kind'] == 'methodology')} methodology, "
          f"{sum(1 for a in snap if a['kind'] == 'assumption')} assumption)")
    print(f"Workers available: {default_workers()}")
    bs = store.q("SELECT id, label, mode, n_runs_completed, status FROM batches "
                 "ORDER BY created_at DESC LIMIT 10")
    if bs:
        print("\nRecent batches:")
        for b in bs:
            print(f"  {b['id']}  {b['mode']:<12} {b['n_runs_completed']:>6} runs  "
                  f"{b['status']:<9} {b['label']}")


def cmd_demo(args):
    """Seed a database with everything the dashboard needs for a demo."""
    store = Store(args.db)
    print("=" * 66)
    print("APEX demo seed")
    print("=" * 66)
    t0 = time.time()
    mc = cmd_batch(argparse.Namespace(
        db=args.db, n=args.runs, seed=483921, label="Baseline Monte Carlo search",
        workers=None, replays=args.replays, weather=None, cars=None))
    print()
    gd = cmd_guided(argparse.Namespace(
        db=args.db, generations=args.generations, population=args.population,
        elites=12, seed=771337, label="Guided scenario search", seed_batch=mc))
    print()
    print(f"Done in {time.time() - t0:.1f}s")
    print(f"  monte_carlo batch: {mc}")
    print(f"  guided batch:      {gd}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="apex", description="Multi-agent motorsport safety stress tester")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("batch", help="run a Monte Carlo batch")
    p.add_argument("-n", type=int, default=2000)
    p.add_argument("--seed", type=int, default=483921)
    p.add_argument("--label", default="")
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--replays", type=int, default=400)
    p.add_argument("--weather", nargs="*", default=None)
    p.add_argument("--cars", nargs="*", type=int, default=None)
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("guided", help="run a guided/adversarial search")
    p.add_argument("--generations", type=int, default=6)
    p.add_argument("--population", type=int, default=60)
    p.add_argument("--elites", type=int, default=12)
    p.add_argument("--seed", type=int, default=771337)
    p.add_argument("--label", default="")
    p.add_argument("--seed-batch", default=None)
    p.set_defaults(func=cmd_guided)

    p = sub.add_parser("experiment", help="run a controlled experiment")
    p.add_argument("key", choices=list(EXPERIMENTS) + ["all"])
    p.add_argument("--runs", type=int, default=150)
    p.set_defaults(func=cmd_experiment)

    p = sub.add_parser("whatif", help="paired-seed intervention")
    p.add_argument("--changes", required=True,
                   help='JSON, e.g. \'{"overtake_threshold_delta":0.15}\'')
    p.add_argument("-n", type=int, default=200)
    p.add_argument("--label", default="")
    p.set_defaults(func=cmd_whatif)

    p = sub.add_parser("report", help="generate the stress-test report")
    p.add_argument("batch_id", nargs="?", default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("info", help="show circuits, assumptions and batches")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("demo", help="seed a database for the dashboard")
    p.add_argument("--runs", type=int, default=2000)
    p.add_argument("--generations", type=int, default=6)
    p.add_argument("--population", type=int, default=60)
    p.add_argument("--replays", type=int, default=400)
    p.set_defaults(func=cmd_demo)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
