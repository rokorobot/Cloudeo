"use client";

import Link from "next/link";

import { Dot, PROVIDER_DOT } from "@/components/common/status";
import { ACTIVE, ATTENTION } from "@/fixtures/work-orders";
import { HEALTH } from "@/fixtures/health";
import { formatDuration, formatMoney } from "@/lib/format";
import { useOpenWorkOrder, woHref } from "@/lib/routes";
import { useLiveWorkOrder } from "@/state/mission-control";

const LIVE_ID = ACTIVE.find((w) => w.hasDetail)?.id;

export function StatusBar() {
  const open = useOpenWorkOrder();
  // Follow the open WorkOrder if it is live; otherwise show the primary running one.
  const openWo = useLiveWorkOrder(open.id);
  const liveWo = useLiveWorkOrder(LIVE_ID);
  const wo = openWo?.execution ? openWo : liveWo;

  const executor = wo?.mode === "running" ? "running" : wo?.mode === "stopped" ? "err" : "warn";
  const browser = wo?.mode === "operator" ? "warn" : wo?.mode === "running" ? "running" : "idle";
  const auditor = HEALTH.runtimes.find((r) => r.kind === "auditor");
  const verifier = HEALTH.runtimes.find((r) => r.kind === "verifier");

  return (
    <footer className="flex h-8 items-center gap-4 border-t border-line px-4 text-[12px] text-subtle">
      <span className="flex items-center gap-1.5"><Dot kind={executor} />Executor</span>
      <span className="flex items-center gap-1.5">
        <Dot kind={browser} />
        {wo?.mode === "operator" ? "Browser · you" : "Browser"}
      </span>
      {auditor && <span className="flex items-center gap-1.5 max-md:hidden"><Dot kind={PROVIDER_DOT[auditor.status]} />Auditor</span>}
      {verifier && <span className="flex items-center gap-1.5 max-md:hidden"><Dot kind={PROVIDER_DOT[verifier.status]} />Verifier</span>}
      <div className="flex-1" />
      <span className="max-lg:hidden">
        {ACTIVE.length} running · <Link href="/attention" className="text-warn hover:underline">{ATTENTION.length} attention</Link>
      </span>
      {wo && (
        <Link href={woHref(wo.id, wo.currentStage)} className="flex items-center gap-4 font-mono text-[11.5px] tnum hover:text-foreground">
          <span className="text-muted-foreground max-md:hidden">{wo.id}</span>
          <span>{formatDuration(wo.elapsedSec)} elapsed</span>
          <span>{formatMoney(wo.cost)}</span>
          <span className="max-md:hidden">{wo.steps} steps</span>
        </Link>
      )}
    </footer>
  );
}
