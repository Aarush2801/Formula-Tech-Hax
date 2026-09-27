/** Number and unit formatting. Kept in one place so units never drift. */

export const nf = (v: number | null | undefined, d = 0): string =>
  v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : v.toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });

export const int = (v: number | null | undefined): string => nf(v, 0);

export const sec = (v: number | null | undefined, d = 2): string =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v.toFixed(d)} s`;

export const ms = (v: number | null | undefined): string =>
  v === null || v === undefined ? "—" : v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(1)} s`;

export const mps = (v: number | null | undefined, d = 1): string =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v.toFixed(d)} m/s`;

export const kph = (v: number | null | undefined, d = 0): string =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${(v * 3.6).toFixed(d)} km/h`;

export const gforce = (v: number | null | undefined, d = 1): string =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${(v / 9.81).toFixed(d)} g`;

export const metres = (v: number | null | undefined, d = 1): string =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v.toFixed(d)} m`;

export const pct = (v: number | null | undefined, d = 1): string =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(d)}%`;

export const dec = (v: number | null | undefined, d = 2): string =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : v.toFixed(d);

export const signed = (v: number | null | undefined, d = 3): string =>
  v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : `${v >= 0 ? "+" : ""}${v.toFixed(d)}`;

export const rho = (v: number | null | undefined): string => signed(v, 3);

export const clock = (t: number | null | undefined): string => {
  if (t === null || t === undefined || !Number.isFinite(t)) return "—";
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(2).padStart(5, "0")}`;
};

export const ago = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "—";
  const d = (Date.now() - then) / 1000;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
};

export const datetime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return "—";
  return d.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
};

/** "347 / 10,000 runs" — the project's canonical way of stating a recurrence. */
export const outOf = (n: number, total: number): string =>
  `${int(n)} / ${int(total)}`;

export const titleCase = (s: string | null | undefined): string =>
  !s ? "—" : s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const snakeToWords = (s: string | null | undefined): string =>
  !s ? "—" : s.replace(/_/g, " ");
