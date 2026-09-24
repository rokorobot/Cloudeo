export function PageHeader({ title, lead }: { title: string; lead?: string }) {
  return (
    <header className="flex flex-col gap-1.5">
      <h1 className="text-[22px] font-medium tracking-[-0.015em] text-balance">{title}</h1>
      {lead && <p className="max-w-[62ch] text-subtle">{lead}</p>}
    </header>
  );
}

export function PageBody({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto flex max-w-[980px] flex-col gap-6 px-6 pt-8 pb-10 max-md:px-4">{children}</div>;
}
