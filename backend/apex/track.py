"""Track geometry.

A circuit is authored as an ordered list of segment specifications (straight /
braking zone / corner) and then *integrated* into a centreline: heading is the
running integral of curvature, position the running integral of heading.

Authoring a closed loop by hand is fiddly, so ``build_track`` runs a small
least-squares pass that nudges the straight lengths until the loop closes. The
Jacobian is exact and trivial: moving straight *i* by dL displaces the endpoint
by dL * (cos theta_i, sin theta_i). A few Gauss-Newton iterations with light
regularisation gets closure to well under a metre without visibly distorting the
authored layout.

Cars live in curvilinear coordinates (s along the centreline, d lateral from it),
which is what makes vectorised pairwise proximity tests cheap. Cartesian x/y is
produced only for rendering and for the heading-angle term of conflict typing.
"""

from __future__ import annotations

import math

import numpy as np

from . import assumptions as A
from .models import SegmentType, Track, TrackSegment

G = 9.81

# A segment spec is a dict with the authored, human-meaningful fields.
SegmentSpec = dict


def corner_speed(radius: float, grip: float = 1.0) -> float:
    """Geometric cornering speed ceiling with aerodynamic load.

    Lateral friction is speed dependent: mu(v) = mu0 + k * (v / v_ref)^2. Setting
    v^2 = mu(v) * grip * g * R and solving for v gives

        v^2 * (1 - grip * k * g * R / v_ref^2) = mu0 * grip * g * R

    The bracket goes non-positive for large radii, i.e. the corner is flat out; the
    result is capped at MAX_CORNER_SPEED in that case.
    """
    k = A.AERO_LATERAL_GAIN
    vref2 = A.AERO_REF_SPEED ** 2
    denom = 1.0 - grip * k * G * radius / vref2
    if denom <= 1e-3:
        return A.MAX_CORNER_SPEED
    v2 = A.LATERAL_MU * grip * G * radius / denom
    return float(min(math.sqrt(max(v2, 1.0)), A.MAX_CORNER_SPEED))


def lateral_accel_limit(v, grip):
    """Speed-dependent lateral acceleration ceiling, m/s^2."""
    mu = A.LATERAL_MU + A.AERO_LATERAL_GAIN * (v / A.AERO_REF_SPEED) ** 2
    return mu * grip * G


def brake_accel_limit(v, grip):
    """Speed-dependent deceleration ceiling, m/s^2."""
    mu = A.BRAKE_MU + A.AERO_BRAKE_GAIN * (v / A.AERO_REF_SPEED) ** 2
    return mu * grip * G


def _integrate(specs: list[SegmentSpec], lengths: np.ndarray, ds: float = 2.0):
    """Integrate heading and position along the authored segments."""
    x, y, theta = 0.0, 0.0, 0.0
    nodes_x, nodes_y, nodes_s, nodes_h, nodes_w = [], [], [], [], []
    straight_headings: list[tuple[int, float]] = []
    s_acc = 0.0
    bounds: list[tuple[float, float]] = []

    for i, spec in enumerate(specs):
        L = float(lengths[i])
        kappa = spec.get("curvature", 0.0)
        if spec.get("radius"):
            kappa = spec["turn_sign"] / spec["radius"]
        if abs(kappa) < 1e-9:
            straight_headings.append((i, theta))
        seg_start = s_acc
        n = max(int(math.ceil(L / ds)), 1)
        step = L / n
        for _ in range(n):
            nodes_x.append(x)
            nodes_y.append(y)
            nodes_s.append(s_acc)
            nodes_h.append(theta)
            nodes_w.append(spec["width"])
            # Midpoint integration keeps arcs visually clean at 2 m steps.
            th_mid = theta + 0.5 * kappa * step
            x += step * math.cos(th_mid)
            y += step * math.sin(th_mid)
            theta += kappa * step
            s_acc += step
        bounds.append((seg_start, s_acc))

    return (
        np.array(nodes_x), np.array(nodes_y), np.array(nodes_s),
        np.array(nodes_h), np.array(nodes_w), straight_headings, bounds,
        np.array([x, y]), theta,
    )


