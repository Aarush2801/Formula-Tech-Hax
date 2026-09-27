"use client";

import {
  Activity,
  AlertTriangle,
  BarChart3,
  CircleDot,
  FileText,
  FlaskConical,
  Gauge,
  History,
  Loader2,
  Map as MapIcon,
  PlayCircle,
  Search,
  Settings2,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React from "react";

import { datetime, int } from "../lib/format";
import { useApp } from "../lib/store";

const NAV = [
  { href: "/", label: "Overview", icon: Gauge },
  { href: "/live", label: "Live simulation", icon: PlayCircle },
  { href: "/circuit", label: "Circuit analysis", icon: MapIcon },
  { href: "/scenarios", label: "Scenario explorer", icon: Search },
  { href: "/replay", label: "Incident replay", icon: Activity },
  { href: "/drivers", label: "Driver analysis", icon: Users },
  { href: "/environment", label: "Environment", icon: CircleDot },
  { href: "/sensitivity", label: "Sensitivity", icon: BarChart3 },
  { href: "/whatif", label: "What-if lab", icon: FlaskConical },
  { href: "/history", label: "History", icon: History },
  { href: "/report", label: "Report", icon: FileText },
  { href: "/assumptions", label: "Model assumptions", icon: Settings2 },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { meta, batches, batchId, setBatchId, jobs, apiOnline } = useApp();
  const running = jobs.filter((j) => j.status === "running");

  const usable = batches.filter(
    (b) => b.status === "complete" && b.n_runs_completed > 0
  );

  return (
    <div className="flex min-h-screen">
      {/* ------------------------------------------------------- nav rail --- */}
      <nav
        className="sticky top-0 flex h-screen w-[194px] shrink-0 flex-col border-r border-line bg-surface-1/70 backdrop-blur"
        aria-label="Main navigation"
      >
        <Link href="/" className="flex items-center gap-2.5 px-3.5 py-4">
          <ApexMark />
          <span className="min-w-0">
            <span className="block text-[15px] font-semibold leading-none tracking-tight text-ink">
              APEX
            </span>
            <span className="mt-1 block text-[9px] leading-tight tracking-wide text-ink-3">
              SAFETY STRESS TESTER
            </span>
          </span>
        </Link>

        <ul className="flex-1 overflow-y-auto px-2 pb-3">
          {NAV.map((n) => {
            const active = path === n.href;
            const Icon = n.icon;
            return (
              <li key={n.href}>
                <Link
                  href={n.href}
                  aria-current={active ? "page" : undefined}
                  className={`group relative mb-[1px] flex items-center gap-2.5 rounded px-2.5 py-[7px] text-[12px] transition-colors ${
                    active
                      ? "bg-surface-3 text-ink"
                      : "text-ink-3 hover:bg-surface-2 hover:text-ink-2"
                  }`}
                >
                  {active && (
                    <span
                      className="absolute inset-y-[6px] left-0 w-[2px] rounded-full"
                      style={{ background: "var(--accent)" }}
                    />
                  )}
                  <Icon size={14} className="shrink-0" aria-hidden />
                  <span className="truncate">{n.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>

        <div className="border-t border-line px-3 py-2.5">
          <div className="flex items-center gap-1.5">
            <span
              className={`inline-block h-[6px] w-[6px] rounded-full ${
                apiOnline === false ? "" : "pulse"
              }`}
              style={{
                background:
                  apiOnline === false
                    ? "var(--critical)"
                    : apiOnline === null
                    ? "var(--text-muted)"
                    : "var(--good)",
              }}
              aria-hidden
            />
            <span className="text-[10px] text-ink-3">
              {apiOnline === false
                ? "API offline"
                : apiOnline === null
                ? "Connecting"
                : "Engine connected"}
            </span>
          </div>
          {running.length > 0 && (
            <div className="mt-2 flex items-center gap-1.5">
              <Loader2 size={10} className="animate-spin text-ink-3" aria-hidden />
              <span className="num text-[10px] text-ink-2">
                {running[0].completed}/{running[0].total}
              </span>
              <span className="truncate text-[10px] text-ink-3">{running[0].phase}</span>
            </div>
          )}
        </div>
      </nav>

      {/* ------------------------------------------------------------ main --- */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-plane/92 px-4 py-2 backdrop-blur">
          <div className="flex min-w-0 items-center gap-2">
            <span className="label-xs">Analysing batch</span>
            {usable.length > 0 ? (
              <select
                value={batchId ?? ""}
                onChange={(e) => setBatchId(e.target.value)}
                className="max-w-[330px] truncate rounded border border-line-strong bg-surface-2 px-2 py-1 text-[11.5px] text-ink hover:border-[color:var(--accent)]"
                aria-label="Select the batch to analyse"
              >
                {usable.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.label || b.id} · {int(b.n_runs_completed)} runs · {b.mode}
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-[11.5px] text-ink-3">none yet</span>
            )}
          </div>

          {batchId && (
            <span className="num hidden text-[10.5px] text-ink-3 lg:inline">
              {batchId}
            </span>
          )}

          <div className="ml-auto flex items-center gap-2">
            <span
              className="inline-flex max-w-[560px] items-start gap-1.5 rounded border px-2 py-1"
              style={{
                borderColor: "var(--warning)44",
                background: "var(--warning)0d",
              }}
              role="note"
            >
              <AlertTriangle
                size={11}
                className="mt-[1px] shrink-0"
                style={{ color: "var(--warning)" }}
                aria-hidden
              />
              <span className="text-[10px] leading-snug text-ink-2">
                {meta?.disclaimer ??
                  "Simulated results under stated model assumptions. Not a real-world crash probability."}
              </span>
            </span>
          </div>
        </header>

        <main className="min-w-0 flex-1 px-4 py-4">{children}</main>

        <footer className="border-t border-line px-4 py-3">
          <p className="text-[10px] leading-relaxed text-ink-3">
            {meta?.positioning ??
              "An automated scenario-generation and safety-stress-testing layer, not a replacement for a high-fidelity motorsport simulator."}
          </p>
        </footer>
      </div>
    </div>
  );
}

/** A minimal apex-curve mark — geometric, not a logo pastiche. */
function ApexMark() {
  return (
    <svg width={22} height={22} viewBox="0 0 22 22" aria-hidden className="shrink-0">
      <path
        d="M3 19 C3 9, 8 3, 19 3"
        fill="none"
        stroke="var(--accent)"
        strokeWidth={2}
        strokeLinecap="round"
      />
      <path
        d="M3 19 C5 12, 10 6, 19 6"
        fill="none"
        stroke="var(--text-muted)"
        strokeWidth={1}
        strokeDasharray="2 2.5"
      />
      <circle cx={8.4} cy={8.2} r={2.1} fill="var(--warning)" />
    </svg>
  );
}
