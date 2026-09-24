import type { WorkOrderDetail, WorkOrderSummary } from "@/lib/types";

/**
 * Local fixture data. Nothing here comes from the V2 control store; values
 * are illustrative and chosen to exercise every screen state.
 */

const WO_1842: WorkOrderDetail = {
  id: "WO-1842",
  title: "Update EU robot catalogue",
  objective:
    "Sync EU humanoid robot prices and stock from the vendor portal into catalogue/eu.jsonl, with a source URL captured for every changed row.",
  project: "HumanoidOnline",
  state: "executing",
  elapsedSec: 272,
  cost: { usd: 0.73 },
  blocks: { done: 3, total: 6 },
  hasDetail: true,
  risk: "medium",
  profile: { id: "catalogue-sync", version: "v12" },
  createdAt: "07:16",
  budget: { usd: 4 },
  currentStage: "execute",
  stages: {
    plan: "done",
    execute: "active",
    audit: "pending",
    memory: "pending",
    checkpoint: "pending",
    verify: "pending",
    promote: "pending",
  },
  agent: {
    role: "primary-code",
    model: "Claude Sonnet 5",
    runtime: "claude-code via UHP",
    provider: "Anthropic",
  },
  evidenceCount: 12,
  steps: 18,

  plan: {
    acceptanceCriteria: [
      { text: "Every EU SKU has a price in EUR and a stock count", status: "met" },
      { text: "No row changes without a source URL captured as evidence", status: "met" },
      { text: "Importer tests pass on the candidate checkpoint", status: "in_progress" },
      { text: "Final verification by a provider independent of the executor", status: "pending" },
    ],
    routing: {
      policy: "jev-route v3",
      decidedAt: "07:16:42",
      rationale:
        "Python data task with tests available. Deterministic rules were not decisive between the two CLI profiles; policy score chose the one with more verified history on this task class.",
      candidates: [
        {
          profileId: "claude-sonnet-cli",
          label: "Claude Code · Sonnet 5",
          status: "selected",
          policyScore: 0.87,
          observed: { verifiedSuccesses: 129, attempts: 142, medianSec: 400, medianCost: { usd: 0.21 }, window: "30 days" },
        },
        {
          profileId: "codex-gpt56-cli",
          label: "Codex · GPT-5.6",
          status: "eligible",
          policyScore: 0.81,
          observed: { verifiedSuccesses: 85, attempts: 97, medianSec: 312, medianCost: { usd: 0.26 }, window: "30 days" },
        },
        {
          profileId: "jev-browser",
          label: "Jev browser",
          status: "eligible",
          policyScore: 0.64,
          observed: { verifiedSuccesses: 245, attempts: 310, medianSec: 125, medianCost: { usd: 0.04 }, window: "30 days" },
        },
        {
          profileId: "opencode-deepseek-cli",
          label: "OpenCode · DeepSeek",
          status: "filtered",
          filterReason: "Quarantined: failed upstream regression suite on v0.9.4",
        },
        {
          profileId: "claude-opus-cli",
          label: "Claude Code · Opus 5.5",
          status: "filtered",
          filterReason: "Median cost per block exceeds remaining budget share",
        },
      ],
      hardConstraints: ["write:catalogue/*", "deny:prod-db", "budget ≤ $4.00", "auditor ≠ executor provider"],
    },
  },

  execution: {
    currentBlockId: "04",
    blocks: [
      { id: "01", title: "Schema inspection", status: "proven" },
      { id: "02", title: "Importer patch", status: "proven" },
      { id: "03", title: "Unit tests", status: "proven" },
      { id: "04", title: "Portal sync", status: "active" },
      { id: "05", title: "Diff review", status: "pending" },
      { id: "06", title: "Evidence bundle", status: "pending" },
    ],
    browser: {
      url: "vendor-portal.example/eu/robots?region=EU",
      siteName: "Vendor Portal",
      heading: "EU robot catalogue",
      subheading: "Prices ex. VAT · updated 23 Sep 2026",
      filters: ["Region: EU", "Category: Humanoid", "In stock"],
      rows: [
        { model: "G1 Humanoid", sku: "G1-EU-01", price: "€16 000", stock: 42 },
        { model: "H1 Research", sku: "H1-EU-03", price: "€90 000", stock: 7 },
        { model: "Walker S Lite", sku: "WS-EU-11", price: "€48 500", stock: 12 },
        { model: "Atlas Edu Kit", sku: "AE-EU-02", price: "€72 000", stock: 3 },
        { model: "Nova Service", sku: "NS-EU-07", price: "€39 900", stock: 21 },
      ],
    },
    seedEvents: [
      { id: "s1", kind: "system", text: "Workspace created from accepted checkpoint", detail: "C3 · 51bd30a", atSec: 242 },
      { id: "s2", kind: "step", text: "Inspected importer schema", detail: "importer/eu.py · 12 files read", atSec: 249 },
      { id: "s3", kind: "step", text: "Opened browser session", detail: "jev-browser · session b-77f1", atSec: 258 },
    ],
    script: [
      { text: "Opened vendor portal", detail: "GET /eu/robots → 200", cursor: { x: 12, y: 10 } },
      { text: "Found 18 catalogue rows", detail: "dom.query table tr · 18 nodes", cursor: { x: 55, y: 55 } },
      { text: "Selected region filter", detail: "click span[data-region=EU]", cursor: { x: 14, y: 36 }, highlightFilter: true },
      { text: "Read row: G1 Humanoid", detail: "price 16 000 EUR · stock 42", cursor: { x: 50, y: 58 }, highlightRow: 0 },
      { text: "Read row: H1 Research", detail: "price 90 000 EUR · stock 7", cursor: { x: 50, y: 66 }, highlightRow: 1 },
      { text: "Diffed against catalogue", detail: "2 price deltas · 1 new SKU", cursor: { x: 70, y: 74 }, highlightRow: 2 },
      { text: "Wrote candidate rows", detail: "catalogue/eu.jsonl +3 −2 · source URLs attached", cursor: { x: 80, y: 82 }, producesEvidence: true },
    ],
  },

  audit: {
    blockId: "03",
    blockTitle: "Unit tests",
    verdict: "BLOCK_DONE",
    executor: "Claude Sonnet 5 · Anthropic",
    auditor: "GPT-5.6 · OpenAI · read-only",
    auditedHead: "4f91e29",
    contentSha: "c98d4f1e…8a01",
    checkpoint: "51bd30a",
    verification: "MATCH",
    tests: [
      { suite: "control/importer", passed: 41, total: 41 },
      { suite: "control/catalogue", passed: 28, total: 28 },
    ],
    artifactCount: 12,
    proven: [
      { value: 12, label: "files inspected by the auditor" },
      { value: 4, label: "files modified, all within write scope" },
      { value: 69, label: "control tests passed on audited HEAD", tone: "ok" },
      { value: 15, label: "obligations deferred to later blocks" },
      { value: 0, label: "unexpected XPASS", tone: "ok" },
    ],
    pendingNote: "Block 04 is still executing. Its audit starts when the candidate checkpoint is exported.",
  },

  memory: {
    taskClass: "data · python · cli · tests available",
    window: "last 30 days",
    rows: [
      {
        profileId: "claude-sonnet-cli",
        selected: true,
        observed: { verifiedSuccesses: 129, attempts: 142, medianSec: 400, medianCost: { usd: 0.21 }, window: "30 days" },
        p95Sec: 1140,
        evidenceBasis: "142 audited blocks · 38 WorkOrders",
      },
      {
        profileId: "codex-gpt56-cli",
        observed: { verifiedSuccesses: 85, attempts: 97, medianSec: 312, medianCost: { usd: 0.26 }, window: "30 days" },
        p95Sec: 980,
        evidenceBasis: "97 audited blocks · 22 WorkOrders",
      },
      {
        profileId: "jev-browser",
        observed: { verifiedSuccesses: 245, attempts: 310, medianSec: 125, medianCost: { usd: 0.04 }, window: "30 days" },
        p95Sec: 420,
        evidenceBasis: "310 audited blocks · 61 WorkOrders",
      },
    ],
  },

  checkpoints: {
    repo: "humanoid-catalogue",
    items: [
      { id: "C0", sha: "a02c11e", label: "baseline", status: "accepted" },
      { id: "C1", sha: "7e3b90d", label: "schema", status: "accepted", auditedBy: "GPT-5.6" },
      { id: "C2", sha: "e11f4c2", label: "importer", status: "accepted", auditedBy: "GPT-5.6" },
      { id: "C3", sha: "51bd30a", label: "tests", status: "accepted", auditedBy: "GPT-5.6" },
      { id: "C4", sha: "pending", label: "portal sync", status: "candidate" },
    ],
  },

  verify: {
    summary:
      "A final_verifier from a provider independent of the executor re-checks every acceptance criterion against the last accepted checkpoint, without reading the executor's claims.",
    checks: [
      { text: "Each acceptance criterion re-evaluated from evidence", detail: "4 criteria" },
      { text: "Accepted checkpoint content matches the audited SHA" },
      { text: "Every changed catalogue row has a captured source URL" },
      { text: "No writes outside catalogue/*" },
    ],
    preconditions: [
      { text: "All 6 blocks audited and checkpointed", met: false },
      { text: "Independent verifier provider available", met: true },
    ],
  },

  promote: {
    summary:
      "Promotion publishes the accepted checkpoint to the target. Medium-risk WorkOrders need owner approval; you will see the diff, evidence and cost before anything ships.",
    checks: [
      { text: "Merge accepted checkpoint into main", detail: "humanoid-catalogue" },
      { text: "Publish catalogue/eu.jsonl to the storefront importer" },
      { text: "Record a PerformanceEvent for each audited block" },
    ],
    preconditions: [
      { text: "VERIFY passed", met: false },
      { text: "Owner approval (risk: medium)", met: false },
    ],
  },
};

