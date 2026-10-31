"""Write the environment manifest that identifies a CI test run.

Usage: python scripts/ci_env_manifest.py JOB OUTPUT.json

Records the commit, dirty-tree state, interpreter, lockfile digest and the
installed distributions, so a test artifact names exactly what it tested.
"""

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    job, output = sys.argv[1], Path(sys.argv[2])
    dirty = git("status", "--porcelain", "--untracked-files=no")
    packages = {}
    for dist in metadata.distributions():
        entry = {"version": dist.version}
        direct_url = dist.read_text("direct_url.json")
        if direct_url:
            entry["direct_url"] = json.loads(direct_url)
        packages[dist.metadata["Name"]] = entry
    manifest = {
        "job": job,
        "created_at": datetime.now(UTC).isoformat(),
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(dirty),
        "dirty_paths": dirty.splitlines(),
        "python": sys.version,
        "platform": platform.platform(),
        "uv_lock_sha256": sha256(ROOT / "uv.lock"),
        "pyproject_sha256": sha256(ROOT / "pyproject.toml"),
        "packages": dict(sorted(packages.items())),
    }
    output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{job}: commit={manifest['commit']} dirty={manifest['dirty']} "
          f"packages={len(packages)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
