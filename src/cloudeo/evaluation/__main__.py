"""CLI: python -m cloudeo.evaluation {run,gate,digest,list,verify,compare}."""

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
    gate = sub.add_parser("gate", help="run a suite once; exit 0 pass, 1 fail, 2 blocked")
    gate.add_argument("--suite", required=True)
    gate.add_argument("--out", type=Path, required=True)
    release = sub.add_parser(
        "release-gate", help="may a judged comparison's candidate replace the current baseline?"
    )
    release.add_argument("--comparison", type=Path, required=True, help="comparison-*.json")
    release.add_argument("--gate-report", type=Path, required=True, help="regression gate-*.json")
    holdout = release.add_mutually_exclusive_group(required=True)
    holdout.add_argument("--holdout-report", type=Path, help="gate-*.json run with holdout storage")
    holdout.add_argument("--no-holdout-reason", help="owner-recorded reason there is no holdout")
    release.add_argument("--thresholds", type=Path, help="default: gates/thresholds-v1.json")
    release.add_argument(
        "--candidate-file", required=True, help="candidate configuration, relative to the package"
    )
    release.add_argument("--out", type=Path, required=True)
    release.add_argument("--approved-by", default="owner")
    release.add_argument(
        "--apply", action="store_true", help="on pass, write the new record and move the pointer"
    )
    compare = sub.add_parser("compare", help="paired comparison of two configurations")
    compare.add_argument("--suite", required=True)
    compare.add_argument("--baseline", type=Path, required=True, help="configuration JSON")
    compare.add_argument("--candidate", type=Path, required=True, help="configuration JSON")
    compare.add_argument("--out", type=Path, required=True)
    compare.add_argument("--repetitions", type=int, default=5)
    compare.add_argument("--seed", type=int, default=20261031)
    # Owner-approved caps: USD 7 per run and USD 20 per rolling week by default
    # (2026-10-31); a thresholds file carries its own release caps (2026-11-02).
    compare.add_argument("--run-cap-usd", type=float)
    compare.add_argument("--week-cap-usd", type=float)
    compare.add_argument(
        "--thresholds", type=Path,
        help="frozen thresholds JSON (e.g. gates/thresholds-v1.json); requires a clean tree",
    )  # fmt: skip
    compare.add_argument("--ledger", type=Path, help="spend ledger (default OUT/ledger.jsonl)")
    compare.add_argument("--require-clean", action="store_true", help="refuse a dirty tree")
    compare.add_argument(
        "--estimate-only", action="store_true", help="check the budget, run nothing"
    )
    args = parser.parse_args(argv)

    if args.command == "compare":
        return _compare(args)
    if args.command == "gate":
        return _gate(args)
    if args.command == "release-gate":
        return _release(args)

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


def _gate(args) -> int:
    from cloudeo.evaluation.gate import build_report, write_report
    from cloudeo.evaluation.runner import holdout_dir, load_suite

    suite, cases = load_suite(args.suite, holdout=holdout_dir())
    run_id, trials, holdout = asyncio.run(run_suite(args.suite, args.out))
    report = build_report(run_id, suite, cases, trials, holdout)
    _, md_path = write_report(args.out, report)
    print(md_path.read_text())
    return report["exit_code"]


def _release(args) -> int:
    import json

    from cloudeo.evaluation import release
    from cloudeo.evaluation.compare import THRESHOLDS, load_thresholds
    from cloudeo.evaluation.contracts import EvalComparison, EvalConfiguration
    from cloudeo.evaluation.runner import DATA

    comparison = EvalComparison.model_validate_json(args.comparison.read_text())
    thresholds = load_thresholds(args.thresholds or THRESHOLDS / "thresholds-v1.json")
    gate_report = json.loads(args.gate_report.read_text())
    holdout = json.loads(args.holdout_report.read_text()) if args.holdout_report else None
    baseline = release.current()
    verdict, failed, blocked = release.decide(
        comparison, thresholds, gate_report, holdout, args.no_holdout_reason, baseline
    )
    candidate = DATA / args.candidate_file
    if not candidate.is_file() or (
        EvalConfiguration.model_validate_json(candidate.read_text()).digest
        != comparison.candidate.digest
    ):
        blocked.append(f"{args.candidate_file} is not the compared candidate configuration")
        verdict = "fail" if failed else "blocked"
    decision = {
        "verdict": verdict, "exit_code": release.EXIT_CODES[verdict], "fail_reasons": failed,
        "blocked_reasons": blocked, "comparison_id": comparison.comparison_id,
        "current_baseline": baseline.id, "candidate": comparison.candidate.id,
        "thresholds_digest": thresholds.digest, "proposed_record": None,
    }  # fmt: skip
    if verdict == "pass":
        record = release.next_record(
            comparison, thresholds, holdout, args.no_holdout_reason, baseline,
            args.approved_by, args.candidate_file,
        )  # fmt: skip
        decision["proposed_record"] = record.model_dump(mode="json")
        if args.apply:
            release.apply(record)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"release-{comparison.comparison_id}.json"
    path.write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n")
    print(f"release gate: {verdict.upper()} ({comparison.candidate.id} vs current {baseline.id})")
    for reason in failed + blocked:
        print(f"- {reason}")
    if verdict == "pass":
        print(f"proposed {decision['proposed_record']['id']}"
              + (": written; open a PR to promote" if args.apply else "; rerun with --apply"))  # fmt: skip
    return decision["exit_code"]


def _compare(args) -> int:
    from datetime import UTC, datetime

    from cloudeo.evaluation.compare import (
        BudgetExceeded,
        DirtyCodeRefused,
        Ledger,
        estimate,
        load_thresholds,
        plan,
        run_comparison,
    )
    from cloudeo.evaluation.contracts import EvalConfiguration
    from cloudeo.evaluation.runner import holdout_dir, load_suite

    baseline = EvalConfiguration.model_validate_json(args.baseline.read_text())
    candidate = EvalConfiguration.model_validate_json(args.candidate.read_text())
    ledger = Ledger(args.ledger or args.out / "ledger.jsonl")
    thresholds = load_thresholds(args.thresholds) if args.thresholds else None
    if args.run_cap_usd is None:
        args.run_cap_usd = thresholds.run_cap_usd if thresholds else 7.0
    if args.week_cap_usd is None:
        args.week_cap_usd = thresholds.week_cap_usd if thresholds else 20.0
    if thresholds:
        print(f"thresholds: {thresholds.id} (digest {thresholds.digest[:12]}), frozen for this run")
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
                seed=args.seed, require_clean=args.require_clean, thresholds=thresholds,
            )
        )  # fmt: skip
    except (BudgetExceeded, DirtyCodeRefused) as exc:
        print(f"refused: {exc}")
        return 2
    print((args.out / f"comparison-{comparison.run_id}.md").read_text())
    # Observational runs report only; a judged run exits 0 only on pass.
    return {"observational": 0, "pass": 0, "fail": 1, "inconclusive": 2}[comparison.gate_verdict]


if __name__ == "__main__":
    sys.exit(main())
