import type { Metadata } from "next";
import { FolderKanban } from "lucide-react";

import { Placeholder } from "@/components/common/placeholder";

export const metadata: Metadata = { title: "Projects" };

export default function Page() {
  return (
    <Placeholder
      title="Projects"
      icon={FolderKanban}
      lead="Projects group WorkOrders, write scopes, budgets and owners."
      planned={[
      "Project settings and owners",
      "Default envelopes and risk classes",
      "Connected repositories and targets",
      ]}
    />
  );
}