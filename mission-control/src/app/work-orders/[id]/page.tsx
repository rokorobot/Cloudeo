import { notFound, redirect } from "next/navigation";

import { getWorkOrder, WORK_ORDERS } from "@/fixtures/work-orders";

export function generateStaticParams() {
  return Object.keys(WORK_ORDERS).map((id) => ({ id }));
}

/** A bare WorkOrder URL opens the stage it is currently in. */
export default async function WorkOrderIndex(props: PageProps<"/work-orders/[id]">) {
  const { id } = await props.params;
  const wo = getWorkOrder(decodeURIComponent(id));
  if (!wo) notFound();
  redirect(`/work-orders/${wo.id}/${wo.currentStage}`);
}
