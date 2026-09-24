import { groupSummaries, type Result, type WorkOrderList, type WorkOrderQuerySource } from "@/data/sources";
import {
  LIFECYCLE,
  STAGE_STATUSES,
  type UnsupportedWorkOrder,
  type WorkOrderDetail,
  type WorkOrderState,
  type WorkOrderSummary,
} from "@/lib/types";

/**
 * Reads V2 WorkOrders through the Next.js proxy (/api/control → Cloudeo API).
 *
 * Every payload is checked against the vocabulary this UI knows. A value it
 * does not know is an explicit "unsupported" error, never a default.
 */

/** States the V2 adapter may send. Demo-only states are not valid here. */
export const CONTROL_STATES = [
  "draft",
  "intake",
  "plan_proposed",
  "plan_approved",
  "executing",
  "final_verification",
  "promoted",
  "attention",
  "deferred",
  "aborted",
] as const satisfies readonly WorkOrderState[];

export class UnsupportedViewError extends Error {}

function oneOf<T extends string>(allowed: readonly T[], value: unknown, what: string): T {
  if (typeof value === "string" && (allowed as readonly string[]).includes(value)) return value as T;
  throw new UnsupportedViewError(`unsupported ${what}: ${JSON.stringify(value)}`);
}

function requireControl(raw: { source?: unknown }) {
  if (raw.source !== "control") throw new UnsupportedViewError(`unexpected source: ${JSON.stringify(raw.source)}`);
}

export function normalizeSummary(raw: WorkOrderSummary): WorkOrderSummary {
  requireControl(raw);
  oneOf(CONTROL_STATES, raw.state, "WorkOrder state");
  return raw;
}

export function normalizeDetail(raw: WorkOrderDetail): WorkOrderDetail {
  normalizeSummary(raw);
  oneOf(LIFECYCLE, raw.currentStage, "lifecycle stage");
  for (const stage of LIFECYCLE) oneOf(STAGE_STATUSES, raw.stages?.[stage], `${stage} stage status`);
  for (const b of raw.execution?.blocks ?? []) oneOf(["proven", "active", "pending"] as const, b.status, "block status");
  if (raw.execution) oneOf(["unavailable"] as const, raw.execution.runtime, "runtime");
  if (raw.audit) {
    oneOf(["BLOCK_DONE", "NOT_YET_PROVEN", "CHECKPOINT_REJECTED"] as const, raw.audit.verdict, "audit verdict");
    oneOf(["MATCH", "MISMATCH", "PENDING"] as const, raw.audit.verification, "verification");
  }
  for (const c of raw.checkpoints?.items ?? [])
    oneOf(["baseline", "accepted", "candidate", "rejected"] as const, c.status, "checkpoint status");
  for (const h of raw.history ?? []) oneOf(CONTROL_STATES, h.state, "history state");
  if (raw.attention?.raisedFrom) oneOf(CONTROL_STATES, raw.attention.raisedFrom, "attention source state");
  return raw;
}

async function readJson(res: Response): Promise<{ detail?: { error?: string; message?: string } } & Record<string, unknown>> {
  try {
    return await res.json();
  } catch {
    return {};
  }
}

function failure(res: Response, body: { detail?: { error?: string; message?: string } }): Result<never> {
  const message = body.detail?.message ?? `HTTP ${res.status}`;
  if (res.status === 404) return { status: "not_found" };
  if (res.status === 422) return { status: "error", kind: "unsupported", message };
  if (res.status === 503) return { status: "error", kind: "unavailable", message };
  return { status: "error", kind: "failed", message };
}

export class HttpWorkOrderQuerySource implements WorkOrderQuerySource {
  constructor(
    private readonly base = "/api/control",
    private readonly fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  async getWorkOrder(id: string): Promise<Result<WorkOrderDetail>> {
    try {
      const res = await this.fetchImpl(`${this.base}/work-orders/${encodeURIComponent(id)}`, { cache: "no-store" });
      const body = await readJson(res);
      if (!res.ok) return failure(res, body);
      return { status: "ready", data: normalizeDetail(body as unknown as WorkOrderDetail) };
    } catch (e) {
      return toError(e);
    }
  }

  async listWorkOrders(): Promise<Result<WorkOrderList>> {
    try {
      const res = await this.fetchImpl(`${this.base}/work-orders`, { cache: "no-store" });
      const body = await readJson(res);
      if (!res.ok) return failure(res, body);
      const summaries: WorkOrderSummary[] = [];
      const unsupported: UnsupportedWorkOrder[] = [];
      for (const raw of (body.workOrders ?? []) as (WorkOrderSummary | UnsupportedWorkOrder)[]) {
        if ("unsupported" in raw) {
          unsupported.push(raw);
          continue;
        }
        try {
          summaries.push(normalizeSummary(raw));
        } catch (e) {
          unsupported.push({ id: String(raw.id), unsupported: (e as Error).message, source: "control" });
        }
      }
      return { status: "ready", data: groupSummaries(summaries, unsupported) };
    } catch (e) {
      return toError(e);
    }
  }
}

function toError(e: unknown): Result<never> {
  if (e instanceof UnsupportedViewError) return { status: "error", kind: "unsupported", message: e.message };
  return { status: "error", kind: "unavailable", message: e instanceof Error ? e.message : String(e) };
}
