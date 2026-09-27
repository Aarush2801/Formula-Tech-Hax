"use client";

import { Copy, Download, FileText, Loader2 } from "lucide-react";
import React from "react";

import { PageHeader, RequireBatch } from "../../components/Common";
import {
  Button,
  Caveat,
  ErrorState,
  Panel,
  Skeleton,
} from "../../components/ui";
import { api, API_BASE } from "../../lib/api";
import { datetime, int } from "../../lib/format";
import { useApp, useFetch } from "../../lib/store";

export default function ReportPage() {
  return (
    <RequireBatch>
      <ReportScreen />
    </RequireBatch>
  );
}

function ReportScreen() {
  const { batchId, batch } = useApp();
  const rep = useFetch(batchId ? () => api.report(batchId) : null, [batchId]);
  const [copied, setCopied] = React.useState(false);
  const [active, setActive] = React.useState<string | null>(null);

  const copy = async () => {
    if (!rep.data) return;
    try {
      await navigator.clipboard.writeText(rep.data.markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard may be unavailable */
    }
  };

  const download = () => {
    if (!rep.data) return;
    const blob = new Blob([rep.data.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `apex-stress-test-${rep.data.batch_id}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const blocks = React.useMemo(
    () => (rep.data ? parseMarkdown(rep.data.markdown) : []),
    [rep.data]
  );

  return (
    <>
      <PageHeader
        title="Stress-test report"
        lede="An automatically generated write-up of this batch, assembled entirely from its stored analyses. The limitations section is generated from the actual configuration, so it names the specific assumptions that drove the specific numbers above it."
        right={
          rep.data && (
            <div className="flex gap-2">
              <Button size="sm" onClick={copy}>
                <Copy size={11} /> {copied ? "Copied" : "Copy markdown"}
              </Button>
              <Button size="sm" onClick={download}>
                <Download size={11} /> Download
              </Button>
              <a
                href={`${API_BASE}/api/report/${rep.data.batch_id}/markdown`}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Button size="sm" variant="ghost">
                  <FileText size={11} /> Raw
                </Button>
              </a>
            </div>
          )
        }
      />

      {rep.loading && !rep.data ? (
        <div className="flex items-center gap-2 py-10 text-ink-3">
          <Loader2 size={14} className="animate-spin" aria-hidden />
          <span className="text-xs">Assembling the report from stored analyses…</span>
        </div>
      ) : rep.error ? (
        <ErrorState error={rep.error} onRetry={rep.reload} />
      ) : rep.data ? (
        <div className="grid gap-3 xl:grid-cols-[210px_minmax(0,1fr)]">
          {/* contents */}
          <nav className="xl:sticky xl:top-[52px] xl:self-start" aria-label="Report contents">
            <Panel title="Contents" dense>
              <ol className="space-y-[1px]">
                {rep.data.sections.map((s) => (
                  <li key={s}>
                    <a
                      href={`#${slug(s)}`}
                      onClick={() => setActive(s)}
                      className={`block truncate rounded px-1.5 py-[3px] text-[11px] transition-colors ${
                        active === s
                          ? "bg-surface-3 text-ink"
                          : "text-ink-3 hover:bg-surface-2 hover:text-ink-2"
                      }`}
                    >
                      {s}
                    </a>
                  </li>
                ))}
              </ol>
              <div className="mt-2.5 border-t border-line pt-2">
                <p className="text-[10px] text-ink-3">
                  {int(rep.data.n_runs)} runs · generated {datetime(rep.data.generated_at)}
                </p>
                <p className="num mt-1 text-[9.5px] text-ink-3">{rep.data.batch_id}</p>
              </div>
            </Panel>
          </nav>

          {/* rendered report */}
          <Panel bodyClassName="px-5 py-5">
            <article className="max-w-[78ch]">
              {blocks.map((b, i) => (
                <Block key={i} block={b} />
              ))}
            </article>
          </Panel>
        </div>
      ) : null}
    </>
  );
}

/* ------------------------------------------------------- markdown render --- */

type Block =
  | { kind: "h1" | "h2" | "h3"; text: string }
  | { kind: "p"; text: string }
  | { kind: "quote"; text: string }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] }
  | { kind: "table"; headers: string[]; rows: string[][] };

/**
 * A small, deliberate Markdown subset renderer. The report is produced by the
 * backend as Markdown so it can be downloaded or pasted anywhere; this renders the
 * exact same text in the product's own type and table styling rather than shipping
 * a general Markdown library for six constructs.
 */
