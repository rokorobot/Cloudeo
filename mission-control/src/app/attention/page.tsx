import type { Metadata } from "next";

import { AttentionList } from "@/components/common/work-order-lists";
import { PageBody, PageHeader } from "@/components/common/page-header";

export const metadata: Metadata = { title: "Attention" };

export default function AttentionPage() {
  return (
    <PageBody>
      <PageHeader
        title="Attention"
        lead="WorkOrders that stopped rather than continue under a weaker policy. Each one says why."
      />
      <AttentionList />
    </PageBody>
  );
}