def _close_loop(specs: list[SegmentSpec], iterations: int = 40) -> np.ndarray:
    """Gauss-Newton adjustment of straight lengths until the loop closes."""
    lengths = np.array([s["length"] for s in specs], dtype=float)
    original = lengths.copy()

    for _ in range(iterations):
        *_, straight_headings, _, endpoint, _ = _integrate(specs, lengths, ds=8.0)
        err = endpoint  # want endpoint == origin
        if np.linalg.norm(err) < 0.05:
            break
        idx = [i for i, _ in straight_headings]
        J = np.array([[math.cos(h), math.sin(h)] for _, h in straight_headings]).T
        # Minimise ||J dL + err||^2 + lam ||dL||^2  (ridge keeps the layout honest)
        lam = 1e-3
        JT = J.T
        H = JT @ J + lam * np.eye(J.shape[1])
        delta = -np.linalg.solve(H, JT @ err)
        # Damp, and never shrink a straight below a quarter of its authored length.
        delta = np.clip(delta, -60.0, 60.0) * 0.6
        for k, i in enumerate(idx):
            lengths[i] = max(lengths[i] + delta[k], 0.25 * original[i])
    return lengths


def build_track(
    track_id: str,
    name: str,
    country: str,
    specs: list[SegmentSpec],
    width_multiplier: float = 1.0,
) -> Track:
    specs = [dict(s) for s in specs]
    for s in specs:
        s["width"] = s["width"] * width_multiplier

    total_turn = sum(
        (s["turn_sign"] * s["length"] / s["radius"]) for s in specs if s.get("radius")
    )
    if abs(abs(total_turn) - 2 * math.pi) > 0.25:
        raise ValueError(
            f"{track_id}: authored corners turn {math.degrees(total_turn):.1f} deg; "
            "a closed circuit needs ~360."
        )

    lengths = _close_loop(specs)
    (cx, cy, cs, ch, cw, _, bounds, endpoint, _) = _integrate(specs, lengths, ds=2.5)
    closure = float(np.linalg.norm(endpoint))

    segments: list[TrackSegment] = []
    turn_counter = 0
    for i, spec in enumerate(specs):
        radius = spec.get("radius")
        stype = SegmentType(spec["type"])
        turn_no = None
        if stype in (SegmentType.CORNER, SegmentType.CHICANE):
            turn_counter += 1
            turn_no = spec.get("turn_number", turn_counter)
        elif spec.get("turn_number"):
            turn_no = spec["turn_number"]
        kappa = (spec["turn_sign"] / radius) if radius else 0.0
        tgt = corner_speed(radius) if radius else spec.get("target_speed", 95.0)
        segments.append(
            TrackSegment(
                index=i,
                name=spec["name"],
                type=stype,
                length=float(lengths[i]),
                width=spec["width"],
                curvature=kappa,
                corner_radius=radius,
                target_speed=tgt,
                is_braking_zone=stype == SegmentType.BRAKING_ZONE,
                overtaking_opportunity=spec.get("overtaking_opportunity", 0.2),
                runoff_width=spec.get("runoff_width", 12.0),
                barrier_distance=spec.get("barrier_distance", 20.0),
                s_start=bounds[i][0],
                s_end=bounds[i][1],
                turn_number=turn_no,
            )
        )

    track = Track(
        id=track_id,
        name=name,
        country=country,
        length=float(cs[-1] + (cs[-1] - cs[-2])),
        segments=segments,
        centreline_x=cx.tolist(),
        centreline_y=cy.tolist(),
        centreline_s=cs.tolist(),
        centreline_heading=ch.tolist(),
        centreline_width=cw.tolist(),
    )
    track.closure_error = closure  # type: ignore[attr-defined]
    return track


