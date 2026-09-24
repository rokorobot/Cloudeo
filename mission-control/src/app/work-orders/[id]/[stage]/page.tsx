import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { WorkOrderView } from "@/components/work-order/work-order-view";
import { getWorkOrder, WORK_ORDERS } from "@/fixtures/work-orders";
import { LIFECYCLE, type LifecycleStage } from "@/lib/types";

type Props = PageProps<"/work-orders/[id]/[stage]">;

export function generateStaticParams() {
  return Object.keys(WORK_ORDERS).flatMap((id) => LIFECYCLE.map((stage) => ({ id, stage })));
}

async function resolve(props: Props) {
  const { id, stage } = await props.params;
  const wo = getWorkOrder(decodeURIComponent(id));
  const s = LIFECYCLE.find((x) => x === stage);
  if (!wo || !s) notFound();
  return { wo, stage: s as LifecycleStage };
}

export async function generateMetadata(props: Props): Promise<Metadata> {
  const { wo, stage } = await resolve(props);
  return { title: `${wo.id} · ${stage.toUpperCase()}` };
}

export default async function WorkOrderStagePage(props: Props) {
  const { wo, stage } = await resolve(props);
  return <WorkOrderView id={wo.id} stage={stage} />;
}
