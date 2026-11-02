"use client";

import { usePathname } from "next/navigation";
import { LIFECYCLE, type LifecycleStage } from "@/lib/types";

export const woHref = (id: string, stage?: LifecycleStage) =>
  stage ? `/work-orders/${id}/${stage}` : `/work-orders/${id}`;

/** WorkOrder id and stage from the current URL, if a WorkOrder is open. */
export function useOpenWorkOrder(): { id?: string; stage?: LifecycleStage } {
  const path = usePathname();
  const m = path.match(/^\/work-orders\/([^/]+)(?:\/([^/]+))?/);
  if (!m) return {};
  const stage = LIFECYCLE.find((s) => s === m[2]);
  return { id: decodeURIComponent(m[1]), stage };
}
