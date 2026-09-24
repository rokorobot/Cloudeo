import type { Metadata } from "next";
import { Bot } from "lucide-react";

import { Placeholder } from "@/components/common/placeholder";

export const metadata: Metadata = { title: "Agents" };

export default function Page() {
  return (
    <Placeholder
      title="Agents"
      icon={Bot}
      lead="Execution roles such as primary-code, auditor and final_verifier, and which profile currently fills each one."
      planned={[
      "Role → profile assignments per project",
      "Recent verified outcomes per role",
      "Independence rules between roles",
      ]}
    />
  );
}