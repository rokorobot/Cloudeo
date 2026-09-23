"""Control store: persistence for WorkOrders and Project Execution Profiles (§14.1).

ControlStore is the storage interface; SqliteControlStore is the initial
implementation (standard-library sqlite3). PostgreSQL can replace it without
changing WorkOrder semantics, because every rule lives above the SQL:

- every write re-validates the record (model validators) and checks it is a
  legal successor of the stored version (check_evolution);
- updates are compare-and-swap on (work_order_id, version) (V2C-23);
- every write appends an event; nothing is ever deleted (V2C-21);
- a Project Execution Profile version is immutable once saved (V2C-18).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cloudeo.control.model import ProjectExecutionProfile, WorkOrder, check_evolution


class ControlStoreError(Exception):
    pass


class StaleWriteError(ControlStoreError):
    """Another writer changed the record first; reload and retry the decision."""


class NotFoundError(ControlStoreError):
    pass


class ImmutableRecordError(ControlStoreError):
    """An immutable record would change."""


@dataclass(frozen=True)
class ControlEvent:
    work_order_id: str
    version: int
    event: str
    status: str


class ControlStore(Protocol):
    def save_profile(self, profile: ProjectExecutionProfile) -> None: ...

    def get_profile(self, project_id: str, version: int) -> ProjectExecutionProfile: ...

    def current_profile(self, project_id: str) -> ProjectExecutionProfile: ...

    def create(self, work_order: WorkOrder, *, event: str) -> WorkOrder: ...

    def get(self, work_order_id: str) -> WorkOrder: ...

    def update(self, work_order: WorkOrder, *, expected_version: int, event: str) -> WorkOrder: ...

    def events(self, work_order_id: str) -> list[ControlEvent]: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_profiles (
    project_id   TEXT    NOT NULL,
    version      INTEGER NOT NULL,
    content_hash TEXT    NOT NULL,
    data         TEXT    NOT NULL,
    PRIMARY KEY (project_id, version)
);
CREATE TABLE IF NOT EXISTS work_orders (
    work_order_id TEXT    PRIMARY KEY,
    version       INTEGER NOT NULL,
    data          TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS work_order_events (
    work_order_id TEXT    NOT NULL,
    version       INTEGER NOT NULL,
    event         TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    data          TEXT    NOT NULL,
    PRIMARY KEY (work_order_id, version)
);
"""


