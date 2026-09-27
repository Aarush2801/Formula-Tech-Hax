"use client";

/**
 * App-wide state: which batch is being analysed, the metadata every screen needs,
 * and the registry of running jobs.
 *
 * The selected batch is the single most important piece of context in the product.
 * Every number on every screen is qualified by it, which is why the batch selector
 * lives in the top bar and never in a page.
 */

import React from "react";

import {
  api,
  ApiError,
  BatchRow,
  JobSnapshot,
  Meta,
  TrackGeometry,
  streamJob,
} from "./api";

interface Ctx {
  meta: Meta | null;
  metaError: unknown;
  batches: BatchRow[];
  batchId: string | null;
  batch: BatchRow | null;
  setBatchId: (id: string) => void;
  refreshBatches: () => Promise<void>;
  track: TrackGeometry | null;
  trackId: string;
  setTrackId: (id: string) => void;
  jobs: JobSnapshot[];
  watchJob: (job: JobSnapshot) => void;
  loading: boolean;
  apiOnline: boolean | null;
}

const AppCtx = React.createContext<Ctx | null>(null);

const LS_BATCH = "apex.batchId";

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [meta, setMeta] = React.useState<Meta | null>(null);
  const [metaError, setMetaError] = React.useState<unknown>(null);
  const [batches, setBatches] = React.useState<BatchRow[]>([]);
  const [batchId, setBatchIdState] = React.useState<string | null>(null);
  const [track, setTrack] = React.useState<TrackGeometry | null>(null);
  const [trackId, setTrackId] = React.useState("vale_park");
  const [jobs, setJobs] = React.useState<JobSnapshot[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [apiOnline, setApiOnline] = React.useState<boolean | null>(null);

  const refreshBatches = React.useCallback(async () => {
    const res = await api.batches(60);
    setBatches(res.batches);
    return;
  }, []);

  const setBatchId = React.useCallback((id: string) => {
    setBatchIdState(id);
    try {
      localStorage.setItem(LS_BATCH, id);
    } catch {
      /* private browsing */
    }
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [m, b] = await Promise.all([api.meta(), api.batches(60)]);
        if (cancelled) return;
        setMeta(m);
        setBatches(b.batches);
        setApiOnline(true);
        let stored: string | null = null;
        try {
          stored = localStorage.getItem(LS_BATCH);
        } catch {
          /* ignore */
        }
        const usable = b.batches.filter(
          (x) => x.status === "complete" && x.n_runs_completed > 0
        );
        const pick =
          (stored && usable.find((x) => x.id === stored)?.id) ??
          usable.find((x) => x.mode === "monte_carlo")?.id ??
          usable[0]?.id ??
          null;
        if (pick) setBatchIdState(pick);
      } catch (e) {
        if (!cancelled) {
          setMetaError(e);
          setApiOnline(e instanceof ApiError && e.status === 0 ? false : true);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    api
      .track(trackId)
      .then((t) => !cancelled && setTrack(t))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [trackId]);

  const watchJob = React.useCallback(
    (job: JobSnapshot) => {
      setJobs((prev) => [job, ...prev.filter((j) => j.job_id !== job.job_id)]);
      streamJob(
        job.job_id,
        (snap) =>
          setJobs((prev) =>
            prev.map((j) => (j.job_id === snap.job_id ? { ...j, ...snap } : j))
          ),
        (snap) => {
          setJobs((prev) =>
            prev.map((j) => (j.job_id === snap.job_id ? { ...j, ...snap } : j))
          );
          refreshBatches().catch(() => undefined);
          if (snap.status === "complete" && snap.batch_id) setBatchId(snap.batch_id);
        }
      );
    },
    [refreshBatches, setBatchId]
  );

  const batch = React.useMemo(
    () => batches.find((b) => b.id === batchId) ?? null,
    [batches, batchId]
  );

  const value: Ctx = {
    meta,
    metaError,
    batches,
    batchId,
    batch,
    setBatchId,
    refreshBatches,
    track,
    trackId,
    setTrackId,
    jobs,
    watchJob,
    loading,
    apiOnline,
  };

  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>;
}

export function useApp(): Ctx {
  const c = React.useContext(AppCtx);
  if (!c) throw new Error("useApp must be used inside AppProvider");
  return c;
}

/** Small fetch hook with loading/error state, keyed on its dependencies. */
export function useFetch<T>(
  fn: (() => Promise<T>) | null,
  deps: unknown[]
): { data: T | null; error: unknown; loading: boolean; reload: () => void } {
  const [data, setData] = React.useState<T | null>(null);
  const [error, setError] = React.useState<unknown>(null);
  const [loading, setLoading] = React.useState(false);
  const [nonce, setNonce] = React.useState(0);

  React.useEffect(() => {
    if (!fn) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fn()
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, error, loading, reload: () => setNonce((n) => n + 1) };
}
