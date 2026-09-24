import { Greeting } from "@/components/home/greeting";
import { Dot, PROVIDER_DOT, SectionLabel } from "@/components/common/status";
import { WorkOrderRow } from "@/components/common/work-order-row";
import { HEALTH } from "@/fixtures/health";
import { ACTIVE, ATTENTION, RECENT } from "@/fixtures/work-orders";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1">
      <SectionLabel className="mb-1 border-b border-line-soft px-3 pb-2">{title}</SectionLabel>
      {children}
    </section>
  );
}

export default function HomePage() {
  const needsLook = HEALTH.runtimes.filter((r) => r.status === "degraded" || r.status === "unavailable");
  return (
    <div className="mx-auto flex max-w-[780px] flex-col gap-8 px-6 pt-14 pb-10 max-md:px-4 max-md:pt-8">
      <div>
        <Greeting />
        <div className="flex flex-col gap-1 text-[15px] text-subtle">
          <span><b className="font-medium text-foreground tnum">{ACTIVE.length}</b> autonomous WorkOrders running</span>
          <span><b className="font-medium text-warn tnum">{ATTENTION.length}</b> requires your attention</span>
          <span><b className="font-medium text-foreground tnum">{HEALTH.verifiedToday}</b> completed and verified since yesterday</span>
        </div>
      </div>

      <Section title="Attention">
        {ATTENTION.map((w) => <WorkOrderRow key={w.id} summary={w} variant="attention" />)}
      </Section>
      <Section title="Active">
        {ACTIVE.map((w) => <WorkOrderRow key={w.id} summary={w} variant="active" />)}
      </Section>
      <Section title="Recent">
        {RECENT.map((w) => <WorkOrderRow key={w.id} summary={w} variant="recent" />)}
      </Section>

      <Section title="Runtimes">
        <div className="flex flex-wrap gap-x-5 gap-y-2 px-3 py-1.5 text-[12.5px] text-subtle">
          {HEALTH.runtimes.map((r) => (
            <span key={r.name} className="flex items-center gap-2">
              <Dot kind={PROVIDER_DOT[r.status]} />
              {r.name}
            </span>
          ))}
        </div>
        {needsLook.length > 0 && (
          <p className="px-3 text-[12.5px] text-muted-foreground">
            {needsLook.map((r) => `${r.name}: ${r.detail}`).join(" · ")}
          </p>
        )}
      </Section>
    </div>
  );
}
