import type { Metadata } from "next";

import { RunsList } from "@/components/common/work-order-lists";
import { PageBody, PageHeader } from "@/components/common/page-header";

export const metadata: Metadata = { title: "Runs" };

export default function RunsPage() {
  return (
    <PageBody>
      <PageHeader title="Runs" lead="Every WorkOrder, grouped by what it needs from you." />
      <RunsList />
    </PageBody>
  );
}
