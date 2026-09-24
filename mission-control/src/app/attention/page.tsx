import type { Metadata } from "next";
import Link from "next/link";
import { TriangleAlert } from "lucide-react";

import { PageBody, PageHeader } from "@/components/common/page-header";
import { Chip } from "@/components/common/status";
import { ATTENTION, getWorkOrder } from "@/fixtures/work-orders";

export const metadata: Metadata = { title: "Attention" };

export default function AttentionPage() {
  return (
    <PageBody>
      <PageHeader
        title="Attention"
        lead="WorkOrders that Cloudeo paused rather than continue under a weaker policy. Each one says why and what you can do."
      />
      <div className="flex flex-col gap-3">
        {ATTENTION.map((s) => {
          const wo = getWorkOrder(s.id);
          const a = wo?.attention;
          return (
            <Link
              key={s.id}
              href={`/work-orders/${s.id}/${wo?.currentStage ?? ""}`}
              className="flex flex-col gap-2.5 rounded-lg border border-warn/40 bg-warn/[0.06] p-4 transition-colors hover:bg-warn/[0.1]"
            >
              <div className="flex flex-wrap items-center gap-2.5">
                <TriangleAlert className="size-4 text-warn" />
                <span className="font-mono text-[13px] text-warn">{s.reason}</span>
                <span className="flex-1" />
                <Chip>{s.id}</Chip>
              </div>
              <span className="text-[15px]">{s.title}</span>
              {a && (
                <span className="text-subtle">
                  {a.headline} Paused at <span className="font-mono text-[12px]">{a.pausedAtCheckpoint}</span> since {a.since}.
                </span>
              )}
            </Link>
          );
        })}
      </div>
    </PageBody>
  );
}