function parseMarkdown(md: string): Block[] {
  const lines = md.split("\n");
  const out: Block[] = [];
  let i = 0;

  const flushPara = (buf: string[]) => {
    if (buf.length) out.push({ kind: "p", text: buf.join("").trim() });
  };

  let para: string[] = [];

  while (i < lines.length) {
    const line = lines[i];

    if (/^#{1,3}\s/.test(line)) {
      flushPara(para);
      para = [];
      const level = line.match(/^#+/)![0].length;
      out.push({
        kind: level === 1 ? "h1" : level === 2 ? "h2" : "h3",
        text: line.replace(/^#+\s*/, ""),
      });
      i++;
      continue;
    }

    if (line.startsWith("> ")) {
      flushPara(para);
      para = [];
      const buf: string[] = [];
      while (i < lines.length && lines[i].startsWith("> ")) {
        buf.push(lines[i].slice(2));
        i++;
      }
      out.push({ kind: "quote", text: buf.join(" ") });
      continue;
    }

    if (line.startsWith("| ")) {
      flushPara(para);
      para = [];
      const tbl: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        const cells = lines[i]
          .split("|")
          .slice(1, -1)
          .map((c) => c.trim());
        if (!cells.every((c) => /^-+$/.test(c))) tbl.push(cells);
        i++;
      }
      if (tbl.length) {
        out.push({ kind: "table", headers: tbl[0], rows: tbl.slice(1) });
      }
      continue;
    }

    if (/^[-*]\s/.test(line)) {
      flushPara(para);
      para = [];
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s*/, ""));
        i++;
      }
      out.push({ kind: "ul", items });
      continue;
    }

    if (/^\d+\.\s/.test(line)) {
      flushPara(para);
      para = [];
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s*/, ""));
        i++;
      }
      out.push({ kind: "ol", items });
      continue;
    }

    if (line.trim() === "") {
      flushPara(para);
      para = [];
      i++;
      continue;
    }

    // A line ending in two spaces is a Markdown hard break; anything else joins
    // onto the same paragraph with a space.
    para.push(/\s{2}$/.test(line) ? `${line.trimEnd()}\n` : `${line} `);
    i++;
  }
  flushPara(para);
  return out;
}

function Block({ block }: { block: Block }) {
  switch (block.kind) {
    case "h1":
      return (
        <h1 className="mb-3 text-[21px] font-semibold tracking-tight text-ink">
          {inline(block.text)}
        </h1>
      );
    case "h2":
      return (
        <h2
          id={slug(block.text.replace(/^\d+\.\s*/, ""))}
          className="mb-2.5 mt-7 scroll-mt-16 border-b border-line pb-1.5 text-[15px] font-semibold text-ink"
        >
          {inline(block.text)}
        </h2>
      );
    case "h3":
      return (
        <h3 className="mb-2 mt-5 text-[12.5px] font-semibold uppercase tracking-wider text-ink-2">
          {inline(block.text)}
        </h3>
      );
    case "p":
      return (
        <p className="mb-2.5 text-[12.5px] leading-relaxed text-ink-2">
          {block.text.split("\n").map((ln, i, arr) => (
            <React.Fragment key={i}>
              {inline(ln)}
              {i < arr.length - 1 && <br />}
            </React.Fragment>
          ))}
        </p>
      );
    case "quote":
      return (
        <blockquote
          className="mb-4 rounded border-l-2 px-3 py-2.5"
          style={{ borderLeftColor: "var(--warning)", background: "var(--warning)0c" }}
        >
          <p className="text-[12px] leading-relaxed text-ink-2">{inline(block.text)}</p>
        </blockquote>
      );
    case "ul":
      return (
        <ul className="mb-3 space-y-1.5 pl-4">
          {block.items.map((it, i) => (
            <li key={i} className="list-disc text-[12.5px] leading-relaxed text-ink-2">
              {inline(it)}
            </li>
          ))}
        </ul>
      );
    case "ol":
      return (
        <ol className="mb-3 space-y-1.5 pl-4">
          {block.items.map((it, i) => (
            <li key={i} className="list-decimal break-words text-[12px] leading-relaxed text-ink-2">
              {inline(it)}
            </li>
          ))}
        </ol>
      );
    case "table":
      return (
        <div className="mb-4 overflow-x-auto">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr>
                {block.headers.map((h, i) => (
                  <th
                    key={i}
                    className={`label-xs !text-[9px] border-b border-line-strong px-2 py-1.5 ${
                      i === 0 ? "text-left" : "text-right"
                    }`}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((r, ri) => (
                <tr key={ri} className="border-b border-line/60">
                  {r.map((c, ci) => (
                    <td
                      key={ci}
                      className={`px-2 py-1 ${
                        ci === 0 ? "text-ink-2" : "num text-right text-ink"
                      }`}
                    >
                      {inline(c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
  }
}

/** Bold, italics and inline code only — matching what the generator emits. */
function inline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*|https?:\/\/\S+)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) {
      parts.push(
        <strong key={k++} className="font-semibold text-ink">
          {tok.slice(2, -2)}
        </strong>
      );
    } else if (tok.startsWith("`")) {
      parts.push(
        <code key={k++} className="num rounded bg-surface-3 px-1 text-[11px] text-ink">
          {tok.slice(1, -1)}
        </code>
      );
    } else if (tok.startsWith("http")) {
      parts.push(
        <a
          key={k++}
          href={tok}
          target="_blank"
          rel="noopener noreferrer"
          className="break-all underline decoration-dotted"
          style={{ color: "var(--accent)" }}
        >
          {tok}
        </a>
      );
    } else {
      parts.push(
        <em key={k++} className="italic">
          {tok.slice(1, -1)}
        </em>
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function slug(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}
