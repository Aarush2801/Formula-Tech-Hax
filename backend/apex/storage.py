"""SQLite persistence.

Deliberately a thin layer. The schema stores what the dashboard needs to answer
its questions without keeping every trajectory of every run: full trajectories
are retained only in a window around interesting conflicts (see ``replay.py``),
which is what keeps a 10,000-run batch to a few tens of megabytes instead of
several gigabytes.

WAL mode is on because the API reads while a batch writes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "apex.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    label TEXT,
    mode TEXT,                -- monte_carlo | guided | experiment | intervention
    n_runs_requested INTEGER,
    n_runs_completed INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',
    space_json TEXT,
    pin_json TEXT,
    config_json TEXT,
    summary_json TEXT,
    wall_time_ms REAL,
    seed_base INTEGER
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    batch_id TEXT,
    created_at TEXT,
    seed INTEGER,
    track_id TEXT,
    n_cars INTEGER,
    weather TEXT,
    grip REAL, visibility REAL, spray REAL, tyre_condition REAL,
    track_temp REAL, ambient_temp REAL, wind REAL,
    traffic_density_requested REAL,
    traffic_density_measured REAL,
    grid_spread REAL, pace_spread REAL,
    track_width_multiplier REAL, error_rate_multiplier REAL,
    overtake_threshold_delta REAL, following_gap_delta REAL,
    duration REAL, n_timesteps INTEGER, wall_time_ms REAL,
    origin TEXT, generation INTEGER, parent_scenario_id TEXT,
    config_fingerprint TEXT,
    n_conflicts INTEGER, n_warnings INTEGER, n_critical INTEGER,
    n_near_misses INTEGER, n_collisions INTEGER, n_light_contacts INTEGER,
    n_off_track INTEGER, n_spins INTEGER, n_barrier_strikes INTEGER,
    n_evasive INTEGER, n_overtake_attempts INTEGER, n_overtakes_completed INTEGER,
    n_driver_errors INTEGER,
    min_ttc REAL, min_pet REAL, max_closing_speed REAL, max_deceleration REAL,
    peak_scsi REAL, hotspot_segment INTEGER,
    dominant_error TEXT,
    laps_completed REAL,
    field_mix_json TEXT,
    error_counts_json TEXT,
    scenario_json TEXT,
    has_replay INTEGER DEFAULT 0,
    FOREIGN KEY (batch_id) REFERENCES batches(id)
);
CREATE INDEX IF NOT EXISTS idx_runs_batch ON runs(batch_id);
CREATE INDEX IF NOT EXISTS idx_runs_weather ON runs(weather);
CREATE INDEX IF NOT EXISTS idx_runs_fp ON runs(config_fingerprint);
CREATE INDEX IF NOT EXISTS idx_runs_scsi ON runs(peak_scsi DESC);
CREATE INDEX IF NOT EXISTS idx_runs_ttc ON runs(min_ttc);

CREATE TABLE IF NOT EXISTS conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    batch_id TEXT,
    driver_a TEXT, driver_b TEXT,
    driver_a_index INTEGER, driver_b_index INTEGER,
    archetype_a TEXT, archetype_b TEXT,
    conflict_type TEXT, severity TEXT,
    t_min_ttc REAL, timestep INTEGER,
    segment_index INTEGER, location TEXT, turn_number INTEGER,
    min_ttc REAL, min_pet REAL, closing_speed REAL, max_deceleration REAL,
    evasive_action INTEGER, collision INTEGER, scsi REAL,
    a_decision TEXT, b_decision TEXT,
    weather TEXT, traffic_density REAL, n_cars INTEGER,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS idx_conf_run ON conflicts(run_id);
CREATE INDEX IF NOT EXISTS idx_conf_batch ON conflicts(batch_id);
CREATE INDEX IF NOT EXISTS idx_conf_seg ON conflicts(segment_index);
CREATE INDEX IF NOT EXISTS idx_conf_sev ON conflicts(severity);
CREATE INDEX IF NOT EXISTS idx_conf_ttc ON conflicts(min_ttc);
CREATE INDEX IF NOT EXISTS idx_conf_arch ON conflicts(archetype_a, archetype_b);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    batch_id TEXT,
    t REAL, timestep INTEGER,
    event_type TEXT, severity TEXT,
    segment_index INTEGER, location TEXT,
    driver_a TEXT, driver_b TEXT,
    driver_a_index INTEGER, driver_b_index INTEGER,
    min_ttc REAL, min_pet REAL, closing_speed REAL,
    max_deceleration REAL, lateral_rate REAL,
    evasive_action INTEGER, collision INTEGER, off_track INTEGER,
    detail_json TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
CREATE INDEX IF NOT EXISTS idx_ev_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_ev_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_ev_batch ON events(batch_id);

CREATE TABLE IF NOT EXISTS replays (
    run_id TEXT PRIMARY KEY,
    batch_id TEXT,
    focus_timestep INTEGER,
    focus_drivers TEXT,
    min_ttc REAL,
    payload BLOB,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS patterns (
    id TEXT PRIMARY KEY,
    batch_id TEXT,
    rank INTEGER,
    pattern_key TEXT,
    track_id TEXT,
    segment_index INTEGER,
    location TEXT,
    turn_number INTEGER,
    weather TEXT,
    n_cars INTEGER,
    traffic_band TEXT,
    archetype_a TEXT, archetype_b TEXT,
    conflict_type TEXT,
    dominant_error TEXT,
    occurrences INTEGER,
    runs_evaluated INTEGER,
    band_runs INTEGER,
    occurrence_rate REAL,
    median_min_ttc REAL, p05_min_ttc REAL,
    median_min_pet REAL, median_closing_speed REAL,
    evasive_rate REAL, collision_rate REAL, mean_scsi REAL,
    example_run_ids_json TEXT,
    conditions_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_pat_batch ON patterns(batch_id);

CREATE TABLE IF NOT EXISTS analysis (
    id TEXT PRIMARY KEY,
    batch_id TEXT,
    kind TEXT,
    payload_json TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_an_batch ON analysis(batch_id, kind);

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    created_at TEXT,
    name TEXT,
    kind TEXT,
    config_json TEXT,
    results_json TEXT,
    batch_ids_json TEXT
);
"""

