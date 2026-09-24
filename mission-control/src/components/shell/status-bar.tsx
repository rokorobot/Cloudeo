"use client";

import Link from "next/link";

import { Dot, PROVIDER_DOT } from "@/components/common/status";
import { useHealth, useLiveWorkOrder, useWorkOrderList } from "@/data/context";
import type { LiveWorkOrder } from "@/data/sources";
import { formatDuration, formatMoney, STATE_LABEL } from "@/lib/format";
import { useOpenWorkOrder, woHref } from "@/lib/routes";

function Counts() {
  const list = useWorkOrderList();
  if (list.status !== "ready") return null;
  return (
    <span className="max-lg:hidden">
      {list.data.active.length} active ·{" "}
      <Link href="/attention" className="text-warn hover:underline">
        {list.data.attention.length} attention
      </Link>
    </span>
  );
}

/** Demo: live runtime dots and the simulated run's clock. */
function SimulatedRuntime({ wo }: { wo: LiveWorkOrder | undefined }) {
  const health = useHealth();
  const executor = wo?.mode === "running" ? "running" : wo?.mode === "stopped" ? "err" : "warn";
  const browser = wo?.mode === "operator" ? "warn" : wo?.mode === "running" ? "running" : "idle";
  const auditor = health?.runtimes.find((r) => r.kind === "auditor");
  const verifier = health?.runtimes.find((r) => r.kind === "verifier");
  return (
    <>
      <span className="flex items-center gap-1.5"><Dot kind={executor} />Executor</span>
      <span className="flex items-center gap-1.5">
        <Dot kind={browser} />
        {wo?.mode === "operator" ? "Browser · you" : "Browser"}
      </span>
      {auditor && <span className="flex items-center gap-1.5 max-md:hidden"><Dot kind={PROVIDER_DOT[auditor.status]} />Auditor</span>}
      {verifier && <span className="flex items-center gap-1.5 max-md:hidden"><Dot kind={PROVIDER_DOT[verifier.status]} />Verifier</span>}
    </>
  );
}

export function StatusBar() {
  const open = useOpenWorkOrder();
  const health = useHealth();
  const list = useWorkOrderList();
  // Demo: follow the open WorkOrder if it is live, otherwise the first active one.
  const primary = list.status === "ready" ? list.data.active.find((s) => s.hasDetail)?.id : undefined;
  const openWo = useLiveWorkOrder(open.id);
  const simulated = useLiveWorkOrder(health ? primary : undefined);
  const wo = openWo?.execution?.runtime === "simulated" ? openWo : simulated;

  return (
    <footer className="flex h-8 items-center gap-4 border-t border-line px-4 text-[12px] text-subtle">
      {health ? (
        <SimulatedRuntime wo={wo} />
      ) : (
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <Dot kind="idle" />
          Runtime telemetry unavailable · control store read-only
        </span>
      )}
      <div className="flex-1" />
      <Counts />
      {health && wo && wo.elapsedSec !== undefined && wo.cost && (
        <Link href={woHref(wo.id, wo.currentStage)} className="flex items-center gap-4 font-mono text-[11.5px] tnum hover:text-foreground">
          <span className="text-muted-foreground max-md:hidden">{wo.id}</span>
          <span>{formatDuration(wo.elapsedSec)} elapsed</span>
          <span>{formatMoney(wo.cost)}</span>
          {wo.steps !== undefined && <span className="max-md:hidden">{wo.steps} steps</span>}
        </Link>
      )}
      {!health && openWo && (
        <span className="font-mono text-[11.5px]">
          <span className="text-muted-foreground">{openWo.id}</span> · {STATE_LABEL[openWo.state]}
          {openWo.version !== undefined && <span className="text-muted-foreground"> · record v{openWo.version}</span>}
        </span>
      )}
    </footer>
  );
}
