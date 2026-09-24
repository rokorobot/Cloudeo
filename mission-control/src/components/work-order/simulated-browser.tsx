"use client";

import { Hand, Play } from "lucide-react";

import { Panel } from "@/components/common/status";
import type { ExecutionView, ScriptStep } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useRunControls, type RunMode } from "@/state/mission-control";

/**
 * A stand-in for a live browser stream. The "page" is plain markup from
 * fixtures; the cursor and highlights follow the current script step.
 */
export function SimulatedBrowser({
  browser,
  step,
  mode,
  woId,
}: {
  browser: ExecutionView["browser"];
  step?: ScriptStep;
  mode: RunMode;
  woId: string;
}) {
  const controls = useRunControls(woId);
  const operator = mode === "operator";
  const live = mode === "running" || operator;
  const cursor = step?.cursor ?? { x: 12, y: 10 };

  return (
    <Panel className={cn("relative flex min-h-[340px] flex-col overflow-hidden", operator && "border-warn/50")}>
      <div className="flex items-center gap-2 border-b border-line-soft px-2.5 py-2">
        <span aria-hidden className="flex gap-[5px]">
          <i className="size-2 rounded-full bg-[#2a303b]" />
          <i className="size-2 rounded-full bg-[#2a303b]" />
          <i className="size-2 rounded-full bg-[#2a303b]" />
        </span>
        <span className="min-w-0 flex-1 truncate rounded-md border border-line-soft bg-ground px-2.5 py-1 font-mono text-[11.5px] text-subtle">
          {browser.url}
        </span>
        {live ? (
          <span className="flex items-center gap-1.5 font-mono text-[10.5px] tracking-[0.08em] text-err">
            <i className="size-1.5 animate-node-pulse rounded-full bg-err" /> LIVE
          </span>
        ) : (
          <span className="font-mono text-[10.5px] tracking-[0.08em] text-muted-foreground">FROZEN</span>
        )}
      </div>

      {/* The simulated page deliberately uses light "website" colours, not app tokens. */}
      <div className="relative flex-1 overflow-hidden bg-[#f3f1ec] px-4.5 pt-4 pb-14 text-[12px] text-[#1d2127]">
        <div className="mb-3 flex items-center justify-between border-b border-[#dad6cd] pb-2.5">
          <span className="font-semibold">{browser.siteName}</span>
          <span className="flex gap-3.5 text-[11px] text-[#5a5f68]">
            <span>Products</span>
            <span>Distributors</span>
            <span>Support</span>
          </span>
        </div>
        <h4 className="mb-1 text-[15px] font-semibold">{browser.heading}</h4>
        <div className="mb-3 text-[11px] text-[#666b73]">{browser.subheading}</div>
        <div className="mb-2.5 flex flex-wrap gap-2">
          {browser.filters.map((f, i) => (
            <span
              key={f}
              className={cn(
                "rounded-md border border-[#d1ccc2] bg-white px-2.5 py-1 text-[11px]",
                i === 0 && step?.highlightFilter && "outline-2 outline-offset-1 outline-[#2ba7e8]",
              )}
            >
              {f}
            </span>
          ))}
        </div>
        <table className="w-full border-collapse text-[11.5px]">
          <thead>
            <tr>
              {["Model", "SKU", "Price", "Stock"].map((h) => (
                <th key={h} className="border-b border-[#dad6cd] px-2 py-1.5 text-left text-[10.5px] font-medium tracking-[0.05em] text-[#6a6f77] uppercase">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {browser.rows.map((r, i) => (
              <tr key={r.sku} className={cn("transition-colors duration-300", step?.highlightRow === i && "bg-[#5cc8ff]/25")}>
                <td className="border-b border-[#e6e2da] px-2 py-[7px]">{r.model}</td>
                <td className="border-b border-[#e6e2da] px-2 py-[7px] font-mono text-[11px]">{r.sku}</td>
                <td className="border-b border-[#e6e2da] px-2 py-[7px] tnum">{r.price}</td>
                <td className="border-b border-[#e6e2da] px-2 py-[7px] tnum">{r.stock}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {!operator && (
          <svg
            aria-hidden
            viewBox="0 0 14 14"
            className="pointer-events-none absolute size-3.5 drop-shadow transition-[left,top] duration-[900ms] ease-[cubic-bezier(.4,.1,.2,1)]"
            style={{ left: `${cursor.x}%`, top: `${cursor.y}%` }}
          >
            <path d="M1 1l11 5-5 1.5L5.5 13z" fill="#0b0d10" stroke="#fff" strokeWidth="1" />
          </svg>
        )}

        {operator && (
          <div className="absolute top-3 left-3 rounded-md bg-warn px-2.5 py-1.5 text-[11px] font-medium text-[#1d1606]">
            You have control · agent paused · your actions are recorded as evidence
          </div>
        )}
      </div>

      {mode !== "stopped" && (
        <button
          type="button"
          onClick={operator ? controls.handBack : controls.takeControl}
          className={cn(
            "absolute right-3 bottom-3 flex items-center gap-1.5 rounded-lg border bg-ground/90 px-3 py-1.5 text-[12px] text-foreground backdrop-blur transition-colors",
            operator ? "border-warn/60 text-warn hover:border-warn" : "border-brand/40 hover:border-brand",
          )}
        >
          {operator ? <Play className="size-3.5" /> : <Hand className="size-3.5" />}
          {operator ? "Hand back to agent" : "Take control"}
        </button>
      )}
    </Panel>
  );
}