def _dump(record) -> str:
    return json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class SqliteControlStore:
    def __init__(self, path: Path | str):
        self._path = str(path)
        with closing(self._connect()) as db, db:
            db.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, isolation_level=None, timeout=5)
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def _transaction(self, db: sqlite3.Connection):
        # BEGIN IMMEDIATE: the write lock is taken before the version is read.
        db.execute("BEGIN IMMEDIATE")

    # --- Project Execution Profiles ---

    def save_profile(self, profile: ProjectExecutionProfile) -> None:
        content_hash = profile.canonical_sha256()
        with closing(self._connect()) as db:
            self._transaction(db)
            try:
                row = db.execute(
                    "SELECT content_hash FROM execution_profiles WHERE project_id=? AND version=?",
                    (profile.project_id, profile.version),
                ).fetchone()
                if row is not None:
                    if row[0] != content_hash:
                        raise ImmutableRecordError(
                            f"profile {profile.project_id} v{profile.version} already exists "
                            "with different content; publish a new version instead"
                        )
                    db.execute("COMMIT")
                    return
                latest = db.execute(
                    "SELECT MAX(version) FROM execution_profiles WHERE project_id=?",
                    (profile.project_id,),
                ).fetchone()[0]
                if profile.version != (latest or 0) + 1:
                    raise ControlStoreError(
                        f"the next profile version for {profile.project_id} is {(latest or 0) + 1}"
                    )
                db.execute(
                    "INSERT INTO execution_profiles VALUES (?, ?, ?, ?)",
                    (profile.project_id, profile.version, content_hash, _dump(profile)),
                )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def get_profile(self, project_id: str, version: int) -> ProjectExecutionProfile:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT data FROM execution_profiles WHERE project_id=? AND version=?",
                (project_id, version),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"profile {project_id} v{version}")
        return ProjectExecutionProfile.model_validate_json(row[0])

    def current_profile(self, project_id: str) -> ProjectExecutionProfile:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT data FROM execution_profiles WHERE project_id=? "
                "ORDER BY version DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"no approved profile for {project_id}")
        return ProjectExecutionProfile.model_validate_json(row[0])

    # --- WorkOrders ---

    def _require_stored_profile(self, db: sqlite3.Connection, work_order: WorkOrder) -> None:
        profile = work_order.execution_profile
        row = db.execute(
            "SELECT content_hash FROM execution_profiles WHERE project_id=? AND version=?",
            (profile.project_id, profile.version),
        ).fetchone()
        if row is None or row[0] != profile.canonical_sha256():
            raise ControlStoreError(
                "the WorkOrder's profile snapshot must be an approved, stored profile version"
            )

    def create(self, work_order: WorkOrder, *, event: str) -> WorkOrder:
        stored = work_order.evolve(version=1)
        with closing(self._connect()) as db:
            self._transaction(db)
            try:
                self._require_stored_profile(db, stored)
                try:
                    db.execute(
                        "INSERT INTO work_orders VALUES (?, ?, ?)",
                        (stored.work_order_id, 1, _dump(stored)),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ControlStoreError(f"{stored.work_order_id} already exists") from exc
                self._append_event(db, stored, event)
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return stored

    def get(self, work_order_id: str) -> WorkOrder:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT data FROM work_orders WHERE work_order_id=?", (work_order_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(work_order_id)
        # Reload re-runs every model validator.
        return WorkOrder.model_validate_json(row[0])

    def update(self, work_order: WorkOrder, *, expected_version: int, event: str) -> WorkOrder:
        with closing(self._connect()) as db:
            self._transaction(db)
            try:
                row = db.execute(
                    "SELECT version, data FROM work_orders WHERE work_order_id=?",
                    (work_order.work_order_id,),
                ).fetchone()
                if row is None:
                    raise NotFoundError(work_order.work_order_id)
                if row[0] != expected_version:
                    raise StaleWriteError(
                        f"{work_order.work_order_id} is at version {row[0]}, not {expected_version}"
                    )
                current = WorkOrder.model_validate_json(row[1])
                stored = work_order.evolve(version=expected_version + 1)
                check_evolution(current, stored)
                if stored.execution_profile != current.execution_profile:
                    self._require_stored_profile(db, stored)
                changed = db.execute(
                    "UPDATE work_orders SET version=?, data=? WHERE work_order_id=? AND version=?",
                    (stored.version, _dump(stored), stored.work_order_id, expected_version),
                ).rowcount
                if changed != 1:  # second CAS layer, independent of the check above
                    raise StaleWriteError(work_order.work_order_id)
                self._append_event(db, stored, event)
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return stored

    def _append_event(self, db: sqlite3.Connection, work_order: WorkOrder, event: str) -> None:
        db.execute(
            "INSERT INTO work_order_events VALUES (?, ?, ?, ?, ?)",
            (
                work_order.work_order_id,
                work_order.version,
                event,
                str(work_order.status),
                _dump(work_order),
            ),
        )

    def events(self, work_order_id: str) -> list[ControlEvent]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT work_order_id, version, event, status FROM work_order_events "
                "WHERE work_order_id=? ORDER BY version",
                (work_order_id,),
            ).fetchall()
        return [ControlEvent(*row) for row in rows]

    def replay(self, work_order_id: str) -> list[WorkOrder]:
        """Every stored version, reconstructed and re-validated, in order."""
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT data FROM work_order_events WHERE work_order_id=? ORDER BY version",
                (work_order_id,),
            ).fetchall()
        return [WorkOrder.model_validate_json(row[0]) for row in rows]
