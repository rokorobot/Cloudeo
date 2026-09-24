import { Panel, SectionLabel } from "@/components/common/status";
import type { Result } from "@/data/sources";
import { cn } from "@/lib/utils";

const TITLE = {
  unsupported: "Unsupported control state",
  unavailable: "Control store unavailable",
  failed: "Could not read from the control plane",
};

/** Loading, not-found and error states for anything read from a data source. */
export function ResultState({ result, what }: { result: Exclude<Result<unknown>, { status: "ready" }>; what: string }) {
  if (result.status === "loading") {
    return <p className="px-1 py-6 text-muted-foreground" role="status">Loading {what}…</p>;
  }
  if (result.status === "not_found") {
    return (
      <Panel className="flex flex-col gap-2 p-5">
        <SectionLabel>Not found</SectionLabel>
        <p className="text-subtle">No {what} with this ID exists in the current source.</p>
      </Panel>
    );
  }
  const unsupported = result.kind === "unsupported";
  return (
    <Panel role="alert" className={cn("flex flex-col gap-2 p-5", unsupported ? "border-err/40" : "border-warn/40")}>
      <SectionLabel className={unsupported ? "text-err" : "text-warn"}>{TITLE[result.kind]}</SectionLabel>
      <p className="font-mono text-[12px] break-words text-subtle">{result.message}</p>
      {unsupported && (
        <p className="max-w-[70ch] text-[12.5px] text-muted-foreground">
          Mission Control does not map this state to a guess. Update the read adapter to present it explicitly.
        </p>
      )}
    </Panel>
  );
}
