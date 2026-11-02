import { sameOrigin } from "@/app/api/control/proxy";
import { cloudeoApiUrl, dataSourceFromEnv, ownerToken } from "@/data/mode";

/**
 * The one write route in Mission Control (ADR-038): forwards an owner command
 * to the Cloudeo API with this server's owner token.
 *
 * The browser never sees the token. Only same-origin requests from this app
 * are accepted, so another site cannot make the owner's browser send a
 * command. Only {command, expectedVersion, message} is forwarded; the actor
 * is configured on the API, never taken from a request.
 */
function refuse(status: number, error: string, message: string) {
  return Response.json({ detail: { error, message } }, { status });
}

export async function POST(request: Request, ctx: RouteContext<"/api/control/work-orders/[id]/commands">) {
  if (dataSourceFromEnv() !== "control") return refuse(404, "not_in_control_mode", "Mission Control is running on demo data");
  const token = ownerToken();
  if (!token) return refuse(503, "commands_not_configured", "CLOUDEO_MISSION_CONTROL_OWNER_TOKEN is not set on the Mission Control server");
  if (!sameOrigin(request)) return refuse(403, "cross_origin", "owner commands are accepted from this Mission Control app only");
  if (!(request.headers.get("content-type") ?? "").startsWith("application/json")) {
    return refuse(415, "json_required", "send application/json");
  }
  let body: { command?: unknown; expectedVersion?: unknown; message?: unknown };
  try {
    body = await request.json();
  } catch {
    return refuse(400, "bad_json", "the body is not JSON");
  }
  const { id } = await ctx.params;
  const forwarded = { command: body.command, expectedVersion: body.expectedVersion, message: body.message ?? "" };
  try {
    const res = await fetch(`${cloudeoApiUrl()}/v1/mission-control/work-orders/${encodeURIComponent(id)}/commands`, {
      method: "POST",
      cache: "no-store",
      headers: { "content-type": "application/json", accept: "application/json", authorization: `Bearer ${token}` },
      body: JSON.stringify(forwarded),
    });
    return new Response(await res.text(), {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
    });
  } catch (e) {
    return refuse(503, "control_api_unreachable", `Cloudeo API not reachable at ${cloudeoApiUrl()}: ${(e as Error).message}`);
  }
}