class TrackGeometry:
    """Vectorised lookups over a built track, used by the engine every timestep."""

    def __init__(self, track: Track, width_multiplier: float = 1.0):
        self.track = track
        self.length = track.length
        self.cx = np.asarray(track.centreline_x)
        self.cy = np.asarray(track.centreline_y)
        self.cs = np.asarray(track.centreline_s)
        self.ch = np.asarray(track.centreline_heading)
        self.node_ds = float(self.cs[1] - self.cs[0])

        # Per-segment arrays, plus a fine-grained lookup table indexed by metre.
        self.seg_start = np.array([s.s_start for s in track.segments])
        self.seg_end = np.array([s.s_end for s in track.segments])
        self.seg_width = np.array([s.width for s in track.segments]) * width_multiplier
        self.seg_curvature = np.array([s.curvature for s in track.segments])
        self.seg_radius = np.array(
            [s.corner_radius if s.corner_radius else 1e6 for s in track.segments]
        )
        self.seg_target = np.array([s.target_speed for s in track.segments])
        self.seg_overtaking = np.array([s.overtaking_opportunity for s in track.segments])
        self.seg_runoff = np.array([s.runoff_width for s in track.segments])
        self.seg_barrier = np.array([s.barrier_distance for s in track.segments])
        self.seg_is_corner = np.array(
            [s.type in (SegmentType.CORNER, SegmentType.CHICANE) for s in track.segments]
        )
        self.n_segments = len(track.segments)

        self._res = 1.0
        n_bins = int(math.ceil(self.length / self._res))
        bins = (np.arange(n_bins) + 0.5) * self._res
        self._seg_of_bin = np.clip(
            np.searchsorted(self.seg_end, bins, side="right"), 0, self.n_segments - 1
        )
        # Geometric speed ceiling as a continuous function of s, with a lookahead
        # taken over a horizon in the engine.
        self._target_of_bin = self.seg_target[self._seg_of_bin]
        self._width_of_bin = self.seg_width[self._seg_of_bin]
        self._radius_of_bin = self.seg_radius[self._seg_of_bin]
        self._bins = bins
        self.n_bins = n_bins

        self._build_racing_line()

    # -- racing line -------------------------------------------------------
    def _build_racing_line(self) -> None:
        """Nominal racing line as a lateral offset per metre of track.

        Built from keypoints: outside the corner on approach, at the apex on the
        inside, back outside on exit. Interpolated cyclically. Agents treat this
        as their default lateral target; overtake, defensive and error offsets are
        all expressed relative to it.
        """
        margin = A.CAR_WIDTH * 0.5 + 0.35
        ks: list[float] = []
        vs: list[float] = []
        segs = self.track.segments
        for i, seg in enumerate(segs):
            if not self.seg_is_corner[i]:
                continue
            sign = 1.0 if seg.curvature > 0 else -1.0
            half = self.seg_width[i] * 0.5 - margin
            inner = sign * half * 0.92
            outer = -sign * half * 0.80
            approach = max(seg.length * 0.5, 55.0)
            exit_run = max(seg.length * 0.6, 65.0)
            ks += [seg.s_start - approach, seg.s_mid, seg.s_end + exit_run]
            vs += [outer, inner, outer]

        if not ks:
            self._line_of_bin = np.zeros(self.n_bins)
            return

        order = np.argsort(np.array(ks) % self.length)
        kk = (np.array(ks) % self.length)[order]
        vv = np.array(vs)[order]
        # Average any keypoints that landed on the same metre (tight corner pairs).
        kk_u, inv = np.unique(np.round(kk, 2), return_inverse=True)
        vv_u = np.zeros(len(kk_u))
        np.add.at(vv_u, inv, vv)
        counts = np.bincount(inv, minlength=len(kk_u))
        vv_u /= counts
        # Close the period for cyclic interpolation.
        kk_c = np.concatenate([[kk_u[-1] - self.length], kk_u, [kk_u[0] + self.length]])
        vv_c = np.concatenate([[vv_u[-1]], vv_u, [vv_u[0]]])
        raw = np.interp(self._bins, kk_c, vv_c)
        # Light smoothing so the line has no kinks for the lateral controller.
        k = 9
        kernel = np.ones(k) / k
        self._line_of_bin = np.convolve(np.concatenate([raw[-k:], raw, raw[:k]]),
                                        kernel, mode="same")[k:-k]
        # Never let the nominal line sit outside the usable track width.
        limit = self._width_of_bin * 0.5 - margin
        self._line_of_bin = np.clip(self._line_of_bin, -limit, limit)

    def racing_line(self, s: np.ndarray) -> np.ndarray:
        idx = np.floor((s % self.length) / self._res).astype(np.int64)
        return self._line_of_bin[np.clip(idx, 0, self.n_bins - 1)]

    # -- lookups -----------------------------------------------------------
    def segment_index(self, s: np.ndarray) -> np.ndarray:
        idx = np.floor((s % self.length) / self._res).astype(np.int64)
        return self._seg_of_bin[np.clip(idx, 0, self.n_bins - 1)]

    def width(self, s: np.ndarray) -> np.ndarray:
        idx = np.floor((s % self.length) / self._res).astype(np.int64)
        return self._width_of_bin[np.clip(idx, 0, self.n_bins - 1)]

    def target_speed(self, s: np.ndarray) -> np.ndarray:
        idx = np.floor((s % self.length) / self._res).astype(np.int64)
        return self._target_of_bin[np.clip(idx, 0, self.n_bins - 1)]

    def radius(self, s: np.ndarray) -> np.ndarray:
        idx = np.floor((s % self.length) / self._res).astype(np.int64)
        return self._radius_of_bin[np.clip(idx, 0, self.n_bins - 1)]

    def heading(self, s: np.ndarray) -> np.ndarray:
        i = np.clip(
            np.floor((s % self.length) / self.node_ds).astype(np.int64),
            0, len(self.ch) - 1,
        )
        return self.ch[i]

    def to_cartesian(self, s: np.ndarray, d: np.ndarray):
        """Curvilinear (s, d) -> Cartesian (x, y). Left normal is (-sin, cos)."""
        sm = s % self.length
        pos = sm / self.node_ds
        i0 = np.clip(np.floor(pos).astype(np.int64), 0, len(self.cx) - 1)
        i1 = (i0 + 1) % len(self.cx)
        f = pos - i0
        x0, y0 = self.cx[i0], self.cy[i0]
        x1, y1 = self.cx[i1], self.cy[i1]
        # Guard the wrap node, where x1,y1 jumps back to the origin.
        wrap = i1 < i0
        x1 = np.where(wrap, x0, x1)
        y1 = np.where(wrap, y0, y1)
        bx = x0 + f * (x1 - x0)
        by = y0 + f * (y1 - y0)
        th = self.ch[i0]
        return bx - d * np.sin(th), by + d * np.cos(th)

    def step_state(self, s: np.ndarray):
        """Everything the engine needs about the track at s, from one index pass.

        The engine previously called seven separate lookups per timestep, each
        recomputing the same bin index. At 20 Hz for 1,500 steps that was the
        single largest avoidable cost in the run loop.
        """
        idx = np.floor((s % self.length) / self._res).astype(np.int64)
        np.clip(idx, 0, self.n_bins - 1, out=idx)
        seg = self._seg_of_bin[idx]
        return (
            seg,
            self._width_of_bin[idx],
            self._line_of_bin[idx],
            self._radius_of_bin[idx],
            self.seg_curvature[seg],
            self.seg_overtaking[seg],
            self.seg_is_corner[seg],
        )

    def probe_radius(self, s: np.ndarray, offsets: np.ndarray) -> np.ndarray:
        """Corner radius at a set of lookahead offsets. Returns (n_cars, n_offsets).

        The engine converts these radii into per-agent speed ceilings using that
        agent's own effective grip, which is why the raw radius is what is exposed
        here rather than a precomputed speed.
        """
        probe = (s[:, None] + offsets[None, :]) % self.length
        idx = np.clip(np.floor(probe / self._res).astype(np.int64), 0, self.n_bins - 1)
        return self._radius_of_bin[idx]

    def probe_width(self, s: np.ndarray, offsets: np.ndarray) -> np.ndarray:
        probe = (s[:, None] + offsets[None, :]) % self.length
        idx = np.clip(np.floor(probe / self._res).astype(np.int64), 0, self.n_bins - 1)
        return self._width_of_bin[idx]

    def curvature(self, s: np.ndarray) -> np.ndarray:
        return self.seg_curvature[self.segment_index(s)]

    def overtaking_rating(self, s: np.ndarray) -> np.ndarray:
        return self.seg_overtaking[self.segment_index(s)]

    def runoff(self, s: np.ndarray) -> np.ndarray:
        return self.seg_runoff[self.segment_index(s)]

    def min_target_ahead(self, s: np.ndarray, horizon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Lowest speed ceiling within ``horizon`` metres ahead, and its distance.

        This is what an agent brakes for: not the ceiling where it is, but the
        tightest thing it can see coming.
        """
        n = len(s)
        step = 6.0
        max_h = float(np.max(horizon)) if n else 0.0
        offsets = np.arange(0.0, max_h + step, step)
        probe = (s[:, None] + offsets[None, :]) % self.length
        idx = np.clip(
            np.floor(probe / self._res).astype(np.int64), 0, self.n_bins - 1
        )
        tgt = self._target_of_bin[idx]
        tgt = np.where(offsets[None, :] <= horizon[:, None], tgt, np.inf)
        j = np.argmin(tgt, axis=1)
        rows = np.arange(n)
        return tgt[rows, j], offsets[j]


def build_zones(track) -> dict[int, dict]:
    """Group segments into named zones, one per corner.

    A "zone" is a corner together with its braking zone and its exit — the stretch
    of circuit over which one braking-and-turning event plays out. Each segment is
    assigned to the corner nearest it along the centreline, cyclically.

    This grouping exists because conflict patterns are not segment-sized. A pass
    that starts under braking, develops at the apex and resolves on the exit spans
    three segments, and keying discovered patterns by raw segment would split one
    recurring situation into three rarer ones.
    """
    corners = [sg for sg in track.segments if sg.corner_radius is not None]
    if not corners:
        return {}
    L = track.length
    zones: dict[int, dict] = {}
    for c in corners:
        zones[c.turn_number] = dict(
            turn_number=c.turn_number,
            key=f"T{c.turn_number}",
            name=f"Turn {c.turn_number} zone",
            corner_name=c.name,
            corner_segment_index=c.index,
            corner_radius=c.corner_radius,
            width=c.width,
            min_width=c.width,
            runoff_width=c.runoff_width,
            barrier_distance=c.barrier_distance,
            target_speed=c.target_speed,
            overtaking_opportunity=c.overtaking_opportunity,
            segment_indices=[],
            s_start=c.s_start,
            s_end=c.s_end,
        )
    mapping: dict[int, int] = {}
    for sg in track.segments:
        best, best_d = None, 1e18
        for c in corners:
            d = abs((sg.s_mid - c.s_mid + L / 2) % L - L / 2)
            if d < best_d:
                best, best_d = c, d
        mapping[sg.index] = best.turn_number
        z = zones[best.turn_number]
        z["segment_indices"].append(sg.index)
        z["min_width"] = min(z["min_width"], sg.width)
        z["overtaking_opportunity"] = max(
            z["overtaking_opportunity"], sg.overtaking_opportunity
        )
    for z in zones.values():
        idxs = z["segment_indices"]
        z["s_start"] = min(track.segments[i].s_start for i in idxs)
        z["s_end"] = max(track.segments[i].s_end for i in idxs)
        z["length"] = sum(track.segments[i].length for i in idxs)
    return dict(zones=zones, segment_to_zone=mapping)  # type: ignore[return-value]
