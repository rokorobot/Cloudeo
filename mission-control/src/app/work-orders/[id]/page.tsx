import { WorkOrderRedirect } from "@/components/work-order/work-order-redirect";

export default async function WorkOrderIndex(props: PageProps<"/work-orders/[id]">) {
  const { id } = await props.params;
  return <WorkOrderRedirect id={decodeURIComponent(id)} />;
}
