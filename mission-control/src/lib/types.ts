/**
 * UI-facing view models for Mission Control.
 *
 * These describe what the screens need to render, not the V2 control-store
 * schema. Two sources fill them:
 *
 * - "fixture": local demo data plus a client-side simulation (demo mode);
 * - "control": the read-only V2 adapter (cloudeo.mission_control), which
 *   leaves out anything the control store does not hold.
 *
 * Optional fields are optional because the control store may not have them.
 * Components must render their absence explicitly, never substitute a value.
 */

export const LIFECYCLE = [
  "plan",
  "execute",
  "audit",
  "memory",
  "checkpoint",
  "verify",
  "promote",
] as const;

export type LifecycleStage = (typeof LIFECYCLE)[number];

export const STAGE_STATUSES = ["done", "active", "paused", "attention", "pending", "skipped", "aborted"] as const;

/** How a lifecycle stage appears in the stage bar. "skipped" = not applicable to this block. */
export type StageStatus = (typeof STAGE_STATUSES)[number];

export const WORK_ORDER_STATES = [
  // V2 control states
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
  // Demo-only presentation states
  "auditing",
  "browsing",
  "paused",
  "operator",
  "stopped",
  "verified",
] as const;

export type WorkOrderState = (typeof WORK_ORDER_STATES)[number];

export type DataSource = "fixture" | "control";

export type RiskClass = "low" | "medium" | "high";

/** Semantic tone; maps to brand / ok / warn / err colours. */
export type Tone = "brand" | "ok" | "warn" | "err" | "neutral";

export interface Money {
  usd: number;
}

export interface WorkOrderSummary {
  id: string;
  title: string;
  project: string;
  state: WorkOrderState;
  source: DataSource;
  /** Machine-readable reason shown next to the state, e.g. an attention code. */
  reason?: string;
  /** Not recorded by the control store. */
  elapsedSec?: number;
  /** Not recorded by the control store. */
  cost?: Money;
  blocks?: { done: number; total: number };
  /** Relative or clock time for list rows. */
  when?: string;
  /** False when only the summary row exists, not the full WorkOrder. */
  hasDetail: boolean;
}

/** A stored WorkOrder the adapter refused to present. Listed, never hidden. */
export interface UnsupportedWorkOrder {
  id: string;
  unsupported: string;
  source: "control";
}

export interface AgentRef {
  role: string;
  /** Profile identity, e.g. "opus-coder v1". */
  profile?: string;
  fallbackCondition?: string;
  model?: string;
  runtime?: string;
  provider?: string;
}

export interface Budget {
  usd?: number;
  maxAttemptsPerBlock?: number;
  maxDurationSeconds?: number;
}

export interface Fact {
  label: string;
  value: string;
  tone?: Tone;
}

export interface WorkOrderDetail extends WorkOrderSummary {
  objective: string;
  /** Stored record version (control mode). */
  version?: number;
  risk?: RiskClass;
  profile: { id: string; version: string };
  createdAt?: string;
  budget?: Budget;
  currentStage: LifecycleStage;
  stages: Record<LifecycleStage, StageStatus>;
  agent?: AgentRef;
  evidenceCount: number;
  steps?: number;
  plan: PlanView;
  execution?: ExecutionView;
  audit?: AuditView;
  /** Performance memory (demo only; not in the V2 control store yet). */
  memory?: MemoryView;
  /** V2 MEMORY stage: per-block memory curation and Memory Audit. */
  memoryCuration?: MemoryCurationView[];
  checkpoints: CheckpointView;
  verify: FutureStageView;
  promote: FutureStageView;
  attention?: AttentionView;
  history?: HistoryEntry[];
  timestamps?: { label: string; at: string; by?: string }[];
}

/* ---------- PLAN ---------- */

export interface AcceptanceCriterion {
  text: string;
  /** "unassessed": the control store records criteria, not per-criterion results. */
  status: "met" | "in_progress" | "pending" | "unassessed";
}

/** Historical observations. Never a prediction or guarantee. */
export interface ProfileObservation {
  verifiedSuccesses: number;
  attempts: number;
  medianSec: number;
  medianCost: Money;
  window: string;
}

export interface RoutingCandidate {
  profileId: string;
  label: string;
  status: "selected" | "eligible" | "filtered";
  policyScore?: number;
  observed?: ProfileObservation;
  filterReason?: string;
}

export interface PlanView {
  acceptanceCriteria: AcceptanceCriterion[];
  /** Routing decision (demo only; the control store does not record one yet). */
  routing?: {
    policy: string;
    decidedAt: string;
    rationale: string;
    candidates: RoutingCandidate[];
    hardConstraints: string[];
  };
  planVersion?: number;
  architectureSummary?: string;
  approval?: { planVersion: number; profileVersion: number; approvedBy: string; approvedAt: string };
  blocks?: { id: string; order: number; goal: string; scope: string[]; acceptanceChecks: string[]; memoryImpact: boolean }[];
  /** Role → profile bindings of the WorkOrder's execution profile snapshot. */
  bindings?: { role: string; primary: string; fallbacks: string[]; fallbackConditions: string[] }[];
}

