"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { ResultState } from "@/components/common/result-state";
import { useWorkOrderResult } from "@/data/context";
import { woHref } from "@/lib/routes";

/** A bare WorkOrder URL opens the stage the WorkOrder is currently in. */
export function WorkOrderRedirect({ id }: { id: string }) {
  const router = useRouter();
  const result = useWorkOrderResult(id);
  const target = result.status === "ready" ? woHref(result.data.id, result.data.currentStage) : undefined;
  useEffect(() => {
    if (target) router.replace(target);
  }, [router, target]);
  if (result.status === "ready") return null;
  return (
    <div className="px-6.5 pt-5.5 pb-7 max-md:px-4">
      <ResultState result={result} what="WorkOrder" />
    </div>
  );
}
