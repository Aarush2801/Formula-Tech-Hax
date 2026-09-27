"""Human-error model.

Errors are sampled as discrete events and then *persist* for a window, during
which they modify the agent's effective parameters. That persistence is what
makes them matter: a delayed reaction that lasts 1.5 s can carry an agent all the
way through a braking zone.

Two kinds of exposure drive the sampling:
  * per-corner   — braking-point errors are drawn once per braking-zone entry
  * per-second   — everything else is drawn on a fixed cadence

All rates come from ``assumptions.ERROR_RATES`` and are scaled per agent by that
agent's ``error_probability`` multiplier and per scenario by
``error_rate_multiplier``. They are modelling dials, not measured incident rates.
"""

from __future__ import annotations

import numpy as np

from . import assumptions as A

ERROR_KINDS = [
    "missed_braking_point",
    "delayed_reaction",
    "unexpected_line_change",
    "grip_loss",
    "concentration_lapse",
    "over_aggressive_overtake",
    "incorrect_defensive_response",
    "spin",
    "slow_response_to_car_ahead",
]

# Ordered, not a set. Iterating this consumes random draws, so hash-ordered
# iteration would make the RNG stream depend on PYTHONHASHSEED and break
# reproducibility across processes — which is exactly what it did.
PER_CORNER_KINDS = ("missed_braking_point", "incorrect_defensive_response")


