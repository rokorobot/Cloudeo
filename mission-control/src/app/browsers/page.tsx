import type { Metadata } from "next";
import { PanelTop } from "lucide-react";

import { Placeholder } from "@/components/common/placeholder";

export const metadata: Metadata = { title: "Browsers" };

export default function Page() {
  return (
    <Placeholder
      title="Browsers"
      icon={PanelTop}
      lead="Live and recorded browser sessions used by WorkOrders."
      planned={[
      "Session grid with live previews",
      "Recordings attached to block evidence",
      "Operator takeover history",
      ]}
    />
  );
}