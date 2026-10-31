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
    compare = sub.add_parser("compare", help="paired comparison of two configurations")
    compare.add_argument("--suite", required=True)
    compare.add_argument("--baseline", type=Path, required=True, help="configuration JSON")
    compare.add_argument("--candidate", type=Path, required=True, help="configuration JSON")
    compare.add_argument("--out", type=Path, required=True)
    compare.add_argument("--repetitions", type=int, default=5)
    compare.add_argument("--seed", type=int, default=20261031)
    # Owner-approved caps (2026-10-31): USD 7 per run, USD 20 per rolling week.
    compare.add_argument("--run-cap-usd", type=float, default=7.0)
    compare.add_argument("--week-cap-usd", type=float, default=20.0)
    compare.add_argument("--ledger", type=Path, help="spend ledger (default OUT/ledger.jsonl)")
    compare.add_argument("--require-clean", action="store_true", help="refuse a dirty tree")
    compare.add_argument(
        "--estimate-only", action="store_true", help="check the budget, run nothing"
    )
    args = parser.parse_args(argv)

    if args.command == "compare":
        return _compare(args)

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
        run_id, trials, holdout = asyncio.run(
            run_suite(args.suite, args.out, repetitions=args.repetitions, label=args.label)
        )
        print(f"run {run_id}: {len(trials)} trials -> {args.out}")
        if holdout["cases"]:
            # Aggregate counts only; holdout trials stay in holdout storage.
            print("holdout: " + ", ".join(f"{k} {v}" for k, v in holdout.items()))
    for t in trials:
        reasons = [*(t.outcome_grade.reasons if t.outcome_grade else ()),
                   *(t.execution_grade.reasons if t.execution_grade else ())]  # fmt: skip
        note = t.error or "; ".join(reasons)
        print(f"{t.case_id:44} rep {t.repetition}  {t.status:11} {t.verdict:7} {note}")
    for partition in ("regression", "capability"):
        group = [t for t in trials if t.provenance.partition == partition]
        if group:
            counts = {v: sum(t.verdict == v for t in group) for v in ("pass", "fail", "unknown")}
            print(f"{partition}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    # Capability cases measure open gaps; only regression results gate the exit code.
    bad = [
        t for t in trials
        if t.status in ("error", "interrupted")
        or (t.verdict == "fail" and t.provenance.partition != "capability")
    ]  # fmt: skip
    return 1 if args.command == "run" and bad else 0


def _compare(args) -> int:
    from datetime import UTC, datetime

    from cloudeo.evaluation.compare import (
        BudgetExceeded,
        DirtyCodeRefused,
        Ledger,
        estimate,
        plan,
        run_comparison,
    )
    from cloudeo.evaluation.contracts import EvalConfiguration
    from cloudeo.evaluation.runner import holdout_dir, load_suite

    baseline = EvalConfiguration.model_validate_json(args.baseline.read_text())
    candidate = EvalConfiguration.model_validate_json(args.candidate.read_text())
    ledger = Ledger(args.ledger or args.out / "ledger.jsonl")
    _, cases = load_suite(args.suite, holdout=holdout_dir())
    cases = [c for c in cases if c.partition != "holdout"]
    planned = estimate(plan(cases, args.repetitions, (baseline, candidate), args.seed))
    week = ledger.spent_this_week(datetime.now(UTC))
    print(f"plan: {len(cases)} cases x {args.repetitions} reps x 2 configs; reserve "
          f"${planned:.2f} (run cap ${args.run_cap_usd:.2f}; week ${week:.2f} spent of "
          f"${args.week_cap_usd:.2f})")  # fmt: skip
    if args.estimate_only:
        fits = planned <= args.run_cap_usd and planned <= args.week_cap_usd - week
        print("fits the budget" if fits else "DOES NOT fit the budget")
        return 0 if fits else 2
    try:
        comparison = asyncio.run(
            run_comparison(
                args.suite, baseline, candidate, args.out, repetitions=args.repetitions,
                run_cap_usd=args.run_cap_usd, week_cap_usd=args.week_cap_usd, ledger=ledger,
                seed=args.seed, require_clean=args.require_clean,
            )
        )  # fmt: skip
    except (BudgetExceeded, DirtyCodeRefused) as exc:
        print(f"refused: {exc}")
        return 2
    print((args.out / f"comparison-{comparison.run_id}.md").read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
