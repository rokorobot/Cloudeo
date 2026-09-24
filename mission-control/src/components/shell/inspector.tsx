"use client";

import Link from "next/link";

import { Dot, PROVIDER_DOT, PROVIDER_TEXT, SectionLabel, StateChip, stateDot } from "@/components/common/status";
import { PauseResumeButton, StopButton } from "@/components/work-order/run-controls";
import { Button } from "@/components/ui/button";
import { HEALTH } from "@/fixtures/health";
import { formatDuration, formatMoney } from "@/lib/format";
import { useOpenWorkOrder, woHref } from "@/lib/routes";
import type { RuntimeKind } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useLiveWorkOrder, type LiveWorkOrder } from "@/state/mission-control";

function KV({ rows }: { rows: [string, React.ReactNode, string?][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
      {rows.map(([k, v, cls]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className={cn("truncate text-right", cls)}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5">
      <SectionLabel>{title}</SectionLabel>
      {children}
    </div>
  );
}

function WorkOrderInspector({ wo }: { wo: LiveWorkOrder }) {
  const pct = Math.min(100, (wo.cost.usd / wo.budget.usd) * 100);
  return (
    <>
      <Group title="State">
        <div className="flex items-center gap-2">
          <Dot kind={stateDot(wo.state)} />
          <StateChip state={wo.state} />
        </div>
        {wo.reason && <span className="font-mono text-[11.5px] text-warn">{wo.reason}</span>}
      </Group>
      <Group title="Agent">
        <KV
          rows={[
            ["Role", wo.agent.role, "font-mono text-[12px]"],
            ["Model", wo.agent.model],
            ["Runtime", wo.agent.runtime],
          ]}
        />
      </Group>
      <Group title="Policy">
        <KV
          rows={[
            ["Profile", `${wo.profile.id} ${wo.profile.version}`, "font-mono text-[12px]"],
            ["Risk", wo.risk, cn("capitalize", wo.risk === "high" && "text-warn")],
            ["Evidence", `${wo.evidenceCount} artifacts`, "font-mono text-[12px]"],
            ["Elapsed", formatDuration(wo.elapsedSec), "font-mono text-[12px] tnum"],
          ]}
        />
      </Group>
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-[12px] text-subtle">
          <span>Cost</span>
          <span className="font-mono tnum">
            {formatMoney(wo.cost)} / {formatMoney(wo.budget)}
          </span>
        </div>
        <div className="h-[3px] overflow-hidden rounded bg-line" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-label="Budget used">
          <i className="block h-full rounded bg-brand transition-[width] duration-500" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <div className="mt-auto grid grid-cols-2 gap-2">
        {wo.execution ? (
          <>
            <PauseResumeButton wo={wo} />
            <StopButton wo={wo} />
          </>
        ) : wo.attention ? (
          <Button asChild size="sm" className="col-span-2">
            <Link href={woHref(wo.id, wo.currentStage)}>Resolve attention</Link>
          </Button>
        ) : null}
      </div>
    </>
  );
}

const KIND_LABEL: Record<RuntimeKind, string> = {
  executor: "Executors",
  browser: "Browser",
  auditor: "Auditor",
  verifier: "Verifier",
  tools: "Tools",
};

function HealthInspector() {
  const kinds: RuntimeKind[] = ["executor", "browser", "auditor", "verifier", "tools"];
  return (
    <>
      <Group title="Today">
        <KV
          rows={[
            ["Verified runs", HEALTH.verifiedToday, "font-mono text-ok"],
            ["Spend", formatMoney(HEALTH.spendToday), "font-mono"],
            ["Recoveries", `${HEALTH.recoveriesToday.succeeded} of ${HEALTH.recoveriesToday.attempted}`, "font-mono"],
          ]}
        />
      </Group>
      {kinds.map((kind) => (
        <Group key={kind} title={KIND_LABEL[kind]}>
          {HEALTH.runtimes
            .filter((r) => r.kind === kind)
            .map((r) => (
              <div key={r.name} className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <Dot kind={PROVIDER_DOT[r.status]} />
                  <span className="flex-1 truncate">{r.name}</span>
                  <span className={cn("text-[12px]", PROVIDER_TEXT[r.status])}>{r.status}</span>
                </div>
                <span className="pl-[15px] text-[11.5px] text-muted-foreground">{r.detail}</span>
              </div>
            ))}
        </Group>
      ))}
    </>
  );
}

export function Inspector() {
  const { id } = useOpenWorkOrder();
  const wo = useLiveWorkOrder(id);
  return (
    <aside aria-label="Inspector" className="flex h-full flex-col gap-5 overflow-y-auto p-4">
      {wo ? <WorkOrderInspector wo={wo} /> : <HealthInspector />}
    </aside>
  );
}
