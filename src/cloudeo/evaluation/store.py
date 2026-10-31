"""SQLite trial index, separate from operational run and control storage.

Append-only: a trial is inserted as "running" and may be finished exactly
once. Finished trials cannot be updated or deleted (enforced by triggers), so a
repeated invocation adds trials and never overwrites one. Each finished trial
is also written as an exclusive-create JSON file next to the index.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from cloudeo.evaluation.contracts import EvalTrial

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    trial_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    suite_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    repetition INTEGER NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL,
    verdict TEXT,
    data TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS trials_finish_once BEFORE UPDATE ON trials
WHEN OLD.status != 'running' OR NEW.trial_id != OLD.trial_id
BEGIN SELECT RAISE(ABORT, 'a finished trial is immutable'); END;
CREATE TRIGGER IF NOT EXISTS trials_no_delete BEFORE DELETE ON trials
BEGIN SELECT RAISE(ABORT, 'trials are never deleted'); END;
"""


class TrialStore:
    def __init__(self, root: Path):
        self.root = root
        (root / "trials").mkdir(parents=True, exist_ok=True)
        self.path = root / "index.sqlite"
        with closing(self._connect()) as db, db:
            db.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def start(self, trial: EvalTrial) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO trials VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                (trial.trial_id, trial.run_id, trial.suite_id, trial.case_id, trial.repetition,
                 trial.label, trial.status, trial.model_dump_json()),
            )  # fmt: skip

    def finish(self, trial: EvalTrial) -> None:
        if trial.status == "running":
            raise ValueError("finish needs a final status")
        data = trial.model_dump_json(indent=2)
        with closing(self._connect()) as db, db:
            changed = db.execute(
                "UPDATE trials SET status=?, verdict=?, data=? "
                "WHERE trial_id=? AND status='running'",
                (trial.status, trial.verdict, data, trial.trial_id),
            ).rowcount
            if changed != 1:
                raise sqlite3.IntegrityError(f"trial {trial.trial_id} is not running")
        with open(self.root / "trials" / f"{trial.trial_id}.json", "x") as f:
            f.write(data + "\n")

    def mark_abandoned(self, current_run_id: str) -> int:
        """Trials left running by an earlier, dead runner become interrupted."""
        with closing(self._connect()) as db, db:
            rows = db.execute(
                "SELECT data FROM trials WHERE status='running' AND run_id != ?",
                (current_run_id,),
            ).fetchall()
        for (data,) in rows:
            trial = EvalTrial.model_validate_json(data)
            self.finish(trial.model_copy(update={"status": "interrupted",
                                                 "error": "runner stopped before the trial finished"}))  # fmt: skip
        return len(rows)

    def trials(self, run_id: str | None = None) -> list[EvalTrial]:
        query, args = "SELECT data FROM trials", ()
        if run_id is not None:
            query, args = query + " WHERE run_id=?", (run_id,)
        with closing(self._connect()) as db:
            rows = db.execute(query + " ORDER BY rowid", args).fetchall()
        return [EvalTrial.model_validate_json(data) for (data,) in rows]
