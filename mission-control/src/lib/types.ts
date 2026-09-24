/**
 * UI-facing view models for Mission Control.
 *
 * These describe what the screens need to render, not the V2 control-store
 * schema. When the backend is wired in, an adapter maps control-store records
 * onto these shapes; components should never import backend types directly.
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

/** How a lifecycle stage appears in the stage bar. */
export type StageStatus = "done" | "active" | "paused" | "attention" | "pending";

export type WorkOrderState =
  | "planning"
  | "executing"
  | "auditing"
  | "browsing"
  | "paused"
  | "operator"
  | "attention"
  | "stopped"
  | "verified";

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
  /** Machine-readable reason shown next to the state, e.g. an attention code. */
  reason?: string;
  elapsedSec: number;
  cost: Money;
  blocks?: { done: number; total: number };
  /** Relative or clock time for list rows. */
  when?: string;
  /** False when fixtures contain only the summary row, not the full WorkOrder. */
  hasDetail: boolean;
}

export interface AgentRef {
  role: string;
  model: string;
  runtime: string;
  provider: string;
}

export interface WorkOrderDetail extends WorkOrderSummary {
  objective: string;
  risk: RiskClass;
  profile: { id: string; version: string };
  createdAt: string;
  budget: Money;
  currentStage: LifecycleStage;
  stages: Record<LifecycleStage, StageStatus>;
  agent: AgentRef;
  evidenceCount: number;
  steps: number;
  plan: PlanView;
  execution?: ExecutionView;
  audit?: AuditView;
  memory: MemoryView;
  checkpoints: CheckpointView;
  verify: FutureStageView;
  promote: FutureStageView;
  attention?: AttentionView;
}

/* ---------- PLAN ---------- */

export interface AcceptanceCriterion {
  text: string;
  status: "met" | "in_progress" | "pending";
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
  routing: {
    policy: string;
    decidedAt: string;
    rationale: string;
    candidates: RoutingCandidate[];
    hardConstraints: string[];
  };
}

/* ---------- EXECUTE ---------- */

export interface BlockRef {
  id: string;
  title: string;
  status: "proven" | "active" | "pending";
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
  currentBlockId: string;
  blocks: BlockRef[];
  browser: {
    url: string;
    siteName: string;
    heading: string;
    subheading: string;
    filters: string[];
    rows: BrowserRow[];
  };
  seedEvents: ActivityEvent[];
  script: ScriptStep[];
}

/* ---------- AUDIT ---------- */

export interface AuditView {
  blockId: string;
  blockTitle: string;
  verdict: "BLOCK_DONE" | "BLOCK_REJECTED";
  executor: string;
  auditor: string;
  auditedHead: string;
  contentSha: string;
  checkpoint: string;
  verification: "MATCH" | "MISMATCH";
  tests: { suite: string; passed: number; total: number }[];
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

/* ---------- CHECKPOINT ---------- */

export interface CheckpointView {
  repo: string;
  items: {
    id: string;
    sha: string;
    label: string;
    status: "accepted" | "candidate";
    auditedBy?: string;
  }[];
}

/* ---------- VERIFY / PROMOTE ---------- */

export interface FutureStageView {
  summary: string;
  checks: { text: string; detail?: string }[];
  preconditions: { text: string; met: boolean }[];
}

/* ---------- ATTENTION ---------- */

export type ProviderStatus = "healthy" | "degraded" | "unavailable" | "ineligible";

export interface AttentionView {
  code: string;
  headline: string;
  pausedAtCheckpoint: string;
  since: string;
  requirement: {
    role: string;
    rule: string;
    executorProvider: string;
  };
  providers: { provider: string; status: ProviderStatus; detail: string }[];
  override: {
    policyPath: string;
    from: string;
    to: string;
    requiredRole: string;
  };
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