/* ---------- EXECUTE ---------- */

export interface BlockRef {
  id: string;
  title: string;
  status: "proven" | "active" | "pending";
  /** Raw V2 block status, e.g. "BLOCK_RESULT". */
  phase?: string;
  attempts?: number;
  failedAttempts?: number;
}

export type ActivityKind = "step" | "operator" | "system";

export interface ActivityEvent {
  id: string;
  kind: ActivityKind;
  text: string;
  detail: string;
  atSec: number;
}

export interface BrowserRow {
  model: string;
  sku: string;
  price: string;
  stock: number;
}

/** One scripted step of the simulated browser run. Cursor is in % of the viewport. */
export interface ScriptStep {
  text: string;
  detail: string;
  cursor: { x: number; y: number };
  highlightRow?: number;
  highlightFilter?: boolean;
  producesEvidence?: boolean;
}

export interface ExecutionView {
  currentBlockId?: string;
  blocks: BlockRef[];
  /** "unavailable": no executor/browser runtime is connected to this WorkOrder. */
  runtime: "simulated" | "unavailable";
  browser?: {
    url: string;
    siteName: string;
    heading: string;
    subheading: string;
    filters: string[];
    rows: BrowserRow[];
  };
  seedEvents?: ActivityEvent[];
  script?: ScriptStep[];
}

/* ---------- AUDIT ---------- */

export interface AuditView {
  blockId: string;
  blockTitle: string;
  /** Only BLOCK_DONE is a proven state. */
  verdict: "BLOCK_DONE" | "NOT_YET_PROVEN" | "CHECKPOINT_REJECTED";
  executor?: string;
  auditor: string;
  auditStatus?: string;
  authoritative?: boolean;
  auditedHead: string;
  contentSha: string;
  checkpoint?: string;
  verification: "MATCH" | "MISMATCH" | "PENDING";
  tests: { suite: string; result: "passed" | "failed"; counts?: { passed: number; total: number } }[];
  artifactCount: number;
  proven: { value: number; label: string; tone?: Tone }[];
  pendingNote?: string;
}

/* ---------- MEMORY ---------- */

export interface MemoryView {
  taskClass: string;
  window: string;
  rows: {
    profileId: string;
    selected?: boolean;
    observed: ProfileObservation;
    p95Sec: number;
    evidenceBasis: string;
  }[];
}

export interface MemoryCurationView {
  blockId: string;
  blockTitle: string;
  status: "not_started" | "curating" | "auditing" | "approved";
  changedPaths: string[];
  outsidePaths: string[];
  auditor?: string;
  auditStatus?: string;
}

/* ---------- CHECKPOINT ---------- */

export interface CheckpointView {
  repo?: string;
  items: {
    id: string;
    /** Absent for a candidate that has no checkpoint commit yet. */
    sha?: string;
    label: string;
    status: "baseline" | "accepted" | "candidate" | "rejected";
    auditedBy?: string;
  }[];
}

/* ---------- VERIFY / PROMOTE ---------- */

export interface FutureStageView {
  summary: string;
  checks: { text: string; detail?: string }[];
  preconditions: { text: string; met: boolean }[];
  /** Recorded results, e.g. the final audit or kernel outcome. */
  facts?: Fact[];
}

/* ---------- ATTENTION ---------- */

export type ProviderStatus = "healthy" | "degraded" | "unavailable" | "ineligible";

export interface AttentionReason {
  code: string;
  severity: "blocking" | "warning";
  summary: string;
  evidenceCount: number;
  suggestions: string[];
  status: "open" | "resolved" | "waived";
}

export interface AttentionView {
  code: string;
  headline: string;
  pausedAtCheckpoint?: string;
  since?: string;
  raisedFrom?: WorkOrderState;
  reasons?: AttentionReason[];
  decisions?: { action: string; actor: string; at: string; message?: string }[];
  /** Decisions the V2 contract offers; not actionable in read-only mode. */
  availableDecisions?: string[];
  requirement?: {
    role: string;
    rule: string;
    executorProvider: string;
  };
  providers?: { provider: string; status: ProviderStatus; detail: string }[];
  override?: {
    policyPath: string;
    from: string;
    to: string;
    requiredRole: string;
  };
}

/* ---------- HISTORY ---------- */

export interface HistoryEntry {
  version: number;
  event: string;
  state: WorkOrderState;
}

/* ---------- HEALTH ---------- */

export type RuntimeKind = "executor" | "browser" | "auditor" | "verifier" | "tools";

export interface RuntimeHealth {
  name: string;
  kind: RuntimeKind;
  status: ProviderStatus;
  detail: string;
}

export interface SystemHealth {
  verifiedToday: number;
  spendToday: Money;
  recoveriesToday: { succeeded: number; attempted: number };
  runtimes: RuntimeHealth[];
}
