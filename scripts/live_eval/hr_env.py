"""Write the HarnessRouter container env file from the job's secrets. Prints no values.

Usage: python scripts/live_eval/hr_env.py OUT_FILE
Reads ANTHROPIC_API_KEY, OPENAI_API_KEY and HR_AUTH_PASSWORD from the environment.
"""

import json
import os
import sys
from pathlib import Path

out = Path(sys.argv[1])
connections = {
    "ANTHROPIC": {"name": "anthropic", "provider": "anthropic",
                  "api_key": os.environ["ANTHROPIC_API_KEY"]},
    "OPENAI": {"name": "openai", "provider": "openai", "api_key": os.environ["OPENAI_API_KEY"]},
}  # fmt: skip
lines = {
    # Pinned HarnessRouter CE 0.23.7 backends, as dev/harnessrouter.compose.yaml.
    "HR_BACKENDS": "codex,claude",
    "HR_CODEX_VERSION": "0.154.0",
    "CLAUDE_CODE_VERSION": "2.1.280",
    "HR_AUTH_USER": "cloudeo",
    "HR_AUTH_PASSWORD": os.environ["HR_AUTH_PASSWORD"],
    "HR_SECRET_GLOBAL_HARNESS_CONN_ANTHROPIC": json.dumps(connections["ANTHROPIC"]),
    "HR_SECRET_GLOBAL_HARNESS_POLICY_CLAUDE": json.dumps({"chain": ["anthropic"]}),
    "HR_SECRET_GLOBAL_HARNESS_CONN_OPENAI": json.dumps(connections["OPENAI"]),
    "HR_SECRET_GLOBAL_HARNESS_POLICY_CODEX": json.dumps({"chain": ["openai"]}),
}
out.write_text("".join(f"{k}={v}\n" for k, v in lines.items()))
out.chmod(0o600)
print(f"wrote {len(lines)} variables to {out}")