# --------------------------------------------------------------------------
# Apex Passport -- new tables only, additive. Never alters the tables above.
# --------------------------------------------------------------------------
PASSPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS cars (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    class TEXT NOT NULL,
    car_profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parts (
    car_id TEXT NOT NULL,
    name TEXT NOT NULL,
    life_used_pct REAL NOT NULL DEFAULT 0,
    part_cost REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'green',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (car_id, name),
    FOREIGN KEY (car_id) REFERENCES cars(id)
);

CREATE TABLE IF NOT EXISTS history_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    car_id TEXT NOT NULL,
    time TEXT NOT NULL,
    type TEXT NOT NULL,
    details_json TEXT NOT NULL,
    hash TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    seq INTEGER NOT NULL,
    FOREIGN KEY (car_id) REFERENCES cars(id)
);
CREATE INDEX IF NOT EXISTS idx_hist_car ON history_events(car_id, seq);

CREATE TABLE IF NOT EXISTS stress_tests (
    id TEXT PRIMARY KEY,
    car_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    track_id TEXT NOT NULL,
    weather TEXT NOT NULL,
    n_races INTEGER NOT NULL,
    batch_id TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    results_json TEXT,
    FOREIGN KEY (car_id) REFERENCES cars(id)
);
CREATE INDEX IF NOT EXISTS idx_stress_car ON stress_tests(car_id);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    car_id TEXT NOT NULL,
    reported_at TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    description TEXT,
    affected_parts_json TEXT,
    before_snapshot_json TEXT NOT NULL,
    history_event_id INTEGER,
    FOREIGN KEY (car_id) REFERENCES cars(id)
);
CREATE INDEX IF NOT EXISTS idx_incident_car ON incidents(car_id);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self.connect() as c:
            c.executescript(SCHEMA)
            c.executescript(PASSPORT_SCHEMA)
        self._migrate()

    # ------------------------------------------------------------------
    def _migrate(self) -> None:
        """Add columns introduced after a database was first created.

        ``CREATE TABLE IF NOT EXISTS`` does not alter an existing table, so a
        database written by an earlier version keeps its old shape. Rather than
        force a rebuild of a batch that took twenty minutes to produce, missing
        columns are added in place.
        """
        additions = {
            "patterns": [("band_runs", "INTEGER"), ("occurrence_rate", "REAL")],
            "runs": [("scenario_json", "TEXT")],
        }
        conn = self.connect()
        for table, cols in additions.items():
            try:
                existing = {
                    r["name"] for r in conn.execute(f"PRAGMA table_info({table})")
                }
            except sqlite3.Error:
                continue
            if not existing:
                continue
            for name, decl in cols:
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    # ------------------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def q(self, sql: str, params: Iterable = ()) -> list[dict]:
        cur = self.connect().execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]

    def q1(self, sql: str, params: Iterable = ()) -> dict | None:
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def exec(self, sql: str, params: Iterable = ()) -> None:
        self.connect().execute(sql, tuple(params))

    # ------------------------------------------------------------------
    # Batches
    # ------------------------------------------------------------------
    def create_batch(
        self, batch_id: str, label: str, mode: str, n_runs: int,
        space: dict | None, pin: dict | None, config: dict | None,
        seed_base: int,
    ) -> None:
        self.exec(
            "INSERT OR REPLACE INTO batches (id, created_at, label, mode, "
            "n_runs_requested, n_runs_completed, status, space_json, pin_json, "
            "config_json, seed_base) VALUES (?,?,?,?,?,0,'running',?,?,?,?)",
            (batch_id, utcnow(), label, mode, n_runs,
             json.dumps(space or {}), json.dumps(pin or {}),
             json.dumps(config or {}), seed_base),
        )

    def update_batch_progress(self, batch_id: str, completed: int) -> None:
        self.exec("UPDATE batches SET n_runs_completed=? WHERE id=?",
                  (completed, batch_id))

    def finish_batch(self, batch_id: str, summary: dict, wall_ms: float,
                     status: str = "complete") -> None:
        self.exec(
            "UPDATE batches SET status=?, summary_json=?, wall_time_ms=? WHERE id=?",
            (status, json.dumps(summary), wall_ms, batch_id),
        )

    # ------------------------------------------------------------------
    # Runs (bulk)
    # ------------------------------------------------------------------
    RUN_COLS = [
        "id", "batch_id", "created_at", "seed", "track_id", "n_cars", "weather",
        "grip", "visibility", "spray", "tyre_condition", "track_temp",
        "ambient_temp", "wind", "traffic_density_requested",
        "traffic_density_measured", "grid_spread", "pace_spread",
        "track_width_multiplier", "error_rate_multiplier",
        "overtake_threshold_delta", "following_gap_delta", "duration",
        "n_timesteps", "wall_time_ms", "origin", "generation",
        "parent_scenario_id", "config_fingerprint", "n_conflicts", "n_warnings",
        "n_critical", "n_near_misses", "n_collisions", "n_light_contacts",
        "n_off_track", "n_spins", "n_barrier_strikes", "n_evasive",
        "n_overtake_attempts", "n_overtakes_completed", "n_driver_errors",
        "min_ttc", "min_pet", "max_closing_speed", "max_deceleration",
        "peak_scsi", "hotspot_segment", "dominant_error", "laps_completed",
        "field_mix_json", "error_counts_json", "scenario_json", "has_replay",
    ]

    CONFLICT_COLS = [
        "run_id", "batch_id", "driver_a", "driver_b", "driver_a_index",
        "driver_b_index", "archetype_a", "archetype_b", "conflict_type",
        "severity", "t_min_ttc", "timestep", "segment_index", "location",
        "turn_number", "min_ttc", "min_pet", "closing_speed", "max_deceleration",
        "evasive_action", "collision", "scsi", "a_decision", "b_decision",
        "weather", "traffic_density", "n_cars",
    ]

    EVENT_COLS = [
        "run_id", "batch_id", "t", "timestep", "event_type", "severity",
        "segment_index", "location", "driver_a", "driver_b", "driver_a_index",
        "driver_b_index", "min_ttc", "min_pet", "closing_speed",
        "max_deceleration", "lateral_rate", "evasive_action", "collision",
        "off_track", "detail_json",
    ]

    def insert_runs(self, rows: list[dict]) -> None:
        if not rows:
            return
        ph = ",".join("?" * len(self.RUN_COLS))
        sql = f"INSERT OR REPLACE INTO runs ({','.join(self.RUN_COLS)}) VALUES ({ph})"
        data = [tuple(r.get(c) for c in self.RUN_COLS) for r in rows]
        c = self.connect()
        c.execute("BEGIN")
        c.executemany(sql, data)
        c.execute("COMMIT")

    def insert_conflicts(self, rows: list[dict]) -> None:
        if not rows:
            return
        ph = ",".join("?" * len(self.CONFLICT_COLS))
        sql = (f"INSERT INTO conflicts ({','.join(self.CONFLICT_COLS)}) "
               f"VALUES ({ph})")
        data = [tuple(r.get(c) for c in self.CONFLICT_COLS) for r in rows]
        c = self.connect()
        c.execute("BEGIN")
        c.executemany(sql, data)
        c.execute("COMMIT")

    def insert_events(self, rows: list[dict]) -> None:
        if not rows:
            return
        ph = ",".join("?" * len(self.EVENT_COLS))
        sql = f"INSERT INTO events ({','.join(self.EVENT_COLS)}) VALUES ({ph})"
        data = [tuple(r.get(c) for c in self.EVENT_COLS) for r in rows]
        c = self.connect()
        c.execute("BEGIN")
        c.executemany(sql, data)
        c.execute("COMMIT")

    def insert_replay(self, run_id: str, batch_id: str, focus_timestep: int,
                      focus_drivers: list[int], min_ttc: float,
                      payload: dict) -> None:
        blob = zlib.compress(json.dumps(payload).encode(), 6)
        self.exec(
            "INSERT OR REPLACE INTO replays (run_id, batch_id, focus_timestep, "
            "focus_drivers, min_ttc, payload) VALUES (?,?,?,?,?,?)",
            (run_id, batch_id, focus_timestep, json.dumps(focus_drivers),
             min_ttc, blob),
        )

    def get_replay(self, run_id: str) -> dict | None:
        row = self.q1("SELECT * FROM replays WHERE run_id=?", (run_id,))
        if not row:
            return None
        payload = json.loads(zlib.decompress(row["payload"]).decode())
        payload["focus_timestep"] = row["focus_timestep"]
        payload["focus_drivers"] = json.loads(row["focus_drivers"])
        return payload

    # ------------------------------------------------------------------
    def save_patterns(self, batch_id: str, patterns: list[dict]) -> None:
        c = self.connect()
        c.execute("BEGIN")
        c.execute("DELETE FROM patterns WHERE batch_id=?", (batch_id,))
        cols = [
            "id", "batch_id", "rank", "pattern_key", "track_id", "segment_index",
            "location", "turn_number", "weather", "n_cars", "traffic_band",
            "archetype_a", "archetype_b", "conflict_type", "dominant_error",
            "occurrences", "runs_evaluated", "band_runs", "occurrence_rate",
            "median_min_ttc", "p05_min_ttc",
            "median_min_pet", "median_closing_speed", "evasive_rate",
            "collision_rate", "mean_scsi", "example_run_ids_json",
            "conditions_json",
        ]
        ph = ",".join("?" * len(cols))
        c.executemany(
            f"INSERT INTO patterns ({','.join(cols)}) VALUES ({ph})",
            [tuple(p.get(k) for k in cols) for p in patterns],
        )
        c.execute("COMMIT")

    def save_analysis(self, batch_id: str, kind: str, payload: dict) -> None:
        self.exec(
            "INSERT OR REPLACE INTO analysis (id, batch_id, kind, payload_json, "
            "created_at) VALUES (?,?,?,?,?)",
            (f"{batch_id}:{kind}", batch_id, kind, json.dumps(payload), utcnow()),
        )

    def get_analysis(self, batch_id: str, kind: str) -> dict | None:
        row = self.q1("SELECT payload_json FROM analysis WHERE batch_id=? AND kind=?",
                      (batch_id, kind))
        return json.loads(row["payload_json"]) if row else None

    def save_experiment(self, exp_id: str, name: str, kind: str, config: dict,
                        results: dict, batch_ids: list[str]) -> None:
        self.exec(
            "INSERT OR REPLACE INTO experiments (id, created_at, name, kind, "
            "config_json, results_json, batch_ids_json) VALUES (?,?,?,?,?,?,?)",
            (exp_id, utcnow(), name, kind, json.dumps(config),
             json.dumps(results), json.dumps(batch_ids)),
        )

    # ------------------------------------------------------------------
    def latest_batch(self, mode: str | None = None) -> dict | None:
        if mode:
            return self.q1(
                "SELECT * FROM batches WHERE mode=? AND status='complete' "
                "ORDER BY created_at DESC LIMIT 1", (mode,))
        return self.q1(
            "SELECT * FROM batches WHERE status='complete' "
            "ORDER BY created_at DESC LIMIT 1")

    def vacuum(self) -> None:
        self.connect().execute("VACUUM")
