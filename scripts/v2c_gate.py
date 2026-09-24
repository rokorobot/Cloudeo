"""V2 control gate: whole-suite health plus an exact control-suite manifest.

The gate runs the full pytest suite once and fails unless:

- pytest exits successfully, with no failures, errors, or unexpected passes;
- the V2 control suite's node IDs and outcomes equal
  `scripts/v2c_control_manifest.tsv` exactly;
- every expected xfail in the control suite is declared `strict=True`.

It deliberately does not check the whole suite's pass count: unrelated tests
may be added without turning a healthy build red.

Usage, from the repository root:

    .venv/bin/python scripts/v2c_gate.py
    .venv/bin/python scripts/v2c_gate.py --write-manifest

`--write-manifest` rewrites the manifest from a healthy run. Review its diff:
a manifest change is a change to the V2C evidence.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "scripts" / "v2c_control_manifest.tsv"
CONTROL_FILES = (
    "tests/test_control_machine.py",
    "tests/test_control_store.py",
    "tests/test_v2c_traceability.py",
)
HEADER = (
    "# V2 control-suite manifest: <outcome>\\t<pytest node ID>, sorted by node ID.\n"
    "# Outcomes: pass, xfail (strict). Checked by scripts/v2c_gate.py;\n"
    "# regenerate with --write-manifest and review the diff.\n"
)


class Recorder:
    """Records each test's outcome and whether its xfail marker is strict."""

    def __init__(self) -> None:
        self.collected: list[str] = []
        self.strict_xfail: dict[str, bool] = {}
        self.outcomes: dict[str, str] = {}

    def pytest_collection_modifyitems(self, config, items) -> None:
        default_strict = config.getini("xfail_strict")
        for item in items:
            self.collected.append(item.nodeid)
            marker = item.get_closest_marker("xfail")
            if marker is not None:
                self.strict_xfail[item.nodeid] = bool(
                    marker.kwargs.get("strict", default_strict)
                )

    def pytest_runtest_logreport(self, report) -> None:
        node = report.nodeid
        if report.failed:
            if report.when == "call":
                self.outcomes[node] = "fail"
            elif self.outcomes.get(node) != "fail":
                self.outcomes[node] = "error"
            return
        if report.when == "call" or (report.when == "setup" and report.skipped):
            if hasattr(report, "wasxfail"):
                self.outcomes[node] = "xfail" if report.skipped else "xpass"
            else:
                self.outcomes[node] = "skip" if report.skipped else "pass"


def read_manifest() -> dict[str, str]:
    expected: dict[str, str] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        outcome, node = line.split("\t", 1)
        expected[node] = outcome
    return expected


def write_manifest(control: dict[str, str]) -> None:
    body = "".join(f"{control[node]}\t{node}\n" for node in sorted(control))
    MANIFEST.write_text(HEADER + body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()

    os.chdir(ROOT)
    recorder = Recorder()
    exit_code = pytest.main(["-q", "-p", "no:cacheprovider"], plugins=[recorder])

    counts: dict[str, int] = {}
    for outcome in recorder.outcomes.values():
        counts[outcome] = counts.get(outcome, 0) + 1
    print("\n== V2 control gate ==")
    print(f"collected: {len(recorder.collected)}")
    for outcome in ("pass", "xfail", "skip", "xpass", "fail", "error"):
        print(f"{outcome}: {counts.get(outcome, 0)}")

    problems: list[str] = []
    if exit_code != 0:
        problems.append(f"pytest exited with {int(exit_code)}")
    for outcome in ("fail", "error", "xpass"):
        if counts.get(outcome):
            problems.append(f"{counts[outcome]} test(s) with outcome {outcome}")
    unreported = [n for n in recorder.collected if n not in recorder.outcomes]
    if unreported:
        problems.append(f"{len(unreported)} collected test(s) have no outcome")

    control = {
        node: outcome
        for node, outcome in recorder.outcomes.items()
        if node.split("::", 1)[0] in CONTROL_FILES
    }
    loose = sorted(
        n for n, outcome in control.items()
        if outcome == "xfail" and not recorder.strict_xfail.get(n, False)
    )
    for node in loose:
        problems.append(f"control xfail is not strict: {node}")

    if args.write_manifest:
        if problems:
            print("\nNot writing the manifest from an unhealthy run:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        write_manifest(control)
        print(f"\nWrote {len(control)} control node IDs to {MANIFEST.relative_to(ROOT)}.")
        return 0

    expected = read_manifest()
    added = sorted(set(control) - set(expected))
    removed = sorted(set(expected) - set(control))
    changed = sorted(
        n for n in set(control) & set(expected) if control[n] != expected[n]
    )
    control_counts = {o: list(control.values()).count(o) for o in ("pass", "xfail")}
    print(
        f"control suite: {len(control)} node IDs "
        f"({control_counts['pass']} pass, {control_counts['xfail']} strict xfail); "
        f"manifest: {len(expected)}"
    )
    if added or removed or changed:
        problems.append("control suite differs from the manifest")
        for node in added:
            print(f"  + {control[node]}\t{node}")
        for node in removed:
            print(f"  - {expected[node]}\t{node}")
        for node in changed:
            print(f"  ~ {expected[node]} -> {control[node]}\t{node}")

    if problems:
        print("\nGATE FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
