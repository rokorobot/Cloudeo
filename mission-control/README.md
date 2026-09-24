# Cloudeo Mission Control

UI foundation for Cloudeo: Next.js 16 (App Router), Tailwind v4, shadcn/ui (Radix).

**This milestone is UI-only.** Nothing here talks to the V2 control store, Browser Use, Jev, executors, auditors or model APIs. Every screen runs on typed local fixtures and a client-side simulation.

```bash
npm ci
npm run dev        # http://localhost:3000
npm run typecheck  # route typegen + tsc
npm run lint
npm test           # Vitest: simulation reducer, lifecycle navigation, owner-override guard
npm run build
```

## Screens

| Route | What it shows |
| --- | --- |
| `/` | Home: greeting, Attention, Active, Recent, runtime health |
| `/runs`, `/attention` | WorkOrder lists |
| `/work-orders/[id]` | Redirects to the WorkOrder's current stage |
| `/work-orders/[id]/[stage]` | WorkOrder view; `stage` is one of `plan execute audit memory checkpoint verify promote` |
| `/agents` `/browsers` `/evidence` `/profiles` `/usage` `/projects` | Placeholders |

Fixture WorkOrders: **WO-1842** (executing, live simulation) and **WO-1845** (`INDEPENDENCE_UNAVAILABLE`).

## Layout of the code

```
src/
  lib/types.ts            UI-facing view models (not the backend schema)
  fixtures/               All sample data: work-orders.ts, health.ts
  state/mission-control.tsx
                          The only place UI state lives: simulated run clock,
                          activity feed, pause / take control / stop,
                          palette + inspector visibility
  components/
    shell/                Top bar, nav, inspector, status bar, palette, brand mark
    work-order/           WorkOrder view, lifecycle bar, run controls, simulated browser
      stages/             One component per lifecycle stage + attention panel
    common/               Chips, dots, panels, list rows, page headers
    ui/                   shadcn primitives (generated)
```

## Wiring the backend later

Components read WorkOrders only through `useLiveWorkOrder(id)` and act through `useRunControls(id)`. To connect V2:

1. Write an adapter that maps control-store records onto the types in `src/lib/types.ts`.
2. Replace the reducer and timers in `src/state/mission-control.tsx` with a subscription that feeds those view models.
3. Keep `useRunControls` as the command seam, with each method becoming a control-store call.

Components should not import backend types directly.

## Design rules

- Dark graphite ground, warm-white text, one cyan accent (`brand`).
- `ok` (green) means verified or proven only. `warn` (amber) means attention. `err` (red) means blocked or failed.
- Geist for UI; Geist Mono for IDs, hashes, commits, evidence refs and machine state.
- Historical performance is always labelled as observed, never as a prediction.
- A checkpoint that has not passed audit is dashed and never styled as accepted.
- Owner policy override is exceptional: separated from the normal recovery actions, requires a reason and an acknowledgement, and in this build submits nothing.
