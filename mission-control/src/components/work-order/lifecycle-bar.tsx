import Link from "next/link";

import { woHref } from "@/lib/routes";
import { LIFECYCLE, type LifecycleStage, type StageStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<StageStatus, string> = {
  done: "done",
  active: "in progress",
  paused: "paused",
  attention: "attention",
  pending: "—",
  skipped: "n/a",
  aborted: "aborted",
};

function Mark({ status }: { status: StageStatus }) {
  return (
    <span
      aria-hidden
      className={cn(
        "relative grid size-3.5 shrink-0 place-items-center rounded-full border-[1.5px] border-[#3a414e]",
        status === "done" && "border-ok bg-ok",
        status === "active" && "border-brand",
        (status === "paused" || status === "attention") && "border-warn bg-warn/15",
        status === "skipped" && "border-dashed",
        status === "aborted" && "border-err bg-err/15",
      )}
    >
      {status === "done" && (
        <span className="h-[3px] w-1.5 -translate-y-px -rotate-45 border-b-[1.6px] border-l-[1.6px] border-ground" />
      )}
      {status === "active" && <span className="size-1.5 animate-node-pulse rounded-full bg-brand" />}
      {status === "paused" && <span className="flex gap-[1.5px]"><i className="h-1.5 w-[2px] bg-warn" /><i className="h-1.5 w-[2px] bg-warn" /></span>}
      {status === "attention" && <span className="text-[8px] leading-none font-bold text-warn">!</span>}
      {status === "aborted" && <span className="h-[1.5px] w-1.5 bg-err" />}
    </span>
  );
}

/** Lifecycle as navigation: each stage is a link that swaps the centre pane. */
export function LifecycleBar({
  id,
  stages,
  selected,
}: {
  id: string;
  stages: Record<LifecycleStage, StageStatus>;
  selected: LifecycleStage;
}) {
  return (
    <nav aria-label="WorkOrder lifecycle" className="overflow-x-auto">
      <ol className="grid min-w-[640px] grid-cols-7 overflow-hidden rounded-lg border border-line bg-panel">
        {LIFECYCLE.map((stage) => {
          const status = stages[stage];
          const on = stage === selected;
          return (
            <li key={stage} className="border-r border-line-soft last:border-r-0">
              <Link
                href={woHref(id, stage)}
                scroll={false}
                aria-current={on ? "step" : undefined}
                className={cn(
                  "relative flex flex-col gap-2 px-3 pt-2.5 pb-3 transition-colors hover:bg-hover",
                  on && "bg-raised after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-brand",
                )}
              >
                <span className="text-[10.5px] font-medium tracking-[0.1em] text-subtle uppercase">{stage}</span>
                <span
                  className={cn(
                    "flex items-center gap-2 font-mono text-[11px] text-muted-foreground",
                    status === "done" && "text-ok",
                    status === "active" && "text-brand",
                    (status === "paused" || status === "attention") && "text-warn",
                    status === "aborted" && "text-err",
                  )}
                >
                  <Mark status={status} />
                  {STATUS_LABEL[status]}
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
