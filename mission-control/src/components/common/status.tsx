import { cn } from "@/lib/utils";
import { STATE_LABEL, STATE_TONE } from "@/lib/format";
import type { ProviderStatus, Tone, WorkOrderState } from "@/lib/types";

export const TONE_TEXT: Record<Tone, string> = {
  brand: "text-brand",
  ok: "text-ok",
  warn: "text-warn",
  err: "text-err",
  neutral: "text-subtle",
};

const CHIP: Record<Tone, string> = {
  brand: "text-brand border-brand/35 bg-brand/10",
  ok: "text-ok border-ok/35 bg-ok/10",
  warn: "text-warn border-warn/40 bg-warn/10",
  err: "text-err border-err/40 bg-err/10",
  neutral: "text-subtle border-line bg-transparent",
};

/** Mono, uppercase machine-state chip. */
export function Chip({ tone = "neutral", className, children }: { tone?: Tone; className?: string; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[11px] tracking-[0.07em] whitespace-nowrap",
        CHIP[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StateChip({ state }: { state: WorkOrderState }) {
  return <Chip tone={STATE_TONE[state]}>{STATE_LABEL[state]}</Chip>;
}

type DotKind = "running" | "ok" | "warn" | "err" | "idle";

export function Dot({ kind, className }: { kind: DotKind; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block size-[7px] shrink-0 rounded-full",
        kind === "running" && "bg-brand shadow-[0_0_0_3px_color-mix(in_oklab,var(--cl-brand)_14%,transparent)]",
        kind === "ok" && "bg-ok",
        kind === "warn" && "bg-warn",
        kind === "err" && "bg-err",
        kind === "idle" && "border-[1.5px] border-muted-foreground",
        className,
      )}
    />
  );
}

export function stateDot(state: WorkOrderState): DotKind {
  const tone = STATE_TONE[state];
  if (tone === "brand") return "running";
  if (tone === "neutral") return "idle";
  return tone;
}

export const PROVIDER_DOT: Record<ProviderStatus, DotKind> = {
  healthy: "ok",
  degraded: "warn",
  unavailable: "err",
  ineligible: "idle",
};

export const PROVIDER_TEXT: Record<ProviderStatus, string> = {
  healthy: "text-ok",
  degraded: "text-warn",
  unavailable: "text-err",
  ineligible: "text-muted-foreground",
};

export function SectionLabel({ className, children }: { className?: string; children: React.ReactNode }) {
  return <span className={cn("label-caps", className)}>{children}</span>;
}

/** Bordered panel. Used sparingly for objects that need separation. */
export function Panel({ className, children, ...rest }: React.ComponentProps<"section">) {
  return (
    <section className={cn("rounded-lg border border-line bg-panel", className)} {...rest}>
      {children}
    </section>
  );
}

export function PanelHeader({ className, children }: { className?: string; children: React.ReactNode }) {
  return <header className={cn("flex items-center gap-2.5 border-b border-line-soft px-3.5 py-2.5", className)}>{children}</header>;
}

export function PanelFooter({ className, children }: { className?: string; children: React.ReactNode }) {
  return <footer className={cn("flex items-center gap-2.5 border-t border-line-soft px-3.5 py-2.5", className)}>{children}</footer>;
}
