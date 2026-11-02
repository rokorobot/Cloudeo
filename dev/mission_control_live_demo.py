"""Drive WorkOrders through a real control store slowly, to watch Mission Control
update in real time. Development aid only: it uses the test fixtures' domain
helpers and writes to the store path you give it (never a production store).

    uv run python dev/mission_control_live_demo.py /tmp/mc-demo.db --step 3

Then serve the API with CLOUDEO_CONTROL_DB_PATH=/tmp/mc-demo.db and run
Mission Control with MISSION_CONTROL_SOURCE=control.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from control_helpers import (
    BASE,
    FINAL,
    MEMORY_PATHS,
    OPUS,
    Role,
    _to_execution,
    audit,
    changes,
    m,
    new_work_order,
    passing_checks,
    project_profile,
    proof_for,
    register_all,
    spec,
    state,
)

from cloudeo.control.store import SqliteControlStore


def run(store: SqliteControlStore, work_order, steps, pause: float) -> None:
    wo = store.create(work_order, event="created")
    print(f"{wo.work_order_id} v{wo.version} created", flush=True)
    for event, step in steps:
        time.sleep(pause)
        wo = store.update(step(wo), expected_version=wo.version, event=event)
        print(f"{wo.work_order_id} v{wo.version} {event} -> {wo.status}", flush=True)


def block_steps(block_id: str, scope: str = "src/app"):
    """One stored event per control transition of a block, attempt to proven checkpoint."""
    s = state()
    return [
        (f"block_{block_id}_attempt_started", lambda w: m.begin_attempt(w, block_id, profile=OPUS)),
        (f"block_{block_id}_run_finished", lambda w: m.finish_run(w, block_id)),
        (
            f"block_{block_id}_tests_recorded",
            lambda w: m.record_tests(w, block_id, passing_checks(s)),
        ),
        (
            f"block_{block_id}_code_approved",
            lambda w: m.approve_code(
                w,
                block_id,
                audit=audit(s),
                changes=changes(paths=(f"{scope}/x.py",), allowed=(scope,)),
                current_state=s,
            ),
        ),
        (
            f"block_{block_id}_checkpoint",
            lambda w: m.enter_block_checkpoint(w, block_id, current_state=s),
        ),
        (
            f"block_{block_id}_proven",
            lambda w: m.prove_block_checkpoint(w, block_id, proof=proof_for(s)),
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--step", type=float, default=3.0, help="seconds between events")
    args = parser.parse_args()
    if args.db.exists():
        sys.exit(f"{args.db} exists; give a new path")

    store = SqliteControlStore(args.db)
    register_all(store)
    store.save_profile(project_profile())

    run(
        store,
        new_work_order(),
        [
            *_to_execution((spec("b1", 1), spec("b2", 2))),
            *block_steps("b1"),
            *block_steps("b2"),
            (
                "final_verification_started",
                lambda w: m.enter_final_verification(w, accepted_baseline=BASE),
            ),
            (
                "final_audit_recorded",
                lambda w: m.record_final_audit(w, audit(state(), Role.FINAL_VERIFIER, FINAL)),
            ),
        ],
        args.step,
    )
    run(
        store,
        m.create_work_order(
            work_order_id="wo-2",
            project_id="demo",
            objective="Refresh the importer.",
            memory_paths=MEMORY_PATHS,
            execution_profile=project_profile(),
        ),
        _to_execution((spec("b1", 1),)),
        args.step,
    )


if __name__ == "__main__":
    main()
