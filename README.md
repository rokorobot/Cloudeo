# Cloudeo v0.1

Local-first proof of concept for a **decision + tool-routing + verification control plane**.

Cloudeo v0.1 does one thing end-to-end:

```
Objective
  -> Jev chooses among explicitly supplied Treg tool candidates
  -> Cloudeo applies a confidence gate
  -> Treg executes the selected tool
  -> Jev verifies whether the result is sufficient
  -> PASS or retry another candidate or ESCALATE
  -> SQLite audit record
```

This is intentionally small. It does **not** yet include autonomous browser control, BB, LongHorizon,
automatic Treg catalog discovery, LLM escalation, write actions, or self-improvement.

## Why this shape

Jev is a decision model, not a chat model. It should answer narrow questions and let deterministic
software own policy. Treg is the tool plane. Cloudeo is the controller between them.

## Requirements

- Ubuntu / WSL2
- Python 3.12+
- `uv`
- Your cloned Treg repo for real Treg execution
- OpenRouter API key for real Jev execution

The project runs in **mock mode by default**, so you can validate the entire control loop before
adding credentials.

## 1. Install locally

Recommended location:

```bash
cd ~
mkdir -p cloudeo
cd cloudeo
# copy the contents of this project here
uv sync --extra dev
cp .env.example .env
```

The LongHorizon-Harness integration is optional. To install it (pinned to
upstream v0.1.7, commit `ff76d6a`), add its extra:

```bash
uv sync --extra dev --extra longhorizon
```

## 2. Run the zero-cost local smoke test

Leave these defaults in `.env`:

```env
CLOUDEO_JEV_BACKEND=mock
CLOUDEO_TREG_BACKEND=mock
```

Start:

```bash
uv run cloudeo
```

Then in another terminal:

```bash
curl -s http://127.0.0.1:18800/health | python -m json.tool

curl -s http://127.0.0.1:18800/v1/runs \
  -H 'Content-Type: application/json' \
  --data @scripts/demo.json | python -m json.tool
```

Expected result: `status: passed`, one selected mock tool, and a verification probability above the
configured threshold.

## 3. Turn on real Jev through OpenRouter

OpenRouter exposes Jev through the Decisions endpoint, not the chat-completions endpoint.

Edit `.env`:

```env
CLOUDEO_JEV_BACKEND=openrouter
OPENROUTER_API_KEY=your_key_here
CLOUDEO_JEV_MODEL=typesafe/jev-1.13
CLOUDEO_JEV_URL=https://openrouter.ai/api/alpha/decisions
```

Restart `uv run cloudeo`.

You can test Jev alone:

```bash
curl -s http://127.0.0.1:18800/v1/decide \
  -H 'Content-Type: application/json' \
  -d '{
    "state": {"ticket":"Checkout is blank after clicking Pay"},
    "questions": {
      "is_bug": {
        "type":"noul",
        "instructions":"Is the customer reporting a software defect?",
        "criteria":{"true":"Broken behavior","false":"Not broken behavior"}
      }
    }
  }' | python -m json.tool
```

## 4. Connect your local Treg clone

Point Cloudeo at the directory where you cloned `rokorobot/treg`:

```env
CLOUDEO_TREG_BACKEND=cli
CLOUDEO_TREG_REPO=/home/robert/treg
```

If your clone is on the Windows filesystem, use its WSL path instead, e.g.:

```env
CLOUDEO_TREG_REPO=/mnt/c/Users/Robert/treg
```

Cloudeo then executes catalog tools as:

```bash
uv run --project "$CLOUDEO_TREG_REPO" treg call <tool-id> --query key=value ...
```

Make sure Treg itself is logged in/configured before enabling real execution.

For a safe first test with real Jev + real Treg command construction but **without executing the
Treg call**, set `"dry_run": true` in `scripts/demo.json`.

## 5. Run tests

```bash
uv run pytest -q
```

## API

- `GET /health` — current backends and version
- `POST /v1/decide` — direct Jev primitive passthrough
- `POST /v1/runs` — Cloudeo route -> execute -> verify loop
- `GET /v1/runs` — recent local audit records
- `GET /docs` — FastAPI interactive API docs

## Routing policy

Defaults:

```env
CLOUDEO_ROUTE_CONFIDENCE=0.65
CLOUDEO_VERIFY_PROBABILITY=0.85
CLOUDEO_MAX_ATTEMPTS=2
```

These are prototype values, **not production safety thresholds**. Real thresholds must be calibrated
on labeled examples for each workflow.

## Current trust boundary

v0.1 supports read/search/enrichment-style tool calls. Do not use this prototype for irreversible
or consequential actions. Human approval and explicit action policies belong in a later stage.

## v0.2 candidates

1. Automatic Treg catalog discovery from an objective instead of requiring candidate IDs.
2. LLM escalation adapter when Jev routing/verification is uncertain.
3. Browser Use worker adapter.
4. Policy engine for read/write/high-risk actions.
5. Run/evidence timeline UI.
6. Evaluation set + threshold calibration tooling.
