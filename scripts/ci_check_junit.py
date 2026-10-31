"""Check a pytest JUnit report against the expected-skip inventory for one CI job.

Usage: python scripts/ci_check_junit.py JOB REPORT.xml [SUMMARY.json]

Fails when any test failed or errored, when the skipped set differs from
tests/expected_skips.json[JOB], or when no tests ran. Strict xfails are
configured in pyproject.toml, so an unexpected pass is already a failure.
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

INVENTORY = Path(__file__).resolve().parent.parent / "tests" / "expected_skips.json"


def main() -> int:
    job, report = sys.argv[1], sys.argv[2]
    expected = set(json.loads(INVENTORY.read_text())[job])

    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "xfailed": 0}
    skipped: set[str] = set()
    for case in ET.parse(report).iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        skip = case.find("skipped")
        if case.find("failure") is not None:
            counts["failed"] += 1
        elif case.find("error") is not None:
            counts["error"] += 1
        elif skip is not None and skip.get("type") == "pytest.xfail":
            counts["xfailed"] += 1
        elif skip is not None:
            counts["skipped"] += 1
            skipped.add(test_id)
        else:
            counts["passed"] += 1

    unexpected = sorted(skipped - expected)
    missing = sorted(expected - skipped)
    summary = {"job": job, "counts": counts, "skipped": sorted(skipped),
               "unexpected_skips": unexpected, "stale_inventory": missing}
    print(json.dumps(summary, indent=2))
    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_text(json.dumps(summary, indent=2) + "\n")

    problems = []
    if counts["failed"] or counts["error"]:
        problems.append("tests failed or errored")
    if not counts["passed"]:
        problems.append("no tests passed")
    if unexpected:
        problems.append(f"unexpected skips: {unexpected}")
    if missing:
        problems.append(f"expected skips did not occur (update the inventory): {missing}")
    for problem in problems:
        print(f"::error::{job}: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
