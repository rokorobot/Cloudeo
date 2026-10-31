"""Before any spend: check that HarnessRouter offers each configured executor model.

Usage: python scripts/live_eval/preflight.py CONFIG.json [CONFIG.json ...]
Reads CLOUDEO_EVAL_UHP_URL and CLOUDEO_EVAL_UHP_COOKIE. Prints model ids only.
Exit 1 if a configured model is not offered by its harness.
"""

import json
import os
import sys

import httpx

base = os.environ["CLOUDEO_EVAL_UHP_URL"].rstrip("/")
headers = {"Cookie": os.environ["CLOUDEO_EVAL_UHP_COOKIE"]}
missing = []
for path in sys.argv[1:]:
    with open(path) as f:
        variables = json.load(f)["variables"]
    harness, model = variables["executor_harness"], variables["executor_model"]
    r = httpx.get(f"{base}/v1/harnesses/{harness}/models", headers=headers, timeout=60)
    if r.status_code != 200:
        print(f"{harness}: HTTP {r.status_code} listing models")
        missing.append((harness, model))
        continue
    body = r.json()
    offered = sorted(m["id"] for m in body.get("models", []) if m.get("available", True))
    print(f"{harness}: offers {offered}")
    if model not in offered:
        missing.append((harness, model))
for harness, model in missing:
    print(f"::error::{harness} does not offer the configured model {model!r}")
sys.exit(1 if missing else 0)
