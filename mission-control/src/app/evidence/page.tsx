import type { Metadata } from "next";
import { ShieldCheck } from "lucide-react";

import { Placeholder } from "@/components/common/placeholder";

export const metadata: Metadata = { title: "Evidence" };

export default function Page() {
  return (
    <Placeholder
      title="Evidence"
      icon={ShieldCheck}
      lead="Everything Cloudeo can prove about completed work: audits, checkpoints, test runs and source captures."
      planned={[
      "Search evidence by WorkOrder, SHA or artifact",
      "Audit reports with deterministic checks",
      "Export evidence bundles",
      ]}
    />
  );
}