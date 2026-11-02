import { cloudeoApiUrl, dataSourceFromEnv } from "@/data/mode";

/**
 * GET-only SSE pass-through to the Cloudeo control event stream. Forwards
 * Last-Event-ID so a reconnecting EventSource resumes without gaps, and aborts
 * the upstream request when the browser disconnects.
 */
export async function GET(request: Request): Promise<Response> {
  if (dataSourceFromEnv() !== "control") {
    return Response.json({ detail: { error: "not_in_control_mode", message: "Mission Control is running on demo data" } }, { status: 404 });
  }
  const headers: Record<string, string> = { accept: "text/event-stream" };
  const lastEventId = request.headers.get("last-event-id");
  if (lastEventId) headers["last-event-id"] = lastEventId;
  try {
    const res = await fetch(`${cloudeoApiUrl()}/v1/mission-control/stream`, { cache: "no-store", headers, signal: request.signal });
    if (!res.ok || !res.body) {
      return new Response(await res.text(), { status: res.status, headers: { "content-type": res.headers.get("content-type") ?? "application/json" } });
    }
    return new Response(res.body, {
      headers: { "content-type": "text/event-stream", "cache-control": "no-store", "x-accel-buffering": "no" },
    });
  } catch (e) {
    return Response.json(
      { detail: { error: "control_api_unreachable", message: `Cloudeo API not reachable at ${cloudeoApiUrl()}: ${(e as Error).message}` } },
      { status: 503 },
    );
  }
}