class ErrorState:
    """Vectorised, per-agent error state with expiry timers."""

    def __init__(self, n: int, driver_error_scale: np.ndarray, rate_multiplier: float):
        self.n = n
        self.scale = driver_error_scale
        self.rate_multiplier = rate_multiplier
        self.rates = A.ERROR_RATES
        self.fx = A.ERROR_EFFECTS

        # Active-until timestamps, in simulation seconds.
        self.until = {k: np.zeros(n) for k in ERROR_KINDS}
        self.braking_offset = np.zeros(n)     # m, added to the braking point
        self.line_bias = np.zeros(n)          # m, added to the lateral target
        self.threshold_delta = np.zeros(n)    # added to the overtake threshold
        self.grip_scale = np.ones(n)
        self.reaction_scale = np.ones(n)
        self.spinning = np.zeros(n, dtype=bool)
        self.counts = {k: np.zeros(n, dtype=np.int32) for k in ERROR_KINDS}
        self.log: list[tuple[float, int, str]] = []
        self._any_active = False

    # ----------------------------------------------------------------------
    def _p(self, kind: str) -> np.ndarray:
        return np.clip(self.rates[kind] * self.scale * self.rate_multiplier, 0.0, 0.95)

    def _fire(self, kind: str, mask: np.ndarray, t: float) -> np.ndarray:
        if not mask.any():
            return mask
        idx = np.nonzero(mask)[0]
        self.counts[kind][idx] += 1
        for i in idx:
            self.log.append((round(float(t), 3), int(i), kind))
        return mask

    def sample_per_second(self, t: float, rng: np.random.Generator,
                          in_corner: np.ndarray) -> None:
        u = rng.random((len(ERROR_KINDS), self.n))
        for j, kind in enumerate(ERROR_KINDS):
            if kind in PER_CORNER_KINDS:
                continue
            hit = u[j] < self._p(kind)
            if kind == "spin":
                # A spin is only sampled where it is physically plausible: in a
                # corner, and made much more likely if grip is already lost.
                hit &= in_corner
                hit &= rng.random(self.n) < (0.25 + 0.75 * (self.grip_scale < 0.95))
            if not hit.any():
                continue
            self._fire(kind, hit, t)
            self._apply(kind, hit, t, rng)

    def sample_at_braking_zone(self, t: float, rng: np.random.Generator,
                               entering: np.ndarray) -> None:
        if not entering.any():
            return
        for kind in PER_CORNER_KINDS:
            hit = entering & (rng.random(self.n) < self._p(kind))
            if hit.any():
                self._fire(kind, hit, t)
                self._apply(kind, hit, t, rng)

    def _apply(self, kind: str, hit: np.ndarray, t: float,
               rng: np.random.Generator) -> None:
        self._any_active = True
        fx = self.fx
        if kind == "missed_braking_point":
            self.braking_offset[hit] = fx["missed_braking_point_m"]
            self.until[kind][hit] = t + 4.0
        elif kind == "delayed_reaction":
            self.reaction_scale[hit] = fx["delayed_reaction_multiplier"]
            self.until[kind][hit] = t + fx["delayed_reaction_window_s"]
        elif kind == "unexpected_line_change":
            sign = np.where(rng.random(self.n) < 0.5, -1.0, 1.0)
            self.line_bias[hit] = (sign * fx["unexpected_line_change_m"])[hit]
            self.until[kind][hit] = t + 1.2
        elif kind == "grip_loss":
            self.grip_scale[hit] = fx["grip_loss_factor"]
            self.until[kind][hit] = t + fx["grip_loss_window_s"]
        elif kind == "concentration_lapse":
            self.reaction_scale[hit] = np.maximum(
                self.reaction_scale[hit], fx["delayed_reaction_multiplier"] * 0.8
            )
            self.until[kind][hit] = t + fx["concentration_lapse_window_s"]
        elif kind == "over_aggressive_overtake":
            self.threshold_delta[hit] = fx["over_aggressive_threshold_delta"]
            self.until[kind][hit] = t + 3.0
        elif kind == "incorrect_defensive_response":
            # Defend the wrong side: flip the lateral bias.
            self.line_bias[hit] = -fx["unexpected_line_change_m"] * 1.4
            self.until[kind][hit] = t + 2.0
        elif kind == "spin":
            self.spinning[hit] = True
            self.until[kind][hit] = t + 2.5
        elif kind == "slow_response_to_car_ahead":
            self.reaction_scale[hit] = np.maximum(self.reaction_scale[hit], 2.0)
            self.until[kind][hit] = t + 1.0

    def expire(self, t: float) -> None:
        # Cheap early-out: on most timesteps no agent has an active error.
        if not self._any_active:
            return
        for kind in ERROR_KINDS:
            done = (self.until[kind] > 0) & (self.until[kind] <= t)
            if not done.any():
                continue
            self.until[kind][done] = 0.0
            if kind == "missed_braking_point":
                self.braking_offset[done] = 0.0
            elif kind in ("unexpected_line_change", "incorrect_defensive_response"):
                self.line_bias[done] = 0.0
            elif kind == "grip_loss":
                self.grip_scale[done] = 1.0
            elif kind == "over_aggressive_overtake":
                self.threshold_delta[done] = 0.0
            elif kind == "spin":
                self.spinning[done] = False
        # Reaction scale is shared by three error kinds; rebuild it from whichever
        # are still active rather than clearing it blindly.
        active = (
            (self.until["delayed_reaction"] > 0)
            | (self.until["concentration_lapse"] > 0)
            | (self.until["slow_response_to_car_ahead"] > 0)
        )
        self.reaction_scale = np.where(active, self.reaction_scale, 1.0)
        self._any_active = bool(
            any(bool((self.until[k] > 0).any()) for k in ERROR_KINDS)
        )

    # ----------------------------------------------------------------------
    def total_counts(self) -> dict[str, int]:
        return {k: int(v.sum()) for k, v in self.counts.items()}

    def dominant_kind(self) -> str | None:
        totals = self.total_counts()
        # Ignore grip_loss when picking a dominant error: it is the highest-rate
        # event by construction, so it would win every time and say nothing.
        ranked = sorted(
            ((v, k) for k, v in totals.items() if k != "grip_loss"), reverse=True
        )
        if not ranked or ranked[0][0] == 0:
            return None
        return ranked[0][1]
