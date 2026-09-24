"use client";

import Link from "next/link";
import { Check, TriangleAlert } from "lucide-react";

import { Dot } from "@/components/common/status";
import { formatDuration, STATE_LABEL } from "@/lib/format";
import { woHref } from "@/lib/routes";
import type { WorkOrderSummary } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useLiveWorkOrder } from "@/state/mission-control";

const GRID = "grid grid-cols-[18px_1fr_auto] items-center gap-3 rounded-md px-3 py-2.5 md:grid-cols-[18px_1fr_auto_72px]";

/**
 * One WorkOrder in a list. Rows with full fixture detail link to the WorkOrder;
 * summary-only rows render the same but are not interactive.
 */
export function WorkOrderRow({ summary, variant }: { summary: WorkOrderSummary; variant: "active" | "attention" | "recent" }) {
  const live = useLiveWorkOrder(summary.hasDetail ? summary.id : undefined);
  const wo = live ?? summary;
  const reason = wo.reason ?? STATE_LABEL[wo.state];

  const icon =
    variant === "attention" ? <TriangleAlert className="size-3.5 text-warn" /> :
    variant === "recent" ? <Check className="size-3.5 text-ok" /> :
    <Dot kind={wo.state === "paused" || wo.state === "operator" ? "warn" : "running"} className="ml-[3px]" />;

  const time = variant === "recent" ? wo.when : formatDuration(wo.elapsedSec);
  const meta =
    variant === "recent" ? `${wo.blocks?.total ?? "—"} blocks verified` : reason;

  const body = (
    <>
      {icon}
      <span className="flex min-w-0 items-baseline gap-2.5">
        <span className="truncate">{wo.title}</span>
        <span className="font-mono text-[11px] text-muted-foreground max-md:hidden">{wo.id}</span>
      </span>
      <span
        className={cn(
          "font-mono text-[11px] tracking-[0.06em] text-subtle",
          variant === "attention" && "text-warn",
          variant === "recent" && "tracking-normal",
          (wo.state === "paused" || wo.state === "operator") && "text-warn",
        )}
      >
        {meta}
      </span>
      <span className="text-right font-mono text-[12px] text-muted-foreground tnum max-md:hidden">{time}</span>
    </>
  );

  const tone = variant === "attention" ? "border border-warn/40 bg-warn/[0.07]" : "";

  if (!summary.hasDetail) {
    return <div className={cn(GRID, tone)} title="Summary only in this fixture set">{body}</div>;
  }
  return (
    <Link
      href={woHref(summary.id, live?.currentStage)}
      className={cn(GRID, tone, "transition-colors", variant === "attention" ? "hover:bg-warn/[0.11]" : "hover:bg-panel")}
    >
      {body}
    </Link>
  );
}
