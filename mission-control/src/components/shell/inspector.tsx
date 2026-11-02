"use client";

import Link from "next/link";

import { Dot, PROVIDER_DOT, PROVIDER_TEXT, SectionLabel, StateChip, stateDot } from "@/components/common/status";
import { NOT_CONNECTED, PauseResumeButton, StopButton } from "@/components/work-order/run-controls";
import { Button } from "@/components/ui/button";
import { useHealth, useLiveWorkOrder, useRunCommands, useWorkOrderList } from "@/data/context";
import type { LiveWorkOrder } from "@/data/sources";
import { formatDuration, formatMoney, formatTimestamp, STATE_LABEL } from "@/lib/format";
import { useOpenWorkOrder, woHref } from "@/lib/routes";
import type { RuntimeKind, SystemHealth } from "@/lib/types";
import { cn } from "@/lib/utils";

type Row = [string, React.ReactNode, string?];

function KV({ rows }: { rows: Row[] }) {
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

const UNAVAILABLE = "text-muted-foreground";

function WorkOrderInspector({ wo }: { wo: LiveWorkOrder }) {
  const { stage } = useOpenWorkOrder();
  const commands = useRunCommands(wo.id);
  const control = wo.source === "control";
  const finished = ["promoted", "aborted", "verified", "stopped"].includes(wo.state);
  const agentRows: Row[] = wo.agent
    ? [
        ["Role", wo.agent.role, "font-mono text-[12px]"],
        ...(wo.agent.profile ? [["Profile", wo.agent.profile, "font-mono text-[12px]"] as Row] : []),
        ...(wo.agent.model ? [["Model", wo.agent.model] as Row] : []),
        ["Runtime", wo.agent.runtime ?? "not connected", wo.agent.runtime ? undefined : UNAVAILABLE],
      ]
    : [["Agent", "no attempt recorded", UNAVAILABLE]];
  const pct = wo.cost && wo.budget?.usd ? Math.min(100, (wo.cost.usd / wo.budget.usd) * 100) : undefined;

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
        <KV rows={agentRows} />
      </Group>
      <Group title="Policy">
        <KV
          rows={[
            ["Profile", `${wo.profile.id} ${wo.profile.version}`, "font-mono text-[12px]"],
            ["Risk", wo.risk ?? "no approved plan", cn("capitalize", wo.risk === "high" && "text-warn", !wo.risk && UNAVAILABLE)],
            ["Evidence", `${wo.evidenceCount} ${control ? "refs" : "artifacts"}`, "font-mono text-[12px]"],
            ...(wo.budget?.maxAttemptsPerBlock ? [["Attempts / block", wo.budget.maxAttemptsPerBlock, "font-mono text-[12px]"] as Row] : []),
            ["Elapsed", wo.elapsedSec !== undefined ? formatDuration(wo.elapsedSec) : "not recorded", wo.elapsedSec !== undefined ? "font-mono text-[12px] tnum" : UNAVAILABLE],
          ]}
        />
      </Group>
      {pct !== undefined && wo.cost && wo.budget?.usd !== undefined ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex justify-between text-[12px] text-subtle">
            <span>Cost</span>
            <span className="font-mono tnum">
              {formatMoney(wo.cost)} / {formatMoney({ usd: wo.budget.usd })}
            </span>
          </div>
          <div className="h-[3px] overflow-hidden rounded bg-line" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-label="Budget used">
            <i className="block h-full rounded bg-brand transition-[width] duration-500" style={{ width: `${pct}%` }} />
          </div>
        </div>
      ) : (
        <KV rows={[["Cost", "not recorded", UNAVAILABLE]]} />
      )}

      {!!wo.history?.length && (
        <Group title="History">
          <ol className="flex flex-col gap-1">
            {wo.history.slice(-6).map((h) => (
              <li key={h.version} className="grid grid-cols-[28px_1fr] gap-2 text-[12px]">
                <span className="font-mono text-muted-foreground">v{h.version}</span>
                <span className="truncate">
                  <span className="font-mono text-[11.5px]">{h.event}</span>
                  <span className="text-muted-foreground"> · {STATE_LABEL[h.state]}</span>
                </span>
              </li>
            ))}
          </ol>
          {wo.timestamps?.length ? (
            <span className="text-[11.5px] text-muted-foreground">
              Last recorded time: {formatTimestamp(wo.timestamps[wo.timestamps.length - 1].at)}
            </span>
          ) : null}
        </Group>
      )}

      <div className="mt-auto flex flex-col gap-2">
        {wo.attention && stage !== wo.currentStage && (
          <Button asChild size="sm">
            <Link href={woHref(wo.id, wo.currentStage)}>{control ? "Open attention" : "Resolve attention"}</Link>
          </Button>
        )}
        {(wo.execution || control) && !finished && (
          <div className="grid grid-cols-2 gap-2">
            <PauseResumeButton wo={wo} />
            <StopButton wo={wo} />
          </div>
        )}
        {!commands && control && !finished && <span className="text-center text-[11.5px] text-muted-foreground">{NOT_CONNECTED}</span>}
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

function FixtureHealth({ health }: { health: SystemHealth }) {
  const kinds: RuntimeKind[] = ["executor", "browser", "auditor", "verifier", "tools"];
  return (
    <>
      <Group title="Today">
        <KV
          rows={[
            ["Verified runs", health.verifiedToday, "font-mono text-ok"],
            ["Spend", formatMoney(health.spendToday), "font-mono"],
            ["Recoveries", `${health.recoveriesToday.succeeded} of ${health.recoveriesToday.attempted}`, "font-mono"],
          ]}
        />
      </Group>
      {kinds.map((kind) => (
        <Group key={kind} title={KIND_LABEL[kind]}>
          {health.runtimes
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

/** Control mode: what the control store can say, and explicitly what it cannot. */
function ControlHealth() {
  const list = useWorkOrderList();
  const counts = list.status === "ready" ? list.data : undefined;
  return (
    <>
      <Group title="Control store">
        {counts ? (
          <KV
            rows={[
              ["Active", counts.active.length, "font-mono"],
              ["Attention", counts.attention.length, cn("font-mono", counts.attention.length > 0 && "text-warn")],
              ["Promoted", counts.recent.filter((s) => s.state === "promoted").length, "font-mono text-ok"],
              ["Aborted", counts.recent.filter((s) => s.state === "aborted").length, "font-mono"],
              ...(counts.unsupported.length ? [["Unsupported", counts.unsupported.length, "font-mono text-err"] as Row] : []),
            ]}
          />
        ) : (
          <span className="text-[12px] text-muted-foreground">{list.status === "loading" ? "Loading…" : "Not reachable"}</span>
        )}
      </Group>
      <Group title="Runtime health">
        <KV
          rows={[
            ["Verified runs today", "not reported", UNAVAILABLE],
            ["Executor runtime", "not reported", UNAVAILABLE],
            ["Browser runtime", "not reported", UNAVAILABLE],
            ["Auditor", "not reported", UNAVAILABLE],
            ["Verifier", "not reported", UNAVAILABLE],
          ]}
        />
        <span className="text-[11.5px] text-muted-foreground">The V2 control store does not record runtime health.</span>
      </Group>
    </>
  );
}

export function Inspector() {
  const { id } = useOpenWorkOrder();
  const wo = useLiveWorkOrder(id);
  const health = useHealth();
  return (
    <aside aria-label="Inspector" className="flex h-full flex-col gap-5 overflow-y-auto p-4">
      {wo ? <WorkOrderInspector wo={wo} /> : health ? <FixtureHealth health={health} /> : <ControlHealth />}
    </aside>
  );
}
