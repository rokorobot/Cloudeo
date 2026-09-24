# Cloudeo Mission Control

Mission Control UI for Cloudeo: Next.js 16 (App Router), Tailwind v4, shadcn/ui (Radix).

```bash
npm ci
npm run dev        # http://localhost:3000 (demo mode)
npm run typecheck  # route typegen + tsc
npm run lint
npm test           # Vitest
npm run build
```

## Two modes, same screens

| `MISSION_CONTROL_SOURCE` | Source | Can change anything? |
| --- | --- | --- |
| `demo` (default) | Local fixtures plus a client-side simulation | Yes, simulated: pause, take control, stop, owner override dialog |
| `control` | Real V2 WorkOrders from the Cloudeo read API | **No.** Read-only; every command renders disabled with "Control actions not connected yet" |

Any other value is a startup error. The mode is read per request, so one build serves either mode.

### Running control mode

```bash
# Cloudeo read API (repo root), pointing at an existing V2 control store
CLOUDEO_CONTROL_DB_PATH=/path/to/control.db uv run uvicorn cloudeo.api.app:app --port 18800

# UI
MISSION_CONTROL_SOURCE=control CLOUDEO_API_URL=http://127.0.0.1:18800 npm run dev
```

The browser only talks to `/api/control/*` in this app, which forwards GET requests to
`/v1/mission-control/*`. Both layers expose GET only. The API opens the SQLite store with `mode=ro`, so a write fails at the database.

In control mode the UI shows only what the control store holds. Live browser frames, tool events, cost, elapsed time, runtime health,
routing decisions and performance memory are **not** in the V2 control store yet; those surfaces say so explicitly instead of
falling back to simulated values.

## Data boundary

```
screens ──▶ src/data/context.tsx (hooks)
              ├── FixtureWorkOrderProvider   demo: fixtures + simulation + commands
              └── V2WorkOrderProvider        control: WorkOrderQuerySource only
                     └── HttpWorkOrderQuerySource ─▶ /api/control ─▶ cloudeo.mission_control (Python adapter) ─▶ cloudeo.control
```

- Screens read through `useWorkOrderResult` / `useLiveWorkOrder` / `useWorkOrderList` and act through `useRunCommands`, which is `null` in control mode.
- `WorkOrderQuerySource` and `WorkOrderCommandSource` are separate interfaces (`src/data/sources.ts`). Control mode implements only the query side.
- **Fail closed.** The Python adapter maps every domain enum through an exhaustive table and refuses unknown values. The UI also checks every
  enum it receives (`src/data/control-source.ts`). An unknown state becomes an explicit "unsupported" error or list row, never a default.

### Contract fixture

`src/data/__fixtures__/control-contract.json` is the exact adapter output for real stored WorkOrders. `tests/test_mission_control_contract.py`
fails if the adapter's output drifts from it, and the UI tests render it. After an intentional adapter change:

```bash
UPDATE_UI_CONTRACT=1 uv run pytest tests/test_mission_control_contract.py
```

## Screens

| Route | What it shows |
| --- | --- |
| `/` | Home: Attention, Active, Recent, runtime health (demo) |
| `/runs`, `/attention` | WorkOrder lists; unsupported records are listed, not hidden |
| `/work-orders/[id]` | Redirects to the WorkOrder's current stage |
| `/work-orders/[id]/[stage]` | WorkOrder view; `stage` is one of `plan execute audit memory checkpoint verify promote` |
| `/agents` `/browsers` `/evidence` `/profiles` `/usage` `/projects` | Placeholders |

Demo WorkOrders: **WO-1842** (executing, live simulation) and **WO-1845** (`INDEPENDENCE_UNAVAILABLE`).

In control mode the MEMORY stage shows V2 memory curation (per block, approved by a Memory Audit). The demo's performance-memory table has
no V2 source yet.

## Layout of the code

```
src/
  lib/types.ts        UI-facing view models (optional where the control store may not hold a value)
  data/               Providers, hooks, query/command interfaces, HTTP source, mode selection
  fixtures/           Demo data (imported only by the fixture provider)
  state/ui.tsx        Shell UI state: palette, inspector
  app/api/control/    GET-only proxy to the Cloudeo read API
  components/
    shell/            Top bar, nav, inspector, status bar, palette, brand mark
    work-order/       WorkOrder view, lifecycle bar, run controls, simulated browser
      stages/         One component per lifecycle stage + attention panel
    common/           Chips, dots, panels, list rows, result states
    ui/               shadcn primitives (generated)
```

## Design rules

- Dark graphite ground, warm-white text, one cyan accent (`brand`).
- `ok` (green) means verified or proven only. `warn` (amber) means attention. `err` (red) means blocked or failed.
- Geist for UI; Geist Mono for IDs, hashes, commits, evidence refs and machine state.
- Historical performance is always labelled as observed, never as a prediction.
- A checkpoint that has not passed its proof is dashed and never styled as accepted.
- Owner policy override is exceptional, and exists only in demo mode; in this build it submits nothing.
