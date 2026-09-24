import { proxyGet } from "@/app/api/control/proxy";

export function GET() {
  return proxyGet("/v1/mission-control/work-orders");
}
