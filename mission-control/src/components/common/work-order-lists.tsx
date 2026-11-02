"use client";

import Link from "next/link";
import { TriangleAlert } from "lucide-react";

import { ResultState } from "@/components/common/result-state";
import { Chip, SectionLabel } from "@/components/common/status";
import { UnsupportedRow, WorkOrderRow } from "@/components/common/work-order-row";
import { useLiveWorkOrder, useWorkOrderList } from "@/data/context";
import type { WorkOrderSummary } from "@/lib/types";
import { shortSha } from "@/lib/format";
import { woHref } from "@/lib/routes";

export function RunsList() {
  const list = useWorkOrderList();
  if (list.status !== "ready") return <ResultState result={list} what="WorkOrders" />;
  const { attention, active, recent, unsupported } = list.data;
  const groups = [
    { title: "Needs attention", items: attention, variant: "attention" as const },
    { title: "Active", items: active, variant: "active" as const },
    { title: "Finished", items: recent, variant: "recent" as const },
  ];
  return (
    <>
      {unsupported.length > 0 && (
        <section className="flex flex-col gap-1">
          <SectionLabel className="mb-1 border-b border-line-soft px-3 pb-2 text-err">Unsupported · {unsupported.length}</SectionLabel>
          {unsupported.map((u) => <UnsupportedRow key={u.id} item={u} />)}
        </section>
      )}
      {groups.map((g) => (
        <section key={g.title} className="flex flex-col gap-1">
          <SectionLabel className="mb-1 border-b border-line-soft px-3 pb-2">
            {g.title} · {g.items.length}
          </SectionLabel>
          {g.items.map((w) => <WorkOrderRow key={w.id} summary={w} variant={g.variant} />)}
        </section>
      ))}
    </>
  );
}

function AttentionCard({ summary }: { summary: WorkOrderSummary }) {
  // Detail gives the headline; loaded per card (few WorkOrders are in attention at once).
  const wo = useLiveWorkOrder(summary.id);
  const a = wo?.attention;
  return (
    <Link
      href={woHref(summary.id, wo?.currentStage)}
      className="flex flex-col gap-2.5 rounded-lg border border-warn/40 bg-warn/[0.06] p-4 transition-colors hover:bg-warn/[0.1]"
    >
      <div className="flex flex-wrap items-center gap-2.5">
        <TriangleAlert className="size-4 text-warn" />
        <span className="font-mono text-[13px] text-warn">{summary.reason}</span>
        <span className="flex-1" />
        <Chip>{summary.id}</Chip>
      </div>
      <span className="text-[15px]">{summary.title}</span>
      {a && (
        <span className="text-subtle">
          {a.headline}
          {a.pausedAtCheckpoint && (
            <>
              {" "}Accepted checkpoint <span className="font-mono text-[12px]">{shortSha(a.pausedAtCheckpoint)}</span>
              {a.since ? ` since ${a.since}` : ""}.
            </>
          )}
        </span>
      )}
    </Link>
  );
}

export function AttentionList() {
  const list = useWorkOrderList();
  if (list.status !== "ready") return <ResultState result={list} what="WorkOrders" />;
  if (!list.data.attention.length) return <p className="text-muted-foreground">Nothing needs your attention.</p>;
  return (
    <div className="flex flex-col gap-3">
      {list.data.attention.map((s) => <AttentionCard key={s.id} summary={s} />)}
    </div>
  );
}
