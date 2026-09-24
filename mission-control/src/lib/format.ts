import type { Money, Tone, WorkOrderState } from "@/lib/types";

export function formatDuration(totalSec: number): string {
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function formatMoney(m: Money): string {
  return `$${m.usd.toFixed(2)}`;
}

export function formatPercent(n: number, d: number): string {
  if (d === 0) return "—";
  return `${Math.round((n / d) * 100)}%`;
}

export const STATE_LABEL: Record<WorkOrderState, string> = {
  planning: "PLANNING",
  executing: "EXECUTING",
  auditing: "AUDITING",
  browsing: "BROWSING",
  paused: "PAUSED",
  operator: "OPERATOR CONTROL",
  attention: "ATTENTION",
  stopped: "STOPPED",
  verified: "VERIFIED",
};

export const STATE_TONE: Record<WorkOrderState, Tone> = {
  planning: "brand",
  executing: "brand",
  auditing: "brand",
  browsing: "brand",
  paused: "warn",
  operator: "warn",
  attention: "warn",
  stopped: "err",
  verified: "ok",
};