const WO_1845: WorkOrderDetail = {
  id: "WO-1845",
  title: "Deploy catalogue v3 to production",
  objective: "Promote the verified catalogue v3 checkpoint to the production storefront.",
  project: "HumanoidOnline",
  state: "attention",
  reason: "INDEPENDENCE_UNAVAILABLE",
  elapsedSec: 3120,
  cost: { usd: 2.41 },
  blocks: { done: 6, total: 6 },
  hasDetail: true,
  risk: "high",
  profile: { id: "catalogue-deploy", version: "v12" },
  createdAt: "06:02",
  budget: { usd: 6 },
  currentStage: "verify",
  stages: {
    plan: "done",
    execute: "done",
    audit: "done",
    memory: "done",
    checkpoint: "done",
    verify: "attention",
    promote: "pending",
  },
  agent: {
    role: "final_verifier",
    model: "—",
    runtime: "no eligible provider",
    provider: "—",
  },
  evidenceCount: 31,
  steps: 64,

  plan: {
    acceptanceCriteria: [
      { text: "Storefront import succeeds against staging", status: "met" },
      { text: "Zero price regressions against catalogue v2", status: "met" },
      { text: "Final verification by a provider independent of the executor", status: "pending" },
    ],
    routing: {
      policy: "jev-route v3",
      decidedAt: "06:02:10",
      rationale: "Deployment task; deterministic rules selected the only profile with deploy permission.",
      candidates: [
        {
          profileId: "claude-sonnet-cli",
          label: "Claude Code · Sonnet 5",
          status: "selected",
          policyScore: 0.92,
          observed: { verifiedSuccesses: 18, attempts: 19, medianSec: 540, medianCost: { usd: 0.34 }, window: "30 days" },
        },
        {
          profileId: "codex-gpt56-cli",
          label: "Codex · GPT-5.6",
          status: "filtered",
          filterReason: "Profile lacks deploy:storefront permission",
        },
      ],
      hardConstraints: ["deploy:storefront", "risk: high → owner approval", "verifier ≠ executor provider"],
    },
  },

  memory: {
    taskClass: "deploy · storefront",
    window: "last 30 days",
    rows: [
      {
        profileId: "claude-sonnet-cli",
        selected: true,
        observed: { verifiedSuccesses: 18, attempts: 19, medianSec: 540, medianCost: { usd: 0.34 }, window: "30 days" },
        p95Sec: 900,
        evidenceBasis: "19 audited blocks · 7 WorkOrders",
      },
    ],
  },

  checkpoints: {
    repo: "humanoid-catalogue",
    items: [
      { id: "C4", sha: "3d02b7a", label: "portal sync", status: "accepted", auditedBy: "GPT-5.6" },
      { id: "C5", sha: "b6e1f09", label: "diff review", status: "accepted", auditedBy: "GPT-5.6" },
      { id: "C6", sha: "9ac7e20", label: "evidence bundle", status: "accepted", auditedBy: "GPT-5.6" },
    ],
  },

  verify: {
    summary: "Final verification is paused: no provider independent of the executor is currently eligible.",
    checks: [
      { text: "Storefront import re-run against staging from checkpoint C6" },
      { text: "Price regression diff against catalogue v2" },
    ],
    preconditions: [
      { text: "All 6 blocks audited and checkpointed", met: true },
      { text: "Independent verifier provider available", met: false },
    ],
  },

  promote: {
    summary: "Promotion deploys checkpoint C6 to the production storefront after verification and owner approval.",
    checks: [{ text: "Deploy storefront import job", detail: "production" }],
    preconditions: [
      { text: "VERIFY passed", met: false },
      { text: "Owner approval (risk: high)", met: false },
    ],
  },

  attention: {
    code: "INDEPENDENCE_UNAVAILABLE",
    headline: "Final verification needs an independent provider, and none is eligible right now.",
    pausedAtCheckpoint: "C6 · 9ac7e20",
    since: "07:48",
    requirement: {
      role: "final_verifier",
      rule: "verifier.provider ≠ executor.provider",
      executorProvider: "Anthropic",
    },
    providers: [
      { provider: "Anthropic", status: "ineligible", detail: "Same provider as the executor" },
      { provider: "OpenAI", status: "unavailable", detail: "Failing health checks for 14 min" },
      { provider: "Google", status: "ineligible", detail: "Not configured for this project" },
    ],
    override: {
      policyPath: "envelope.final_verifier.independence",
      from: "required",
      to: "waived for WO-1845 only",
      requiredRole: "Project owner",
    },
  },
};

