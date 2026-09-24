"use client";

import Link from "next/link";
import { Ban, Check, OctagonX, TriangleAlert } from "lucide-react";

import { Dot, stateDot } from "@/components/common/status";
import { useLiveWorkOrder } from "@/data/context";
import { formatDuration, STATE_LABEL } from "@/lib/format";
import { woHref } from "@/lib/routes";
import type { UnsupportedWorkOrder, WorkOrderSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const GRID = "grid grid-cols-[18px_1fr_auto] items-center gap-3 rounded-md px-3 py-2.5 md:grid-cols-[18px_1fr_auto_72px]";

const SUCCESS = new Set(["promoted", "verified"]);

/**
 * One WorkOrder in a list. Rows with detail link to the WorkOrder; summary-only
 * demo rows render the same but are not interactive.
 */
export function WorkOrderRow({ summary, variant }: { summary: WorkOrderSummary; variant: "active" | "attention" | "recent" }) {
  // Only the demo source has a live simulation worth following in a list row.
  const live = useLiveWorkOrder(summary.source === "fixture" && summary.hasDetail ? summary.id : undefined);
  const wo = live ?? summary;
  const success = SUCCESS.has(wo.state);

  const icon =
    variant === "attention" ? <TriangleAlert className="size-3.5 text-warn" /> :
    variant === "recent" ? (success ? <Check className="size-3.5 text-ok" /> : <OctagonX className="size-3.5 text-err" />) :
    <Dot kind={stateDot(wo.state)} className="ml-[3px]" />;

  const time =
    variant === "recent" ? wo.when :
    wo.elapsedSec !== undefined ? formatDuration(wo.elapsedSec) :
    wo.blocks ? `${wo.blocks.done}/${wo.blocks.total}` : undefined;
  const meta =
    variant === "recent" && success ? `${wo.blocks?.total ?? "—"} ${wo.blocks?.total === 1 ? "block" : "blocks"} verified` : wo.reason ?? STATE_LABEL[wo.state];
  const warn = variant === "attention" || wo.state === "paused" || wo.state === "operator";

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
          warn && "text-warn",
          variant === "recent" && success && "tracking-normal",
          variant === "recent" && !success && "text-err",
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

/** A stored WorkOrder the adapter refused to present. Visible, never dropped. */
export function UnsupportedRow({ item }: { item: UnsupportedWorkOrder }) {
  return (
    <div className={cn(GRID, "border border-err/35 bg-err/[0.06]")} role="alert">
      <Ban className="size-3.5 text-err" />
      <span className="flex min-w-0 items-baseline gap-2.5">
        <span className="font-mono text-[12px]">{item.id}</span>
        <span className="truncate text-[12px] text-subtle">{item.unsupported}</span>
      </span>
      <span className="font-mono text-[11px] tracking-[0.06em] text-err">UNSUPPORTED</span>
      <span className="max-md:hidden" />
    </div>
  );
}
