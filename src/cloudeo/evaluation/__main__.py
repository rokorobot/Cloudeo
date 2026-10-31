"""CLI: python -m cloudeo.evaluation {run,digest,list}."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from cloudeo.evaluation.contracts import EvalCase
from cloudeo.evaluation.runner import run_suite, verify_store
from cloudeo.evaluation.store import TrialStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cloudeo.evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a suite and record trials")
    run.add_argument("--suite", required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--repetitions", type=int, default=1)
    run.add_argument("--label", default="baseline")
    digest = sub.add_parser("digest", help="print a case file's digest for a suite manifest")
    digest.add_argument("case_file", type=Path)
    listing = sub.add_parser("list", help="list recorded trials")
    listing.add_argument("--out", type=Path, required=True)
    verify = sub.add_parser("verify", help="regrade stored trials from retained evidence")
    verify.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "verify":
        report = verify_store(args.out)
        for trial, problems in report:
            print(f"{trial.trial_id} {trial.case_id}: {'; '.join(problems)}")
        print(f"{len(report)} trial(s) with problems")
        return 1 if report else 0
    if args.command == "digest":
        print(EvalCase.model_validate_json(args.case_file.read_text()).digest)
        return 0
    if args.command == "list":
        trials = TrialStore(args.out).trials()
    else:
        run_id, trials = asyncio.run(
            run_suite(args.suite, args.out, repetitions=args.repetitions, label=args.label)
        )
        print(f"run {run_id}: {len(trials)} trials -> {args.out}")
    for t in trials:
        reasons = [*(t.outcome_grade.reasons if t.outcome_grade else ()),
                   *(t.execution_grade.reasons if t.execution_grade else ())]  # fmt: skip
        note = t.error or "; ".join(reasons)
        print(f"{t.case_id:44} rep {t.repetition}  {t.status:11} {t.verdict:7} {note}")
    bad = [t for t in trials if t.status in ("error", "interrupted") or t.verdict == "fail"]
    return 1 if args.command == "run" and bad else 0


if __name__ == "__main__":
    sys.exit(main())
