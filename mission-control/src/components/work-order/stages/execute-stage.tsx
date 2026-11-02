"use client";

import { useEffect, useRef } from "react";
import { Check } from "lucide-react";

import { Panel, PanelHeader, SectionLabel } from "@/components/common/status";
import { PauseResumeButton } from "@/components/work-order/run-controls";
import { SimulatedBrowser } from "@/components/work-order/simulated-browser";
import { formatDuration } from "@/lib/format";
import type { LiveWorkOrder } from "@/data/sources";
import { STATE_LABEL } from "@/lib/format";
import type { ActivityEvent, ExecutionView } from "@/lib/types";
import { cn } from "@/lib/utils";

function ActivityFeed({ events, running }: { events: ActivityEvent[]; running: boolean }) {
  const ref = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <ol ref={ref} aria-live="polite" aria-label="Agent activity" className="flex min-h-0 flex-1 flex-col overflow-y-auto px-3.5 pt-1.5 pb-3.5">
      {events.map((e, i) => {
        const last = i === events.length - 1;
        const now = last && running && e.kind === "step";
        return (
          <li key={e.id} className="relative grid animate-rise grid-cols-[14px_1fr_auto] gap-2.5 py-[7px]">
            {!last && <span aria-hidden className="absolute top-[22px] -bottom-2 left-[6.5px] w-px bg-line" />}
            <span
              aria-hidden
              className={cn(
                "mx-[3px] mt-[5px] size-2 rounded-full bg-muted-foreground",
                e.kind === "step" && "bg-ok",
                e.kind === "operator" && "bg-warn",
                now && "bg-brand shadow-[0_0_0_3px_color-mix(in_oklab,var(--cl-brand)_15%,transparent)]",
              )}
            />
            <div className="min-w-0">
              <div className={cn(now && "text-brand", e.kind === "operator" && "text-warn")}>{e.text}</div>
              <div className="mt-0.5 font-mono text-[11px] break-words text-muted-foreground">{e.detail}</div>
            </div>
            <span className="font-mono text-[11px] text-muted-foreground tnum">{formatDuration(e.atSec)}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** Control mode: nothing is streaming, so say so instead of simulating it. */
function RuntimeUnavailable({ wo, execution }: { wo: LiveWorkOrder; execution: ExecutionView }) {
  const current = execution.blocks.find((b) => b.id === execution.currentBlockId);
  return (
    <Panel className="flex flex-col gap-4 p-5">
      <SectionLabel>Live runtime</SectionLabel>
      <p className="text-[14px]">No executor runtime is connected to this WorkOrder.</p>
      <dl className="grid max-w-[520px] grid-cols-[170px_1fr] gap-x-3 gap-y-1.5 text-[12.5px]">
        <dt className="text-muted-foreground">Control state</dt>
        <dd className="font-mono text-[12px]">{STATE_LABEL[wo.state]}</dd>
        <dt className="text-muted-foreground">Current block</dt>
        <dd className="font-mono text-[12px]">{current ? `${current.id} · ${current.phase ?? current.status}` : "none (all blocks proven)"}</dd>
        {current?.attempts !== undefined && (
          <>
            <dt className="text-muted-foreground">Attempts recorded</dt>
            <dd className="font-mono text-[12px]">
              {current.attempts}
              {current.failedAttempts ? ` · ${current.failedAttempts} failed` : ""}
            </dd>
          </>
        )}
        <dt className="text-muted-foreground">Runtime telemetry</dt>
        <dd className="font-mono text-[12px] text-muted-foreground">unavailable</dd>
        <dt className="text-muted-foreground">Browser session</dt>
        <dd className="font-mono text-[12px] text-muted-foreground">unavailable</dd>
      </dl>
      <p className="max-w-[70ch] text-[12.5px] text-muted-foreground">
        The V2 control store records block state and evidence, not live frames, tool events, cost or elapsed time. Those appear here once a
        runtime-event adapter is connected.
      </p>
    </Panel>
  );
}

function Blocks({ execution, live }: { execution: ExecutionView; live: boolean }) {
  return (
    <ol aria-label="Blocks" className="grid grid-cols-3 gap-2.5 xl:grid-cols-6">
      {execution.blocks.map((b) => (
        <li
          key={b.id}
          className={cn(
            "flex flex-col gap-1 rounded-lg border border-line bg-panel px-3 py-2.5",
            b.status === "active" && "border-brand/35",
            b.status === "pending" && "bg-transparent",
          )}
        >
          <span className="flex items-center justify-between font-mono text-[11.5px]">
            <span className={cn(b.status === "proven" && "text-ok", b.status === "active" && "text-brand", b.status === "pending" && "text-muted-foreground")}>
              BLOCK {b.id}
            </span>
            {b.status === "proven" && <Check className="size-3.5 text-ok" aria-label="proven" />}
            {b.status === "active" && (
              <span className={cn("size-1.5 rounded-full bg-brand", live && "animate-node-pulse")} aria-label={b.phase ?? "in progress"} />
            )}
          </span>
          <span className={cn("text-[12px] text-subtle", b.status === "pending" && "text-muted-foreground")}>{b.title}</span>
          {b.phase && <span className="font-mono text-[10.5px] tracking-[0.04em] text-muted-foreground">{b.phase}</span>}
        </li>
      ))}
    </ol>
  );
}

export function ExecuteStage({ wo, execution }: { wo: LiveWorkOrder; execution: ExecutionView }) {
  if (execution.runtime === "unavailable" || !execution.browser || !execution.script) {
    return (
      <>
        <RuntimeUnavailable wo={wo} execution={execution} />
        <Blocks execution={execution} live={false} />
      </>
    );
  }
  const script = execution.script;
  const lastStep = wo.scriptIndex > 0 ? script[(wo.scriptIndex - 1) % script.length] : undefined;
  const modeText = {
    running: "Autonomous",
    paused: "Paused · nothing new starts",
    operator: "You have control · agent paused",
    stopped: "Stopped",
    static: "",
    readonly: "",
  }[wo.mode];

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <SectionLabel>Block {execution.currentBlockId}</SectionLabel>
        <span className={cn("text-[12.5px] text-subtle", wo.mode !== "running" && "text-warn")}>{modeText}</span>
        <span className="flex-1" />
        <PauseResumeButton wo={wo} />
      </div>

      <div className="grid min-h-[380px] flex-1 gap-3.5 xl:grid-cols-[1.35fr_1fr]">
        <SimulatedBrowser browser={execution.browser} step={lastStep} mode={wo.mode} woId={wo.id} />
        <Panel className="flex min-h-[300px] flex-col overflow-hidden">
          <PanelHeader>
            <SectionLabel>Agent activity</SectionLabel>
            <span className="flex-1" />
            <span className="font-mono text-[11.5px] text-muted-foreground">{wo.agent?.model}</span>
          </PanelHeader>
          <ActivityFeed events={wo.events} running={wo.mode === "running"} />
        </Panel>
      </div>

      <Blocks execution={execution} live={wo.mode === "running"} />
    </>
  );
}
