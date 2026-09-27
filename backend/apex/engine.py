"""Racing / environment engine.

Deterministic, mathematical, and fast. No language model is anywhere near this
file: every decision here is closed-form arithmetic on NumPy arrays.

The engine is vectorised *across agents*, not across runs. All 22 cars advance
together in a synchronised timestep, and the pairwise interaction structure that
the whole study is about (a 22x22 gap / closing-speed / TTC matrix) is exactly
484 elements, which NumPy evaluates essentially for free. A 75 s run at 20 Hz is
1,500 synchronised rounds, and a run costs single-digit milliseconds of array
work rather than ~35,000 per-agent Python calls. That is the difference between a
10,000-run batch being a coffee break and being an overnight job.

Per timestep, in order:
  1. expire and sample human-error events
  2. resolve geometry and effective grip for each agent
  3. build the *delayed* perception matrices (each agent sees the world as it was
     one of its own reaction times ago)
  4. evaluate the situation: car ahead, car behind, room available, corner coming
  5. decide: longitudinal (brake / coast / accelerate), lateral (line, overtake,
     defend, yield), with collision avoidance overriding racing intent
  6. integrate vehicle state under a friction-ellipse budget
  7. detect contact, off-track excursions and barrier strikes
  8. record trajectories, and feed the surrogate-safety accumulators

Reaction time is implemented as a genuine perception delay through a ring buffer
rather than as a fudge factor on a gain, because the ordering of events matters:
an agent that reacts 0.24 s late is acting on a world that has already moved on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from . import assumptions as A
from .car_profiles import CarProfile
from .drivers import as_arrays
from .environment import make_environment, perception_range
from .errors import ErrorState
from .models import (
    ConflictType, Decision, DriverProfile, Environment, EventType, Scenario,
    Severity, Track,
)
from .safety import (
    ConflictAccumulator, PETTracker, classify_conflict_type, closing_speed_matrix,
    pairwise_ttc, ttc_from_relative,
)
from .track import TrackGeometry, brake_accel_limit, lateral_accel_limit

G = 9.81
INF = 1e9

DECISION_CODES = {d.value: i for i, d in enumerate(Decision)}
CODE_TO_DECISION = {i: d.value for d, i in zip(Decision, range(len(Decision)))}
CODE_TO_DECISION = {i: d for i, d in enumerate([d.value for d in Decision])}


@dataclass
class RunResult:
    scenario: Scenario
    environment: Environment
    profiles: list[DriverProfile]
    n_steps: int
    dt: float
    wall_time_ms: float
    # Trajectory arrays, shape (n_steps, n_cars)
    traj_s: np.ndarray
    traj_d: np.ndarray
    traj_v: np.ndarray
    traj_a: np.ndarray
    traj_throttle: np.ndarray
    traj_brake: np.ndarray
    traj_lat: np.ndarray
    traj_seg: np.ndarray
    traj_decision: np.ndarray
    # Outcomes
    conflicts: list[dict]
    events: list[dict]
    pet_pair_min: dict
    min_pet: float
    error_counts: dict
    error_log: list
    dominant_error: str | None
    measured_traffic_density: float
    max_closing_speed: float
    max_deceleration: float
    n_collisions: int
    n_light_contacts: int
    n_off_track: int
    n_spins: int
    n_barrier_strikes: int
    n_overtake_attempts: int
    n_overtakes_completed: int
    n_overtakes_aborted: int
    n_evasive: int
    laps_completed: float
    segment_conflict_counts: dict
    track_id: str
    # None unless a team car was present (Apex Passport).
    team_car_telemetry: dict | None = None


class RaceEngine:
    def __init__(
        self,
        scenario: Scenario,
        track: Track,
        profiles: list[DriverProfile],
        record_trajectory: bool = True,
        team_car_profile: "CarProfile | None" = None,
    ):
        self.sc = scenario
        self.track = track
        self.geo = TrackGeometry(track, scenario.track_width_multiplier)
        self.profiles = profiles
        self.n = len(profiles)
        self.dt = A.DT
        self.n_steps = int(round(scenario.duration / self.dt))
        self.record_trajectory = record_trajectory
        self.rng = np.random.default_rng(scenario.seed)
        self.env = scenario.environment
        self.p = as_arrays(profiles)
        self.L = self.geo.length

        # Perception-delay ring buffer.
        self.buf_len = int(np.ceil(0.45 * A.ERROR_EFFECTS["delayed_reaction_multiplier"]
                                   / self.dt)) + 4

        self.lookahead = np.arange(0.0, A.LOOKAHEAD_HORIZON, A.LOOKAHEAD_STEP)
        # Boolean mask indexed by segment: np.isin per timestep was pure waste.
        self._is_braking_zone = np.array(
            [sg.is_braking_zone for sg in track.segments], dtype=bool
        )

        # ---- Apex Passport: optional team car -----------------------------
        # Every per-car physics array below defaults to the field-wide scalar
        # from assumptions.py, uniformly. An array filled everywhere with the
        # same value broadcasts identically to that scalar in every numpy
        # elementwise op used below, so when team_car_profile is None (or no
        # profile has id "TEAM") this is provably the same computation as
        # before -- see tests/test_car_profiles.py::test_no_team_car_is_unchanged.
        n = self.n
        self.team_idx: int | None = None
        if team_car_profile is not None:
            for i, prof in enumerate(profiles):
                if prof.id == "TEAM":
                    self.team_idx = i
                    break

        self.car_mass = np.full(n, A.CAR_MASS)
        self.engine_power_w = np.full(n, A.ENGINE_POWER)
        self.traction_accel = np.full(n, A.TRACTION_ACCEL)
        self.drag_coeff_arr = np.full(n, A.DRAG_COEFF)
        self.mu_lateral = np.full(n, A.LATERAL_MU)
        self.aero_lateral_gain = np.full(n, A.AERO_LATERAL_GAIN)
        self.max_corner_speed_arr = np.full(n, A.MAX_CORNER_SPEED)
        self.brake_flat_g = np.full(n, np.nan)  # NaN = use the field's dynamic formula
        self.team_car_profile = team_car_profile

        if self.team_idx is not None:
            i = self.team_idx
            cp = team_car_profile
            self.car_mass[i] = cp.mass_kg
            self.engine_power_w[i] = cp.power_kw * 1000.0
            self.traction_accel[i] = A.TRACTION_ACCEL * (
                cp.tyre_grip_coeff / A.LATERAL_MU
            )
            self.drag_coeff_arr[i] = cp.drag_coeff
            self.mu_lateral[i] = cp.tyre_grip_coeff
            self.aero_lateral_gain[i] = cp.downforce_coeff
            self.max_corner_speed_arr[i] = min(
                A.MAX_CORNER_SPEED, cp.top_speed_kmh / 3.6
            )
            self.brake_flat_g[i] = cp.max_brake_g

        # Team-car-only telemetry (spec section 1): kerb strikes, peak g,
        # braking energy per lap, contacts with impact speed. Populated only
        # when a team car is present; see _finalise.
        self.team_kerb_strikes: list[dict] = []
        self.team_peak_g = 0.0
        self.team_braking_energy_by_lap: dict[int, float] = {}
        self.team_contacts: list[dict] = []
        self.team_was_kerb = False

    # ======================================================================
    # Initial conditions
    # ======================================================================
    def _initialise(self):
        n, rng = self.n, self.rng
        geo = self.geo

        # Starting order is shuffled per run: who you are racing near is one of the
        # Monte Carlo dimensions, and it matters as much as any environmental dial.
        self.grid_order = rng.permutation(n)

        # Requested traffic density sets the nominal starting gap. Density is also
        # re-measured during the run, because the field spreads or bunches.
        density = float(np.clip(self.sc.traffic_density, 0.0, 1.0))
        # Nominal gap from requested density. The earlier mapping started the
        # field closer than any agent's own target following gap, so the whole
        # pack was on the brakes from the first timestep.
        base_gap = (100.0 - 62.0 * density) * self.sc.grid_spread
        gaps = base_gap * (1.0 + rng.normal(0.0, 0.22, n))
        gaps = np.clip(gaps, 9.0, 220.0)

        s = np.zeros(n)
        # Where the pack starts is drawn per run. See assumptions.PACK_START_RANDOM:
        # a fixed start point would bake the author's arbitrary choice into every
        # hotspot the search reports.
        start_s = rng.uniform(0.0, self.L) if A.PACK_START_RANDOM else 200.0
        self.pack_start_s = start_s
        acc = start_s
        for rank, car in enumerate(self.grid_order):
            s[car] = acc
            acc -= gaps[rank]
        s = s % self.L

        d = geo.racing_line(s) + rng.normal(0.0, 0.9, n)
        halfw = geo.width(s) * 0.5 - A.CAR_WIDTH * 0.5
        d = np.clip(d, -halfw, halfw)

        # Start at the local speed ceiling, scaled by pace and a small spread.
        R = geo.radius(s)
        vcap = self._corner_speed(R, np.full(n, self.env.grip), mu=self.mu_lateral,
                                  aero_gain=self.aero_lateral_gain,
                                  max_speed=self.max_corner_speed_arr)
        pace = 1.0 + (self.p["pace_multiplier"] - 1.0) * self.sc.pace_spread
        v = np.minimum(vcap, 92.0) * pace * (1.0 + rng.normal(0.0, 0.012, n))

        self.s, self.d, self.v = s, d, np.clip(v, 15.0, 100.0)
        self.a = np.zeros(n)
        self.lat_rate = np.zeros(n)
        self.lap = np.zeros(n, dtype=np.int32)
        self.dist_total = np.zeros(n)

        self.err = ErrorState(
            n, self.p["error_probability"], self.sc.error_rate_multiplier
        )

        # Racing intent state.
        self.ot_target = np.full(n, -1, dtype=np.int64)
        self.ot_side = np.zeros(n)
        self.ot_until = np.zeros(n)
        self.ot_cooldown = np.zeros(n)
        self.ot_best_gap = np.full(n, INF)
        self.seg_prev = self.geo.segment_index(self.s)
        self.defending = np.zeros(n, dtype=bool)
        self.defend_target = np.full(n, -1, dtype=np.int64)
        self.defend_draw = self.rng.random(n)
        self.yielding = np.zeros(n, dtype=bool)
        self.was_off = np.zeros(n, dtype=bool)
        self.spun = np.zeros(n, dtype=bool)

        # History buffers for delayed perception, primed with the initial state.
        self.h_s = np.tile(self.s, (self.buf_len, 1))
        self.h_d = np.tile(self.d, (self.buf_len, 1))
        self.h_v = np.tile(self.v, (self.buf_len, 1))
        self.h_lat = np.zeros((self.buf_len, self.n))
        self.head = 0

        T = self.n_steps
        z = lambda dt_: np.zeros((T, n), dtype=dt_)
        self.tr_s, self.tr_d, self.tr_v = z(np.float32), z(np.float32), z(np.float32)
        self.tr_a, self.tr_th, self.tr_br = z(np.float32), z(np.float32), z(np.float32)
        self.tr_lat = z(np.float32)
        self.tr_seg = z(np.int16)
        self.tr_dec = z(np.int8)

        self.acc = ConflictAccumulator()
        self.pet = PETTracker(self.L, n)
        self.events: list[dict] = []
        self.collision_cooldown: dict[tuple[int, int], float] = {}
        self.max_closing = 0.0
        self.max_decel = 0.0
        self.n_collisions = 0
        self.n_light_contacts = 0
        self.squeeze_lifts = 0
        self.n_off_track = 0
        self.n_barrier = 0
        self.n_ot_attempt = 0
        self.n_ot_done = 0
        self.n_ot_abort = 0
        self.density_samples: list[float] = []
        self.seg_conflicts: dict[int, int] = {}
        self.evasive_steps = np.zeros(n, dtype=bool)
        self.was_emergency_braking = np.zeros(n, dtype=bool)
        self.n_evasive_events = 0

    # ======================================================================
    # Vehicle limits
    # ======================================================================
    @staticmethod
    def _corner_speed(R: np.ndarray, grip: np.ndarray, mu=None, aero_gain=None,
                      max_speed=None) -> np.ndarray:
        # mu/aero_gain/max_speed default to the field-wide scalars; passing
        # per-car arrays (broadcast-shaped by the caller) is what gives the
        # Apex Passport team car its own cornering limit without touching
        # anyone else's -- see the equivalence note on RaceEngine.__init__.
        mu = A.LATERAL_MU if mu is None else mu
        aero_gain = A.AERO_LATERAL_GAIN if aero_gain is None else aero_gain
        max_speed = A.MAX_CORNER_SPEED if max_speed is None else max_speed
        k, vref2 = aero_gain, A.AERO_REF_SPEED ** 2
        denom = 1.0 - grip * k * G * R / vref2
        safe = np.maximum(denom, 1e-3)
        v2 = mu * grip * G * R / safe
        v = np.sqrt(np.maximum(v2, 1.0))
        return np.where(denom <= 1e-3, max_speed, np.minimum(v, max_speed))

    def _drag_accel(self, v: np.ndarray, slip: np.ndarray) -> np.ndarray:
        cd = self.drag_coeff_arr * (1.0 - A.SLIPSTREAM_GAIN * slip)
        return 0.5 * A.AIR_DENSITY * cd * v * v / self.car_mass

    # ======================================================================
    # Main loop
    # ======================================================================
    def run(self) -> RunResult:
        t0 = time.perf_counter()
        self._initialise()
        n, dt, geo, rng = self.n, self.dt, self.geo, self.rng
        idx_n = np.arange(n)
        half_L = self.L / 2.0
        perc_base = perception_range(self.env)
        secs_cadence = int(round(1.0 / dt))

        base_margin = (A.BASE_BRAKING_MARGIN
                       - A.LATE_BRAKING_MARGIN_SPAN * self.p["late_braking_tendency"])
        time_gap = (A.FOLLOWING_TIME_GAP * (1.45 - 0.60 * self.p["risk_tolerance"])
                    + self.sc.following_gap_delta)
        time_gap = np.maximum(time_gap, 0.12)
        ot_threshold_base = (0.56 - 0.34 * self.p["overtake_willingness"]
                             + self.sc.overtake_threshold_delta)

        for step in range(self.n_steps):
            t = step * dt

            # ---- 1. human error ------------------------------------------
            self.err.expire(t)
            # ---- 2. geometry (one index pass) and effective grip ---------
            (seg, width_here, line, R_here, kappa, ot_rating,
             in_corner) = geo.step_state(self.s)
            halfw = width_here * 0.5
            usable = np.maximum(halfw - A.CAR_WIDTH * 0.5 - 0.15, 0.4)

            if step % secs_cadence == 0:
                self.err.sample_per_second(t, rng, in_corner)
            # A braking-point error is drawn once, on entering a braking zone.
            entered_bz = (seg != self.seg_prev) & self._is_braking_zone[seg]
            self.err.sample_at_braking_zone(t, rng, entered_bz)
            self.seg_prev = seg

            grip = np.full(n, self.env.grip) * self.err.grip_scale
            grip = np.where(self.was_off, grip * 0.65, grip)

            # ---- 3. delayed perception -----------------------------------
            react = np.clip(self.p["reaction_time"] * self.err.reaction_scale,
                            0.05, 0.45 * A.ERROR_EFFECTS["delayed_reaction_multiplier"])
            delay = np.clip(np.round(react / dt).astype(np.int64), 0, self.buf_len - 1)
            rows = (self.head - delay) % self.buf_len
            p_s, p_d, p_v = self.h_s[rows], self.h_d[rows], self.h_v[rows]
            p_lat = self.h_lat[rows]

            ds = (p_s - self.s[:, None] + half_L) % self.L - half_L
            dd = p_d - self.d[:, None]
            dv = p_v - self.v[:, None]
            np.fill_diagonal(ds, INF)

            # Spray degrades perception specifically when running close behind.
            lon_gap = np.abs(ds)
            perc = perc_base * (1.0 - 0.45 * self.env.spray
                                * np.clip(1.0 - lon_gap / 60.0, 0.0, 1.0))

            same_corridor = np.abs(dd) < A.CAR_WIDTH * 1.35
            ahead = (ds > 0) & (ds < perc) & same_corridor
            behind = (ds < 0) & (-ds < A.DEFEND_TRIGGER_RANGE) & same_corridor & (dv > 0)
            # Anyone ahead in any lane, used for overtake target selection.
            ahead_any = (ds > 0) & (ds < perc)

            ds_ahead = np.where(ahead, ds, INF)
            j_ahead = np.argmin(ds_ahead, axis=1)
            has_ahead = ds_ahead[idx_n, j_ahead] < INF
            gap_ahead = np.where(has_ahead, ds_ahead[idx_n, j_ahead] - A.CAR_LENGTH, INF)
            v_ahead = np.where(has_ahead, p_v[idx_n, j_ahead], self.v)

            ds_any = np.where(ahead_any, ds, INF)
            j_any = np.argmin(ds_any, axis=1)
            has_any = ds_any[idx_n, j_any] < INF
            gap_any = np.where(has_any, ds_any[idx_n, j_any] - A.CAR_LENGTH, INF)
            v_any = np.where(has_any, p_v[idx_n, j_any], self.v)
            d_any = np.where(has_any, p_d[idx_n, j_any], self.d)

            ds_behind = np.where(behind, ds, -INF)
            j_behind = np.argmax(ds_behind, axis=1)
            has_behind = ds_behind[idx_n, j_behind] > -INF

            # Slipstream and dirty air.
            slip = np.where(
                has_ahead & (gap_ahead < A.SLIPSTREAM_RANGE),
                np.clip(1.0 - gap_ahead / A.SLIPSTREAM_RANGE, 0.0, 1.0), 0.0,
            )
            grip = grip * (1.0 - A.DIRTY_AIR_GRIP_LOSS * slip)

            a_brake_max = brake_accel_limit(self.v, grip, flat_g=self.brake_flat_g)
            a_lat_max = lateral_accel_limit(self.v, grip, mu=self.mu_lateral,
                                            aero_gain=self.aero_lateral_gain)

            # ---- 4. what must I brake for? -------------------------------
            R_probe = geo.probe_radius(self.s, self.lookahead)
            vcap = self._corner_speed(R_probe, grip[:, None], mu=self.mu_lateral[:, None],
                                      aero_gain=self.aero_lateral_gain[:, None],
                                      max_speed=self.max_corner_speed_arr[:, None])
            pace = 1.0 + (self.p["pace_multiplier"] - 1.0) * self.sc.pace_spread
            vcap = vcap * pace[:, None] * A.CORNER_SPEED_MARGIN
            dist_eff = np.maximum(
                self.lookahead[None, :] + self.err.braking_offset[:, None], 1.0
            )
            req = (self.v[:, None] ** 2 - vcap ** 2) / (2.0 * dist_eff)
            k_bind = np.argmax(req, axis=1)
            req_corner = req[idx_n, k_bind]
            v_target = vcap[idx_n, k_bind]
            dist_corner = self.lookahead[k_bind]

            # Car following.
            gap_desired = np.maximum(self.v * time_gap, 4.0)
            follow_slack = np.maximum(gap_ahead - gap_desired * 0.55, 1.5)
            req_follow = np.where(
                has_ahead & (self.v > v_ahead),
                (self.v ** 2 - v_ahead ** 2) / (2.0 * follow_slack),
                -INF,
            )
            gap_squeeze = np.where(
                has_ahead & (gap_ahead < gap_desired),
                0.35 * np.clip(1.0 - gap_ahead / np.maximum(gap_desired, 1.0), 0, 1),
                0.0,
            )

            trigger = a_brake_max / np.maximum(base_margin, 1.0)
            brake_corner = np.clip(req_corner / a_brake_max, 0.0, 1.0)
            brake_corner = np.where(req_corner >= trigger, brake_corner, 0.0)
            brake_follow = np.clip(req_follow / a_brake_max, 0.0, 1.0)
            brake_follow = np.where(req_follow >= trigger, brake_follow, 0.0)
            brake_level = np.maximum(np.maximum(brake_corner, brake_follow), gap_squeeze)

            # ---- 5. racing intent ----------------------------------------
            # Overtake evaluation against the nearest car ahead in any lane.
            speed_adv = self.v - v_any
            opportunity = (
                0.45 * np.clip(speed_adv / 6.0, 0.0, 1.0)
                + 0.35 * ot_rating
                + 0.20 * np.clip(1.0 - gap_any / A.OVERTAKE_COMMIT_RANGE, 0.0, 1.0)
            )
            drive = opportunity * (0.55 + 0.45 * self.p["aggression"])
            thresh = ot_threshold_base + self.err.threshold_delta
            can_try = (
                has_any
                & (self.ot_target < 0)
                & (t >= self.ot_cooldown)
                & (ot_rating >= A.OVERTAKE_MIN_ZONE_RATING)
                & (speed_adv > A.OVERTAKE_MIN_SPEED_ADVANTAGE)
                & (gap_any < A.OVERTAKE_COMMIT_RANGE)
                & ~self.err.spinning
            )
            commit = can_try & (drive > thresh)

            if commit.any():
                # To pass on side sigma the attacker must sit at the target's
                # lateral position plus a car width and a clearance. The move is
                # only feasible if that position is still inside the usable width,
                # which is precisely what a narrow corner takes away.
                offs = A.CAR_WIDTH + A.OVERTAKE_SIDE_CLEARANCE
                d_left, d_right = d_any + offs, d_any - offs
                margin_left = usable - np.abs(d_left)
                margin_right = usable - np.abs(d_right)
                side = np.where(margin_left >= margin_right, 1.0, -1.0)
                enough = np.maximum(margin_left, margin_right) > 0.0
                do = commit & enough
                self.ot_target = np.where(do, j_any, self.ot_target)
                self.ot_side = np.where(do, side, self.ot_side)
                self.ot_until = np.where(do, t + 5.5, self.ot_until)
                self.ot_best_gap = np.where(do, gap_any, self.ot_best_gap)
                # An agent that looked and found no room waits before looking again.
                self.ot_cooldown = np.where(
                    commit & ~enough, t + A.OVERTAKE_COOLDOWN * 0.5, self.ot_cooldown
                )
                for i in np.nonzero(do)[0]:
                    self.n_ot_attempt += 1
                    self._event(
                        t, step, EventType.OVERTAKE_ATTEMPT, Severity.NORMAL, seg[i],
                        int(i), int(j_any[i]),
                        detail=dict(gap=round(float(gap_any[i]), 2),
                                    speed_advantage=round(float(speed_adv[i]), 2),
                                    side="left" if side[i] > 0 else "right",
                                    overtaking_rating=round(float(ot_rating[i]), 2)),
                    )

            # Defensive response.
            defend_now = (
                has_behind
                & (self.p["defensive_tendency"] > self.defend_draw)
                & ~self.err.spinning
            )
            newly_defending = defend_now & ~self.defending
            for i in np.nonzero(newly_defending)[0]:
                self._event(
                    t, step, EventType.DEFENSIVE_MOVE, Severity.NORMAL, seg[i],
                    int(i), int(j_behind[i]),
                    detail=dict(defensive_tendency=round(float(
                        self.p["defensive_tendency"][i]), 3)),
                )
            self.defending = defend_now
            self.defend_target = np.where(defend_now, j_behind, -1)
            if step % int(round(1.5 / dt)) == 0:
                self.defend_draw = rng.random(n)

            # Yield: low-aggression agents concede rather than hold the line.
            attacker_alongside = np.zeros(n, dtype=bool)
            for i in np.nonzero(has_behind)[0]:
                jb = j_behind[i]
                attacker_alongside[i] = -ds[i, jb] < A.CAR_LENGTH * 1.8
            self.yielding = (
                attacker_alongside
                & (self.p["defensive_tendency"] < 0.45)
                & (self.p["risk_tolerance"] < 0.55)
            )

            # ---- lateral target ------------------------------------------
            d_target = line.copy()

            active_ot = self.ot_target >= 0
            if active_ot.any():
                tgt = np.clip(self.ot_target, 0, n - 1)
                d_of_target = p_d[idx_n, tgt]
                ot_line = d_of_target + self.ot_side * (
                    A.CAR_WIDTH + A.OVERTAKE_SIDE_CLEARANCE
                )
                d_target = np.where(active_ot, ot_line, d_target)

            # Corner side for defensive positioning: inside is the direction of turn.
            kappa_ahead = geo.curvature((self.s + 90.0) % self.L)
            inside = np.where(np.abs(kappa_ahead) > 1e-9, np.sign(kappa_ahead),
                              np.sign(np.where(np.abs(kappa) > 1e-9, kappa, 1.0)))
            defend_bias = inside * usable * 0.55 * self.p["defensive_tendency"]
            d_target = np.where(self.defending & ~active_ot,
                                line + defend_bias, d_target)

            if self.yielding.any():
                yield_dir = np.where(self.d >= 0, 1.0, -1.0)
                d_target = np.where(self.yielding,
                                    self.d + yield_dir * 1.6, d_target)

            # Hold a car's width. Any car roughly alongside is given clearance,
            # independent of who is attacking whom — this is ordinary racecraft, and
            # without it two agents will happily settle 1.9 m apart, which is
            # metal-on-metal for a 2.0 m wide car.
            # Separation is judged on TRUE relative position, not the delayed view
            # used everywhere else in this method. That is deliberate: reaction time
            # models the cost of reading a situation developing at a distance, but a
            # car physically alongside is sensed peripherally and continuously.
            # Applying the perception delay here instead made the pair's separation
            # oscillate around its 2.9 m target by more than the 0.9 m of slack that
            # exists before two 2.0 m wide cars touch, and a third of all committed
            # passes ended in contact as a result.
            ds_true = (self.s[None, :] - self.s[:, None] + half_L) % self.L - half_L
            np.fill_diagonal(ds_true, INF)
            dd_true = self.d[None, :] - self.d[:, None]
            near_side = (np.abs(ds_true) < A.CAR_LENGTH * 1.5) & (np.abs(dd_true) < 7.0)
            dd_abs = np.where(near_side, np.abs(dd_true), INF)
            j_side = np.argmin(dd_abs, axis=1)
            has_side = dd_abs[idx_n, j_side] < INF
            need = A.CAR_WIDTH + A.SIDE_MIN_CLEARANCE
            too_close = has_side & (dd_abs[idx_n, j_side] < need)
            if too_close.any():
                dd_side = dd_true[idx_n, j_side]
                away = np.where(dd_side >= 0, -1.0, 1.0)
                sep_target = self.d[j_side] + away * need
                d_target = np.where(too_close, sep_target, d_target)

                # If the clearance cannot be created because there is no room on
                # that side, the car that is behind on the road backs out. Two cars
                # that cannot fit side by side do not keep trying: one lifts. Where
                # neither can (a genuinely too-narrow corner), contact follows, and
                # that is the interaction the search is looking for.
                room_away = np.where(away > 0, usable - self.d, usable + self.d)
                squeezed = too_close & (room_away < A.SIDE_MIN_CLEARANCE)
                lift = squeezed & (ds_true[idx_n, j_side] > 0)
                brake_level = np.where(lift, np.maximum(brake_level, 0.45),
                                       brake_level)
                self.squeeze_lifts += int(lift.sum())

            d_target = d_target + self.err.line_bias
            d_target = np.clip(d_target, -usable, usable)

            # ---- collision avoidance override ----------------------------
            # Avoidance is evaluated on the perceived world, so an agent with a
            # long reaction time acts on a situation that has already developed.
            ttc_perc = ttc_from_relative(
                ds, dd, dv, p_lat - self.lat_rate[:, None]
            )
            j_crit = np.argmin(ttc_perc, axis=1)
            ttc_min_i = ttc_perc[idx_n, j_crit]
            ds_crit = ds[idx_n, j_crit]
            dd_crit = dd[idx_n, j_crit]

            # The right response depends on the geometry of the threat, and getting
            # this wrong is what made an earlier version of this model deadlock:
            # two cars running alongside sit at a permanently low TTC, so treating
            # that as a rear-end emergency put the whole field on the brakes for
            # the rest of the run.
            alongside = np.abs(ds_crit) < A.CAR_LENGTH * 2.0
            threat_ahead = ds_crit > 0
            avoid_long = (ttc_min_i < A.AVOIDANCE_TTC) & threat_ahead & ~alongside
            avoid_lat = (ttc_min_i < A.AVOIDANCE_TTC_LATERAL) & alongside
            # A car being caught from behind cannot help by braking; it can only
            # leave room.
            avoid_behind = (
                (ttc_min_i < A.AVOIDANCE_TTC) & ~threat_ahead & ~alongside
            )
            avoid = avoid_long | avoid_lat | avoid_behind

            if avoid.any():
                brake_level = np.where(avoid_long, 1.0, brake_level)
                brake_level = np.where(
                    avoid_lat,
                    np.maximum(brake_level, A.AVOIDANCE_LATERAL_LIFT),
                    brake_level,
                )
                escape = np.where(dd_crit >= 0, -1.0, 1.0)
                room = np.where(escape > 0, usable - self.d, usable + self.d)
                escape = np.where(room > A.CAR_WIDTH * 0.6, escape, -escape)
                d_target = np.where(
                    avoid,
                    np.clip(self.d + escape * 2.2, -usable, usable),
                    d_target,
                )
                # An attacker abandons a move it can no longer complete: either it
                # is on a rear-end course, or it has run out of lateral room.
                out_of_room = avoid_lat & (
                    usable - np.abs(self.d) < A.CAR_WIDTH * 0.35
                )
                abort = active_ot & (avoid_long | out_of_room)
                for i in np.nonzero(abort)[0]:
                    self.n_ot_abort += 1
                    self._event(
                        t, step, EventType.OVERTAKE_ABORTED, Severity.WARNING, seg[i],
                        int(i), int(self.ot_target[i]),
                        detail=dict(ttc_at_abort=round(float(ttc_min_i[i]), 3)),
                    )
                self.ot_cooldown = np.where(abort, t + A.OVERTAKE_COOLDOWN,
                                            self.ot_cooldown)
                self.ot_target = np.where(abort, -1, self.ot_target)

            # Overtake resolution: completed, stalled, or out of room.
            if active_ot.any():
                tgt = np.clip(self.ot_target, 0, n - 1)
                cur_gap = ds[idx_n, tgt]
                # Progress is measured against the best gap achieved so far, not
                # against the previous timestep: with delayed perception the gap
                # oscillates, and a step-to-step test reads every wobble as a stall.
                gaining = active_ot & (cur_gap < self.ot_best_gap - 0.05)
                self.ot_until = np.where(
                    gaining,
                    np.maximum(self.ot_until, t + A.OVERTAKE_PROGRESS_WINDOW),
                    self.ot_until,
                )
                self.ot_best_gap = np.where(
                    active_ot, np.minimum(self.ot_best_gap, cur_gap), INF
                )
                passed = active_ot & (cur_gap < -A.CAR_LENGTH * 1.2)
                expired = active_ot & (t > self.ot_until)
                for i in np.nonzero(passed)[0]:
                    self.n_ot_done += 1
                    self._event(t, step, EventType.OVERTAKE_COMPLETE, Severity.NORMAL,
                                seg[i], int(i), int(tgt[i]))
                for i in np.nonzero(expired & ~passed)[0]:
                    self.n_ot_abort += 1
                    self._event(t, step, EventType.OVERTAKE_ABORTED, Severity.NORMAL,
                                seg[i], int(i), int(tgt[i]),
                                detail=dict(reason="attempt stalled, no longer gaining"))
                done = passed | expired
                self.ot_cooldown = np.where(done, t + A.OVERTAKE_COOLDOWN,
                                            self.ot_cooldown)
                self.ot_target = np.where(done, -1, self.ot_target)

            # ---- 6. integrate --------------------------------------------
            drag = self._drag_accel(self.v, slip)
            a_pow = np.minimum(self.traction_accel * grip,
                               self.engine_power_w / (self.car_mass * np.maximum(self.v, 8.0)))
            throttle = np.where(brake_level > 0.02, 0.0,
                                np.where(self.v < v_target * 0.995, 1.0, 0.25))
            accel = throttle * a_pow - drag - brake_level * a_brake_max
            accel = np.where(self.err.spinning, -a_brake_max * 0.55, accel)

            # Cornering load, friction ellipse, and running wide when overloaded.
            lat_need = self.v ** 2 / np.maximum(R_here, 1.0)
            corner_use = np.clip(lat_need / np.maximum(a_lat_max, 1.0), 0.0, 1.4)
            excess = np.maximum(lat_need - a_lat_max, 0.0)
            understeer = -np.sign(np.where(np.abs(kappa) > 1e-9, kappa, 1.0)) * excess * 0.16

            budget = 1.0 - brake_level ** 2 - np.minimum(corner_use, 1.0) ** 2
            lat_capacity = np.sqrt(np.clip(budget, 0.02, 1.0))
            max_lat = A.MAX_LATERAL_RATE * lat_capacity
            line_gain = 2.0 + 1.6 * self.p["line_change_tendency"]
            # Proportional term, additionally capped by the rate from which the
            # remaining error can still be arrested: v <= sqrt(2 * a * |error|).
            # Without this the controller overshoots its lateral target by over a
            # metre, which between two cars 2.9 m apart is contact — it was the
            # single largest source of spurious collisions in this model.
            err_d = d_target - self.d
            arrest = np.sqrt(2.0 * A.LATERAL_JERK_LIMIT * np.abs(err_d))
            want = np.sign(err_d) * np.minimum(np.abs(err_d) * line_gain, arrest)
            want = np.clip(want, -max_lat, max_lat)
            self.lat_rate += np.clip(
                want - self.lat_rate,
                -A.LATERAL_JERK_LIMIT * dt, A.LATERAL_JERK_LIMIT * dt,
            )
            lat_total = self.lat_rate + understeer
            lat_total = np.where(
                self.err.spinning,
                lat_total - np.sign(np.where(np.abs(kappa) > 1e-9, kappa, 1.0))
                * A.ERROR_EFFECTS["spin_lateral_m"] * 0.8,
                lat_total,
            )

            prev_v = self.v.copy()
            self.v = np.clip(self.v + accel * dt, 3.0, 110.0)
            self.v = np.where(excess > 0, self.v - excess * 0.012 * dt * 10, self.v)
            self.a = (self.v - prev_v) / dt
            self.s = self.s + self.v * dt
            self.d = self.d + lat_total * dt
            self.dist_total += self.v * dt
            wrapped = self.s >= self.L
            self.lap += wrapped.astype(np.int32)
            self.s = self.s % self.L

            decel = np.maximum(-self.a, 0.0)
            self.max_decel = max(self.max_decel, float(decel.max()))

            # ---- Apex Passport: team car telemetry (peak g, braking energy) --
            if self.team_idx is not None:
                i = self.team_idx
                combined_g = float(np.sqrt(decel[i] ** 2 + lat_need[i] ** 2) / G)
                self.team_peak_g = max(self.team_peak_g, combined_g)
                if decel[i] > 0.5:  # meaningful braking, not a lift-off
                    energy_j = float(self.car_mass[i] * decel[i] * prev_v[i] * dt)
                    lap_i = int(self.lap[i])
                    self.team_braking_energy_by_lap[lap_i] = (
                        self.team_braking_energy_by_lap.get(lap_i, 0.0) + energy_j
                    )

            # ---- 7. excursions, barriers, contact ------------------------
            off = np.abs(self.d) > halfw
            newly_off = off & ~self.was_off
            runoff = geo.runoff(self.s)
            barrier_hit = np.abs(self.d) > (halfw + runoff)
            for i in np.nonzero(newly_off)[0]:
                self.n_off_track += 1
                self._event(
                    t, step, EventType.OFF_TRACK,
                    Severity.INCIDENT if barrier_hit[i] else Severity.WARNING,
                    seg[i], int(i), None,
                    off_track=True,
                    detail=dict(
                        lateral_offset=round(float(self.d[i]), 2),
                        half_width=round(float(halfw[i]), 2),
                        runoff_available=round(float(runoff[i]), 1),
                        barrier_strike=bool(barrier_hit[i]),
                        speed=round(float(self.v[i]), 1),
                    ),
                )
            if barrier_hit.any():
                self.n_barrier += int(barrier_hit.sum())
                self.v = np.where(barrier_hit, self.v * 0.30, self.v)
            self.d = np.clip(self.d, -(halfw + runoff), halfw + runoff)
            self.lat_rate = np.where(off, self.lat_rate * 0.4, self.lat_rate)
            self.was_off = off

            # ---- Apex Passport: team car kerb-strike proxy --------------------
            # This engine has no explicit kerb geometry, only track width and
            # off-track/barrier thresholds. A kerb strike is approximated as
            # running beyond KERB_EDGE_FRAC of the half-width while still
            # technically on track -- the zone a real kerb occupies on most
            # circuits. Severity scales with how far past that fraction and is
            # a labelled proxy, not a measured kerb-load figure.
            if self.team_idx is not None:
                i = self.team_idx
                KERB_EDGE_FRAC = 0.85
                on_kerb = (not bool(off[i])) and abs(float(self.d[i])) > halfw[i] * KERB_EDGE_FRAC
                if on_kerb and not self.team_was_kerb:
                    severity = float(np.clip(
                        (abs(float(self.d[i])) / halfw[i] - KERB_EDGE_FRAC) / (1.0 - KERB_EDGE_FRAC),
                        0.0, 1.0,
                    ))
                    self.team_kerb_strikes.append(dict(
                        t=round(float(t), 3), segment_index=int(seg[i]),
                        location=self.track.segments[int(seg[i])].name,
                        lateral_offset=round(float(self.d[i]), 2),
                        half_width=round(float(halfw[i]), 2),
                        speed=round(float(self.v[i]), 1), severity=round(severity, 3),
                    ))
                self.team_was_kerb = on_kerb

            for i in np.nonzero(self.err.spinning & ~self.spun)[0]:
                self.spun[i] = True
                self._event(t, step, EventType.SPIN, Severity.INCIDENT, seg[i],
                            int(i), None,
                            detail=dict(speed_at_spin=round(float(self.v[i]), 1),
                                        grip=round(float(grip[i]), 3)))

            # ---- 8. surrogate safety -------------------------------------
            # The grid is artificial; the opening seconds are simulated but not
            # counted. See assumptions.WARMUP.
            counting = t >= A.WARMUP
            # Measured on ground truth, not on any agent's delayed view: the
            # analyser is an omniscient reader of trajectories, exactly as SSAM is
            # a reader of a simulation's trajectory file.
            ttc = pairwise_ttc(self.s, self.d, self.v, self.lat_rate, self.L)
            closing = closing_speed_matrix(self.s, self.d, self.v, self.lat_rate, self.L)
            gap_long = (self.s[None, :] - self.s[:, None] + half_L) % self.L - half_L
            heading = geo.heading(self.s)

            flagged = (ttc <= A.TTC_CONFLICT_THRESHOLD) if counting \
                else np.zeros_like(ttc, dtype=bool)
            if flagged.any():
                self.max_closing = max(
                    self.max_closing, float(np.max(np.where(flagged, closing, 0.0)))
                )
                decisions = self._decision_labels(
                    brake_level, throttle, avoid, active_ot, commit
                )
                self.acc.observe(
                    t, step, ttc, closing, decel, lat_total, heading, seg, gap_long,
                    self.ot_target >= 0, self.defending, decisions,
                )

            # Contact: actual box overlap.
            overlap = (np.abs(gap_long) < A.CAR_LENGTH) & \
                      (np.abs(self.d[None, :] - self.d[:, None]) < A.CAR_WIDTH)
            np.fill_diagonal(overlap, False)
            if not counting:
                overlap[:] = False
            for i, j in np.argwhere(overlap):
                if i >= j:
                    continue
                key = (int(i), int(j))
                if t - self.collision_cooldown.get(key, -9.0) < 1.0:
                    continue
                self.collision_cooldown[key] = t
                cs = float(closing[i, j])
                lat_overlap = A.CAR_WIDTH - abs(float(self.d[j] - self.d[i]))
                severe = (
                    cs >= A.CONTACT_SEVERE_CLOSING_SPEED
                    or lat_overlap >= A.CONTACT_SEVERE_OVERLAP
                )
                detail = dict(
                    longitudinal_overlap=round(float(gap_long[i, j]), 2),
                    lateral_overlap_depth=round(lat_overlap, 3),
                    lateral_separation=round(float(self.d[j] - self.d[i]), 2),
                    closing_speed_at_contact=round(cs, 2),
                    speed_a=round(float(self.v[i]), 1),
                    speed_b=round(float(self.v[j]), 1),
                    in_corner=bool(geo.seg_is_corner[seg[i]]),
                    lateral_grip_budget=round(float(lat_capacity[i]), 3),
                )
                if self.team_idx is not None and self.team_idx in (int(i), int(j)):
                    self.team_contacts.append(dict(
                        t=round(float(t), 3), segment_index=int(seg[i]),
                        location=self.track.segments[int(seg[i])].name,
                        other_driver=self.profiles[int(j if i == self.team_idx else i)].id,
                        severe=bool(severe), impact_speed=round(cs, 2),
                        **{k: detail[k] for k in
                           ("longitudinal_overlap", "lateral_overlap_depth", "in_corner")},
                    ))
                if severe:
                    self.n_collisions += 1
                    self.acc.mark_collision(int(i), int(j))
                    self._event(
                        t, step, EventType.COLLISION, Severity.INCIDENT, seg[i],
                        int(i), int(j), collision=True, min_ttc=0.0,
                        closing_speed=round(cs, 2), detail=detail,
                    )
                else:
                    # Wheel-to-wheel contact: recorded, counted separately, and left
                    # to be classified by its surrogate measures rather than being
                    # promoted to an incident on the strength of box overlap alone.
                    self.n_light_contacts += 1
                    self._event(
                        t, step, EventType.LIGHT_CONTACT, Severity.WARNING, seg[i],
                        int(i), int(j), collision=False, min_ttc=0.0,
                        closing_speed=round(cs, 2), detail=detail,
                    )
                if severe:
                    self.v[i] *= 0.72
                    self.v[j] *= 0.80
                else:
                    self.v[i] *= 0.985
                    self.v[j] *= 0.99
                kick = np.sign(self.d[i] - self.d[j])
                kick = kick if kick != 0 else 1.0
                push = 0.9 if severe else 0.35
                self.d[i] += kick * push
                self.d[j] -= kick * push

            if counting:
                self.pet.update(t, self.s, self.d, seg)

            # Discrete braking / evasive events.
            # Edge-triggered: one event per braking episode, not one per timestep.
            emerg = decel >= A.EMERGENCY_BRAKING_THRESHOLD
            emerg_new = emerg & ~self.was_emergency_braking
            self.was_emergency_braking = emerg
            for i in np.nonzero(emerg_new)[0]:
                self._event(t, step, EventType.EMERGENCY_BRAKING, Severity.CRITICAL,
                            seg[i], int(i), None,
                            max_deceleration=round(float(decel[i]), 2),
                            detail=dict(g=round(float(decel[i]) / G, 2)))
            evasive_now = (np.abs(lat_total) >= A.EVASIVE_LATERAL_THRESHOLD) & avoid
            for i in np.nonzero(evasive_now & ~self.evasive_steps)[0]:
                self.n_evasive_events += 1
                self._event(t, step, EventType.EVASIVE_MANOEUVRE, Severity.CRITICAL,
                            seg[i], int(i), int(j_crit[i]), evasive_action=True,
                            min_ttc=round(float(ttc_min_i[i]), 3),
                            lateral_rate=round(float(lat_total[i]), 2))
            self.evasive_steps = evasive_now

            # ---- density and recording -----------------------------------
            near = (np.abs(gap_long) < 75.0)
            np.fill_diagonal(near, False)
            self.density_samples.append(float(np.clip(near.sum(1).mean() / 4.0, 0, 1)))

            if self.record_trajectory:
                self.tr_s[step] = self.s
                self.tr_d[step] = self.d
                self.tr_v[step] = self.v
                self.tr_a[step] = self.a
                self.tr_th[step] = throttle
                self.tr_br[step] = brake_level
                self.tr_lat[step] = lat_total
                self.tr_seg[step] = seg
                self.tr_dec[step] = self._decision_codes(
                    brake_level, throttle, avoid, self.ot_target >= 0, commit
                )
            else:
                self.tr_seg[step] = seg

            # advance history
            self.head = (self.head + 1) % self.buf_len
            self.h_s[self.head] = self.s
            self.h_d[self.head] = self.d
            self.h_v[self.head] = self.v
            self.h_lat[self.head] = lat_total

        return self._finalise(time.perf_counter() - t0)

    # ======================================================================
    # Decision labelling
    # ======================================================================
    def _decision_codes(self, brake_level, throttle, avoid, active_ot, commit):
        code = np.full(self.n, DECISION_CODES[Decision.MAINTAIN_LINE.value],
                       dtype=np.int8)
        lat = self.lat_rate
        code = np.where(throttle > 0.5, DECISION_CODES[Decision.ACCELERATE.value], code)
        code = np.where((throttle <= 0.5) & (brake_level <= 0.02),
                        DECISION_CODES[Decision.COAST.value], code)
        code = np.where(np.abs(lat) > 1.2,
                        np.where(lat > 0, DECISION_CODES[Decision.MOVE_LEFT.value],
                                 DECISION_CODES[Decision.MOVE_RIGHT.value]), code)
        code = np.where(brake_level > 0.15, DECISION_CODES[Decision.BRAKE.value], code)
        code = np.where(self.defending,
                        np.where(self.d >= 0,
                                 DECISION_CODES[Decision.DEFEND_INSIDE.value],
                                 DECISION_CODES[Decision.DEFEND_OUTSIDE.value]), code)
        code = np.where(self.yielding, DECISION_CODES[Decision.YIELD.value], code)
        code = np.where(active_ot,
                        DECISION_CODES[Decision.INITIATE_OVERTAKE.value], code)
        code = np.where(commit,
                        DECISION_CODES[Decision.INITIATE_OVERTAKE.value], code)
        code = np.where(avoid, DECISION_CODES[Decision.AVOID_COLLISION.value], code)
        return code

    def _decision_labels(self, brake_level, throttle, avoid, active_ot, commit):
        codes = self._decision_codes(brake_level, throttle, avoid, active_ot, commit)
        return [CODE_TO_DECISION[int(c)] for c in codes]

    # ======================================================================
    def _event(self, t, step, etype, severity, seg_idx, a, b, **kw):
        self.events.append(
            dict(
                t=round(float(t), 3), timestep=int(step),
                event_type=etype.value, severity=severity.value,
                segment_index=int(seg_idx),
                location=self.track.segments[int(seg_idx)].name,
                driver_a=self.profiles[a].id,
                driver_b=self.profiles[b].id if b is not None else None,
                driver_a_index=int(a),
                driver_b_index=int(b) if b is not None else None,
                **kw,
            )
        )

    # ======================================================================
    def _finalise(self, wall_s: float) -> RunResult:
        from .safety import classify_severity, scsi

        conflicts: list[dict] = []
        n_evasive = 0
        for (i, j), rec in self.acc.pairs.items():
            pet_key = (min(i, j), max(i, j))
            pet_rec = self.pet.pair_min.get(pet_key)
            min_pet = pet_rec[0] if pet_rec else None
            ctype = classify_conflict_type(
                rec.heading_a, rec.heading_b, rec.lat_a, rec.lat_b,
                rec.long_gap, rec.overtaking, rec.defending,
            )
            sev = classify_severity(
                rec.min_ttc, min_pet, rec.collision,
                bool(self.was_off[i] or self.was_off[j]),
                bool(self.spun[i] or self.spun[j]),
                rec.max_decel, rec.evasive,
            )
            score = scsi(rec.min_ttc, min_pet, rec.max_closing, rec.max_decel)
            if rec.evasive:
                n_evasive += 1
            conflicts.append(
                dict(
                    driver_a=self.profiles[i].id, driver_b=self.profiles[j].id,
                    driver_a_index=int(i), driver_b_index=int(j),
                    archetype_a=self.profiles[i].archetype,
                    archetype_b=self.profiles[j].archetype,
                    conflict_type=ctype.value, severity=sev.value,
                    t_min_ttc=round(rec.t_min_ttc, 3), timestep=rec.step_min_ttc,
                    segment_index=rec.segment_at_min,
                    location=self.track.segments[rec.segment_at_min].name,
                    turn_number=self.track.segments[rec.segment_at_min].turn_number,
                    min_ttc=round(rec.min_ttc, 4),
                    min_pet=round(min_pet, 4) if min_pet is not None else None,
                    closing_speed=round(rec.max_closing, 3),
                    max_deceleration=round(rec.max_decel, 3),
                    evasive_action=rec.evasive, collision=rec.collision,
                    scsi=round(score, 5),
                    a_decision=rec.a_decision, b_decision=rec.b_decision,
                    samples=rec.samples,
                )
            )

        # Attribute each conflict to the segment where its TTC bottomed out, so a
        # segment's count is a number of distinct conflicts rather than a number of
        # timesteps (which would simply reward slow corners).
        for c in conflicts:
            k = c["segment_index"]
            self.seg_conflicts[k] = self.seg_conflicts.get(k, 0) + 1

        conflicts.sort(key=lambda c: c["min_ttc"])
        min_pet_overall = None if self.pet.min_pet >= INF else round(self.pet.min_pet, 4)

        team_telemetry = None
        if self.team_idx is not None:
            team_telemetry = dict(
                driver_index=self.team_idx,
                car_profile=self.team_car_profile.to_dict(),
                kerb_strikes=self.team_kerb_strikes,
                n_kerb_strikes=len(self.team_kerb_strikes),
                peak_g=round(self.team_peak_g, 3),
                braking_energy_by_lap_j={
                    k: round(v, 1) for k, v in self.team_braking_energy_by_lap.items()
                },
                contacts=self.team_contacts,
                n_contacts=len(self.team_contacts),
            )

        return RunResult(
            scenario=self.sc,
            environment=self.env,
            profiles=self.profiles,
            n_steps=self.n_steps,
            dt=self.dt,
            wall_time_ms=wall_s * 1000.0,
            traj_s=self.tr_s, traj_d=self.tr_d, traj_v=self.tr_v, traj_a=self.tr_a,
            traj_throttle=self.tr_th, traj_brake=self.tr_br, traj_lat=self.tr_lat,
            traj_seg=self.tr_seg, traj_decision=self.tr_dec,
            conflicts=conflicts,
            events=self.events,
            pet_pair_min={f"{a}-{b}": v for (a, b), v in self.pet.pair_min.items()},
            min_pet=min_pet_overall if min_pet_overall is not None else INF,
            error_counts=self.err.total_counts(),
            error_log=self.err.log,
            dominant_error=self.err.dominant_kind(),
            measured_traffic_density=float(np.mean(self.density_samples))
            if self.density_samples else 0.0,
            max_closing_speed=self.max_closing,
            max_deceleration=self.max_decel,
            n_collisions=self.n_collisions,
            n_light_contacts=self.n_light_contacts,
            n_off_track=self.n_off_track,
            n_spins=int(self.spun.sum()),
            n_barrier_strikes=self.n_barrier,
            n_overtake_attempts=self.n_ot_attempt,
            n_overtakes_completed=self.n_ot_done,
            n_overtakes_aborted=self.n_ot_abort,
            n_evasive=n_evasive,
            laps_completed=float(self.dist_total.max() / self.L),
            segment_conflict_counts=self.seg_conflicts,
            track_id=self.track.id,
            team_car_telemetry=team_telemetry,
        )
