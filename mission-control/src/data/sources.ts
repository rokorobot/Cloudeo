import type {
  ActivityEvent,
  UnsupportedWorkOrder,
  WorkOrderDetail,
  WorkOrderSummary,
} from "@/lib/types";

/**
 * The boundary between Mission Control screens and where WorkOrders come from.
 *
 * Reads and writes are separate on purpose: control mode implements only the
 * query side. Commands exist only for the fixture/demo source.
 */

export type Result<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "not_found" }
  | { status: "error"; kind: "unsupported" | "unavailable" | "failed"; message: string };

export interface WorkOrderList {
  active: WorkOrderSummary[];
  attention: WorkOrderSummary[];
  recent: WorkOrderSummary[];
  /** Stored WorkOrders the adapter could not present. Always shown. */
  unsupported: UnsupportedWorkOrder[];
}

export interface WorkOrderQuerySource {
  getWorkOrder(id: string): Promise<Result<WorkOrderDetail>>;
  listWorkOrders(): Promise<Result<WorkOrderList>>;
}

export interface WorkOrderCommandSource {
  pause(): void;
  resume(): void;
  stop(): void;
  takeControl(): void;
  handBack(): void;
}

/**
 * "readonly": a control-backed WorkOrder; nothing in the UI can change it.
 * The other modes belong to the demo simulation.
 */
export type RunMode = "running" | "paused" | "operator" | "stopped" | "static" | "readonly";

export interface LiveWorkOrder extends WorkOrderDetail {
  mode: RunMode;
  events: ActivityEvent[];
  scriptIndex: number;
}

/** Group summaries the way Home and Runs present them. */
export function groupSummaries(
  summaries: WorkOrderSummary[],
  unsupported: UnsupportedWorkOrder[] = [],
): WorkOrderList {
  const terminal = new Set(["promoted", "aborted", "verified", "stopped"]);
  return {
    attention: summaries.filter((s) => s.state === "attention"),
    recent: summaries.filter((s) => terminal.has(s.state)),
    active: summaries.filter((s) => s.state !== "attention" && !terminal.has(s.state)),
    unsupported,
  };
}
