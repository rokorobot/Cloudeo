import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { WorkOrderView } from "@/components/work-order/work-order-view";
import { LIFECYCLE, type LifecycleStage } from "@/lib/types";

type Props = PageProps<"/work-orders/[id]/[stage]">;

/** The WorkOrder itself is resolved by the data provider (demo or control). */
async function resolve(props: Props) {
  const { id, stage } = await props.params;
  const s = LIFECYCLE.find((x) => x === stage);
  if (!s) notFound();
  return { id: decodeURIComponent(id), stage: s as LifecycleStage };
}

export async function generateMetadata(props: Props): Promise<Metadata> {
  const { id, stage } = await resolve(props);
  return { title: `${id} · ${stage.toUpperCase()}` };
}

export default async function WorkOrderStagePage(props: Props) {
  const { id, stage } = await resolve(props);
  return <WorkOrderView id={id} stage={stage} />;
}
