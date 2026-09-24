"use client";

import { StateChip } from "@/components/common/status";
import { LifecycleBar } from "@/components/work-order/lifecycle-bar";
import { AttentionPanel } from "@/components/work-order/stages/attention-panel";
import { AuditStage } from "@/components/work-order/stages/audit-stage";
import { CheckpointStage } from "@/components/work-order/stages/checkpoint-stage";
import { ExecuteStage } from "@/components/work-order/stages/execute-stage";
import { FutureStage } from "@/components/work-order/stages/future-stage";
import { MemoryStage } from "@/components/work-order/stages/memory-stage";
import { PlanStage } from "@/components/work-order/stages/plan-stage";
import { NotRecorded } from "@/components/work-order/stages/not-recorded";
import { formatDuration, formatMoney } from "@/lib/format";
import type { LifecycleStage } from "@/lib/types";
import { useLiveWorkOrder, type LiveWorkOrder } from "@/state/mission-control";

function Meta({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-muted-foreground">{label}</span>
      <span className={className}>{children}</span>
    </span>
  );
}

function Header({ wo }: { wo: LiveWorkOrder }) {
  return (
    <header className="flex flex-col gap-2">
      <span className="font-mono text-[12px] text-muted-foreground">
        {wo.id} · {wo.project} · created {wo.createdAt}
      </span>
      <h1 className="text-[22px] font-medium tracking-[-0.015em] text-balance">{wo.title}</h1>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px] text-subtle">
        <StateChip state={wo.state} />
        {wo.reason && <span className="font-mono text-[11.5px] text-warn">{wo.reason}</span>}
        <Meta label="Risk" className={wo.risk === "high" ? "text-warn capitalize" : "capitalize"}>{wo.risk}</Meta>
        <Meta label="Profile" className="font-mono text-[12px]">{wo.profile.id} {wo.profile.version}</Meta>
        {wo.blocks && <Meta label="Block" className="font-mono text-[12px] tnum">{wo.blocks.done + (wo.execution ? 1 : 0)} / {wo.blocks.total}</Meta>}
        <Meta label="Elapsed" className="font-mono text-[12px] tnum">{formatDuration(wo.elapsedSec)}</Meta>
        <Meta label="Cost" className="font-mono text-[12px] tnum">{formatMoney(wo.cost)}</Meta>
      </div>
    </header>
  );
}

function StageContent({ wo, stage }: { wo: LiveWorkOrder; stage: LifecycleStage }) {
  if (wo.attention && stage === wo.currentStage) return <AttentionPanel wo={wo} attention={wo.attention} />;
  switch (stage) {
    case "plan":
      return <PlanStage wo={wo} plan={wo.plan} />;
    case "execute":
      return wo.execution ? <ExecuteStage wo={wo} execution={wo.execution} /> : <NotRecorded stage="execute" wo={wo} />;
    case "audit":
      return wo.audit ? <AuditStage audit={wo.audit} /> : <NotRecorded stage="audit" wo={wo} />;
    case "memory":
      return <MemoryStage memory={wo.memory} />;
    case "checkpoint":
      return <CheckpointStage checkpoints={wo.checkpoints} />;
    case "verify":
      return <FutureStage stage="verify" view={wo.verify} status={wo.stages.verify} />;
    case "promote":
      return <FutureStage stage="promote" view={wo.promote} status={wo.stages.promote} />;
  }
}

export function WorkOrderView({ id, stage }: { id: string; stage: LifecycleStage }) {
  const wo = useLiveWorkOrder(id);
  if (!wo) return null;
  return (
    <div className="flex min-h-full flex-col gap-4.5 px-6.5 pt-5.5 pb-7 max-md:px-4">
      <Header wo={wo} />
      <LifecycleBar id={wo.id} stages={wo.stages} selected={stage} />
      <div className="flex min-h-0 flex-1 flex-col gap-3.5">
        <StageContent wo={wo} stage={stage} />
      </div>
    </div>
  );
}
