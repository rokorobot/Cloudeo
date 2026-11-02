"use client";

import { Greeting } from "@/components/home/greeting";
import { ResultState } from "@/components/common/result-state";
import { Dot, PROVIDER_DOT, SectionLabel } from "@/components/common/status";
import { UnsupportedRow, WorkOrderRow } from "@/components/common/work-order-row";
import { useDataSource, useHealth, useWorkOrderList } from "@/data/context";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-1">
      <SectionLabel className="mb-1 border-b border-line-soft px-3 pb-2">{title}</SectionLabel>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="px-3 py-2 text-[12.5px] text-muted-foreground">{children}</p>;
}

export function HomeView() {
  const list = useWorkOrderList();
  const health = useHealth();
  const source = useDataSource();

  if (list.status !== "ready") {
    return (
      <div className="mx-auto flex max-w-[780px] flex-col gap-8 px-6 pt-14 pb-10 max-md:px-4 max-md:pt-8">
        <Greeting />
        <ResultState result={list} what="WorkOrders" />
      </div>
    );
  }
  const { active, attention, recent, unsupported } = list.data;
  const promoted = recent.filter((w) => w.state === "promoted" || w.state === "verified").length;
  const needsLook = health?.runtimes.filter((r) => r.status === "degraded" || r.status === "unavailable") ?? [];

  return (
    <div className="mx-auto flex max-w-[780px] flex-col gap-8 px-6 pt-14 pb-10 max-md:px-4 max-md:pt-8">
      <div>
        <Greeting />
        <div className="flex flex-col gap-1 text-[15px] text-subtle">
          <span>
            <b className="font-medium text-foreground tnum">{active.length}</b>{" "}
            {source === "fixture" ? "autonomous WorkOrders running" : "WorkOrders in progress"}
          </span>
          <span><b className="font-medium text-warn tnum">{attention.length}</b> {attention.length === 1 ? "requires" : "require"} your attention</span>
          <span>
            <b className="font-medium text-foreground tnum">{health ? health.verifiedToday : promoted}</b>{" "}
            {health ? "completed and verified since yesterday" : "promoted after verification"}
          </span>
          {unsupported.length > 0 && (
            <span><b className="font-medium text-err tnum">{unsupported.length}</b> stored WorkOrders cannot be presented</span>
          )}
        </div>
      </div>

      {unsupported.length > 0 && (
        <Section title="Unsupported">
          {unsupported.map((u) => <UnsupportedRow key={u.id} item={u} />)}
        </Section>
      )}
      <Section title="Attention">
        {attention.length ? attention.map((w) => <WorkOrderRow key={w.id} summary={w} variant="attention" />) : <Empty>Nothing needs you.</Empty>}
      </Section>
      <Section title="Active">
        {active.length ? active.map((w) => <WorkOrderRow key={w.id} summary={w} variant="active" />) : <Empty>No WorkOrders in progress.</Empty>}
      </Section>
      <Section title="Recent">
        {recent.length ? recent.map((w) => <WorkOrderRow key={w.id} summary={w} variant="recent" />) : <Empty>No finished WorkOrders yet.</Empty>}
      </Section>

      <Section title="Runtimes">
        {health ? (
          <>
            <div className="flex flex-wrap gap-x-5 gap-y-2 px-3 py-1.5 text-[12.5px] text-subtle">
              {health.runtimes.map((r) => (
                <span key={r.name} className="flex items-center gap-2">
                  <Dot kind={PROVIDER_DOT[r.status]} />
                  {r.name}
                </span>
              ))}
            </div>
            {needsLook.length > 0 && (
              <p className="px-3 text-[12.5px] text-muted-foreground">{needsLook.map((r) => `${r.name}: ${r.detail}`).join(" · ")}</p>
            )}
          </>
        ) : (
          <Empty>Runtime health is not reported by the V2 control store.</Empty>
        )}
      </Section>
    </div>
  );
}
