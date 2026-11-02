import type { DataSource } from "@/lib/types";

/**
 * Which WorkOrder source this deployment uses, from MISSION_CONTROL_SOURCE:
 *   demo    (default) fixtures + simulated controls
 *   control real V2 WorkOrders through CLOUDEO_API_URL, read-only
 * Any other value is a configuration error, not a silent fallback.
 */
export function dataSourceFromEnv(value = process.env.MISSION_CONTROL_SOURCE): DataSource {
  if (value === undefined || value === "" || value === "demo") return "fixture";
  if (value === "control") return "control";
  throw new Error(`MISSION_CONTROL_SOURCE must be "demo" or "control", got ${JSON.stringify(value)}`);
}

/**
 * The owner token this server presents to the Cloudeo API for owner commands
 * (ADR-038). Server-side only; it is never sent to the browser. Unset: commands off.
 */
export function ownerToken(value = process.env.CLOUDEO_MISSION_CONTROL_OWNER_TOKEN): string | null {
  return value ? value : null;
}

export function cloudeoApiUrl(value = process.env.CLOUDEO_API_URL): string {
  return (value || "http://127.0.0.1:18800").replace(/\/+$/, "");
}
