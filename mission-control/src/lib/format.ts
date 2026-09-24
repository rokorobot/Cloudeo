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

/** Stored ISO timestamp → "2026-09-23 12:00 UTC". Shows the stored value; never "now". */
export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function shortSha(sha: string | undefined): string | undefined {
  return sha && /^[0-9a-f]{40,64}$/.test(sha) ? sha.slice(0, 7) : sha;
}

export const STATE_LABEL: Record<WorkOrderState, string> = {
  draft: "DRAFT",
  intake: "CONTEXT INTAKE",
  plan_proposed: "PLAN PROPOSED",
  plan_approved: "PLAN APPROVED",
  executing: "EXECUTING",
  final_verification: "FINAL VERIFICATION",
  promoted: "PROMOTED",
  attention: "ATTENTION",
  deferred: "DEFERRED",
  aborted: "ABORTED",
  auditing: "AUDITING",
  browsing: "BROWSING",
  paused: "PAUSED",
  operator: "OPERATOR CONTROL",
  stopped: "STOPPED",
  verified: "VERIFIED",
};

export const STATE_TONE: Record<WorkOrderState, Tone> = {
  draft: "neutral",
  intake: "brand",
  plan_proposed: "neutral",
  plan_approved: "brand",
  executing: "brand",
  final_verification: "brand",
  promoted: "ok",
  attention: "warn",
  deferred: "neutral",
  aborted: "err",
  auditing: "brand",
  browsing: "brand",
  paused: "warn",
  operator: "warn",
  stopped: "err",
  verified: "ok",
};
