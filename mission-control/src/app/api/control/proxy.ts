import { cloudeoApiUrl, dataSourceFromEnv } from "@/data/mode";

/**
 * GET-only pass-through to the Cloudeo read API. Exists so the browser never
 * talks to the control plane directly and no write method is ever exposed.
 */
export async function proxyGet(path: string): Promise<Response> {
  if (dataSourceFromEnv() !== "control") {
    return Response.json({ detail: { error: "not_in_control_mode", message: "Mission Control is running on demo data" } }, { status: 404 });
  }
  try {
    const res = await fetch(`${cloudeoApiUrl()}${path}`, { cache: "no-store", headers: { accept: "application/json" } });
    const body = await res.text();
    return new Response(body, { status: res.status, headers: { "content-type": res.headers.get("content-type") ?? "application/json" } });
  } catch (e) {
    return Response.json(
      { detail: { error: "control_api_unreachable", message: `Cloudeo API not reachable at ${cloudeoApiUrl()}: ${(e as Error).message}` } },
      { status: 503 },
    );
  }
}

/** True only for a request this app's own pages sent (Origin and Sec-Fetch-Site), never a cross-site one. */
export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (!origin || !host) return false;
  const site = request.headers.get("sec-fetch-site");
  if (site !== null && site !== "same-origin") return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}
