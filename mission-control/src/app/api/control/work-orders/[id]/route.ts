import { proxyGet } from "@/app/api/control/proxy";

export async function GET(_req: Request, ctx: RouteContext<"/api/control/work-orders/[id]">) {
  const { id } = await ctx.params;
  return proxyGet(`/v1/mission-control/work-orders/${encodeURIComponent(id)}`);
}
