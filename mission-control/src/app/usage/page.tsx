import type { Metadata } from "next";
import { Gauge } from "lucide-react";

import { Placeholder } from "@/components/common/placeholder";

export const metadata: Metadata = { title: "Usage" };

export default function Page() {
  return (
    <Placeholder
      title="Usage"
      icon={Gauge}
      lead="Cost, time and verified outcomes over time. Kept off the home screen on purpose."
      planned={[
      "Spend by project, profile and runtime",
      "Verified success versus runtime completion",
      "Budget alerts",
      ]}
    />
  );
}