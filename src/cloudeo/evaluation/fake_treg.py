"""Offline fake of the `treg` command line, for EVAL-01 deterministic scenarios.

Cloudeo's real TregCLIClient runs it as a subprocess in place of `treg`, so
Cloudeo's own query building, catalog matching, input binding and call
construction all run; only Treg and the providers behind it are faked.

Usage: python -I fake_treg.py CATALOG.json LOG.jsonl <treg arguments...>

CATALOG.json:
  {"search": {"<exact query>": {"results": [...], "count": n, "total": n}},
   "endpoints": {"<endpoint id>": {<catalog get detail>}},
   "outputs": {"<endpoint id>": <provider JSON or text>}}

Every invocation is appended to LOG.jsonl. Standard library only.
"""

import json
import sys


def main(argv: list[str]) -> int:
    catalog_path, log_path, args = argv[0], argv[1], argv[2:]
    with open(catalog_path) as f:
        catalog = json.load(f)
    with open(log_path, "a") as f:
        f.write(json.dumps(args) + "\n")

    if args[:3] == ["--json", "catalog", "search"]:
        empty = {"results": [], "count": 0, "total": 0}
        print(json.dumps(catalog.get("search", {}).get(args[3], empty)))
        return 0
    if args[:3] == ["--json", "catalog", "get"]:
        detail = catalog.get("endpoints", {}).get(args[3])
        if detail is None:
            print(f"treg: unknown endpoint {args[3]}", file=sys.stderr)
            return 1
        print(json.dumps(detail))
        return 0
    if args[:2] == ["--json", "balance"]:
        print("treg: no ledger in the offline fake", file=sys.stderr)
        return 2
    if args[:1] == ["call"]:
        output = catalog.get("outputs", {}).get(args[1])
        if output is None:
            print(f"treg: provider for {args[1]} failed", file=sys.stderr)
            return 1
        print(output if isinstance(output, str) else json.dumps(output, sort_keys=True))
        print("treg: charged $0.005 call id call_eval_1", file=sys.stderr)
        return 0
    print(f"treg: unsupported arguments {args}", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
