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
| `control` | Real V2 WorkOrders from the Cloudeo API, updated in real time | Only the owner commands of ADR-038, and only with an owner token (see below). Pause, stop and take control are not in the V2 control model |

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

To watch it update live without a real executor, drive a throwaway store with the dev script (one control event every `--step` seconds):

```bash
uv run python dev/mission_control_live_demo.py /tmp/mc-demo.db --step 3   # then point CLOUDEO_CONTROL_DB_PATH at it
```

### Owner commands (ADR-038)

With an owner configured, control mode can approve or reject a proposed plan (PLAN stage) and decide on an open attention request:
`resume`, `replan`, `defer`, `abort`. Nothing else can be written.

```bash
TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
# API: who the owner is, and the token it accepts
CLOUDEO_MISSION_CONTROL_OWNER=robert CLOUDEO_MISSION_CONTROL_OWNER_TOKEN=$TOKEN CLOUDEO_CONTROL_DB_PATH=... uv run uvicorn cloudeo.api.app:app --port 18800
# UI server: the same token (server-side only; never sent to the browser)
CLOUDEO_MISSION_CONTROL_OWNER_TOKEN=$TOKEN MISSION_CONTROL_SOURCE=control npm run dev
```

- Which commands apply, and why one is disabled, comes from the adapter (`commands` on the detail view). `resume` back into execution is
  disabled until the API is bound to a Workspace Broker; `change_agent` / `change_budget` need envelope amendments the UI cannot author yet.
- Every command is confirmed and names the record version shown when the dialog opened. If the WorkOrder changed meanwhile, the API
  refuses it (409 `stale_version`) and nothing is recorded.
- The actor is configured on the API, never sent by the browser. `/api/control/work-orders/[id]/commands` accepts only same-origin JSON
  from this app and adds the token; the API refuses any request with an `Origin` header, so no web page can reach it directly.
- Without the token the buttons render disabled with the reason, and the top bar says `CONTROL STORE · READ-ONLY`.

### Real time

Changes are pushed, not polled. `GET /v1/mission-control/stream` is Server-Sent Events over the control store's append-only
`work_order_events` table (`src/cloudeo/mission_control/stream.py`):

- Each event carries only `{cursor, workOrderId, version, event}`. The UI re-reads that WorkOrder (if on screen) and the list through the
  normal GET endpoints, so the adapter stays the one place that maps domain records, and the stream cannot show anything the store does not hold.
- The cursor is the event row's SQLite `rowid` (the table is append-only, so it only grows). It is the SSE `id:`, so a reconnecting
  EventSource sends `Last-Event-ID` and gets exactly the events it missed. No schema change.
- A fresh subscription (or a cursor ahead of the store, e.g. a replaced store) gets `ready`, and the UI re-reads everything.
- If the store cannot be read, the stream sends `unavailable` and ends. The UI falls back to re-reading every 5 s and reconnects.
- The status bar shows the link: `Control store · live`, `connecting`, or `reconnecting`.
- SQLite has no change notification, so the API checks the table every 0.5 s (a rowid range scan on a read-only connection).

In control mode the UI shows only what the control store holds. Live browser frames, tool events, cost, elapsed time, runtime health,
routing decisions and performance memory are **not** in the V2 control store yet; those surfaces say so explicitly instead of
falling back to simulated values.

## Data boundary

```
screens ──▶ src/data/context.tsx (hooks)
              ├── FixtureWorkOrderProvider   demo: fixtures + simulation + commands
              └── V2WorkOrderProvider        control: WorkOrderQuerySource only, refreshed by the event stream
                     ├── HttpWorkOrderQuerySource ─▶ /api/control ─▶ cloudeo.mission_control (Python adapter) ─▶ cloudeo.control
                     └── EventSource ─▶ /api/control/stream ─▶ /v1/mission-control/stream ─▶ work_order_events
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
