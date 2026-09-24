import type { Metadata } from "next";

import { PageBody, PageHeader } from "@/components/common/page-header";
import { SectionLabel } from "@/components/common/status";
import { WorkOrderRow } from "@/components/common/work-order-row";
import { ACTIVE, ATTENTION, RECENT } from "@/fixtures/work-orders";

export const metadata: Metadata = { title: "Runs" };

export default function RunsPage() {
  const groups = [
    { title: "Needs attention", items: ATTENTION, variant: "attention" as const },
    { title: "Active", items: ACTIVE, variant: "active" as const },
    { title: "Completed and verified", items: RECENT, variant: "recent" as const },
  ];
  return (
    <PageBody>
      <PageHeader title="Runs" lead="Every WorkOrder in HumanoidOnline, grouped by what it needs from you." />
      {groups.map((g) => (
        <section key={g.title} className="flex flex-col gap-1">
          <SectionLabel className="mb-1 border-b border-line-soft px-3 pb-2">
            {g.title} · {g.items.length}
          </SectionLabel>
          {g.items.map((w) => <WorkOrderRow key={w.id} summary={w} variant={g.variant} />)}
        </section>
      ))}
    </PageBody>
  );
}