export const WORK_ORDERS: Record<string, WorkOrderDetail> = {
  [WO_1842.id]: WO_1842,
  [WO_1845.id]: WO_1845,
};

export const ACTIVE: WorkOrderSummary[] = [
  WO_1842,
  {
    id: "WO-1843",
    title: "SEO crawl: robot comparison pages",
    project: "HumanoidOnline",
    state: "auditing",
    elapsedSec: 728,
    cost: { usd: 1.12 },
    blocks: { done: 2, total: 5 },
    hasDetail: false,
  },
  {
    id: "WO-1844",
    title: "Prospect research: EU integrators",
    project: "HumanoidOnline",
    state: "browsing",
    elapsedSec: 77,
    cost: { usd: 0.09 },
    blocks: { done: 0, total: 4 },
    hasDetail: false,
  },
];

export const ATTENTION: WorkOrderSummary[] = [WO_1845];

export const RECENT: WorkOrderSummary[] = [
  { id: "WO-1839", title: "Robot discovery run", project: "HumanoidOnline", state: "verified", elapsedSec: 5410, cost: { usd: 3.87 }, blocks: { done: 18, total: 18 }, when: "23:42", hasDetail: false },
  { id: "WO-1837", title: "Weekly evidence report", project: "Cloudeo core", state: "verified", elapsedSec: 1260, cost: { usd: 0.62 }, blocks: { done: 7, total: 7 }, when: "21:05", hasDetail: false },
  { id: "WO-1836", title: "Spec sheet normaliser", project: "HumanoidOnline", state: "verified", elapsedSec: 980, cost: { usd: 0.44 }, blocks: { done: 5, total: 5 }, when: "18:30", hasDetail: false },
];

export function getWorkOrder(id: string): WorkOrderDetail | undefined {
  return WORK_ORDERS[id.toUpperCase()];
}
