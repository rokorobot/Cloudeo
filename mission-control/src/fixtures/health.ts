import type { SystemHealth } from "@/lib/types";

export const HEALTH: SystemHealth = {
  verifiedToday: 7,
  spendToday: { usd: 11.84 },
  recoveriesToday: { succeeded: 3, attempted: 3 },
  runtimes: [
    { name: "Claude Code", kind: "executor", status: "healthy", detail: "UHP 2026-09-12 · p50 1.1 s" },
    { name: "Codex", kind: "executor", status: "degraded", detail: "Elevated latency · p50 4.8 s" },
    { name: "Jev browser", kind: "browser", status: "healthy", detail: "3 of 8 sessions in use" },
    { name: "GPT-5.6 auditor", kind: "auditor", status: "healthy", detail: "Read-only · OpenAI via HarnessRouter" },
    { name: "Final verifier", kind: "verifier", status: "unavailable", detail: "No independent provider for Anthropic executors" },
    { name: "Treg", kind: "tools", status: "healthy", detail: "142 capabilities" },
  ],
};
