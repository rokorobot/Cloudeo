"""Before any spend: check that HarnessRouter offers each configured executor model.

Usage: python scripts/live_eval/preflight.py CONFIG.json [CONFIG.json ...]
Reads CLOUDEO_EVAL_UHP_URL and CLOUDEO_EVAL_UHP_COOKIE. Prints model ids only.
Exit 1 if a configured model is not offered by its built-in harness.
"""

import json
import os
import sys

import httpx

base = os.environ["CLOUDEO_EVAL_UHP_URL"].rstrip("/")
r = httpx.get(
    f"{base}/v1/models", headers={"Cookie": os.environ["CLOUDEO_EVAL_UHP_COOKIE"]}, timeout=60
)
r.raise_for_status()
backends = r.json()["backends"]
missing = []
for path in sys.argv[1:]:
    with open(path) as f:
        variables = json.load(f)["variables"]
    harness, model = variables["executor_harness"], variables["executor_model"]
    offered = sorted(m["id"] for m in backends.get(harness, {}).get("models", []) if m["available"])
    print(f"{harness}: {model} {'offered' if model in offered else 'NOT offered'}")
    if model not in offered:
        missing.append(f"{harness}/{model} (offered: {', '.join(offered)})")
for item in missing:
    print(f"error: {item}")
sys.exit(1 if missing else 0)
