import type { Metadata } from "next";
import { ListChecks } from "lucide-react";

import { Placeholder } from "@/components/common/placeholder";

export const metadata: Metadata = { title: "Profiles" };

export default function Page() {
  return (
    <Placeholder
      title="Profiles"
      icon={ListChecks}
      lead="ExecutionProfiles: the harness, model, tools and permissions Cloudeo routes to."
      planned={[
      "Profile registry with version fingerprints",
      "Quarantine and promotion status from upstream validation",
      "Diff between profile versions",
      ]}
    />
  );
}