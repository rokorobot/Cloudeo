"""Contract between the Python read adapter and the Mission Control UI.

The UI tests render mission-control/src/data/__fixtures__/control-contract.json.
This test proves that file is exactly what the adapter serves for real stored
WorkOrders, so the two sides cannot drift apart silently.

Regenerate after an intentional adapter change:
    UPDATE_UI_CONTRACT=1 pytest tests/test_mission_control_contract.py
"""

import json
import os
from pathlib import Path

from control_helpers import (
    persist_attention_work_order,
    persist_candidate_work_order,
    project_profile,
)

from cloudeo.control.store import SqliteControlStore
from cloudeo.mission_control.query import ReadOnlySqliteControlStore, WorkOrderQuerySource

CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "mission-control/src/data/__fixtures__/control-contract.json"
)


def served(tmp_path):
    path = tmp_path / "control.db"
    store = SqliteControlStore(path)
    store.save_profile(project_profile())
    persist_attention_work_order(store)
    persist_candidate_work_order(store)
    source = WorkOrderQuerySource(ReadOnlySqliteControlStore(path))
    return {
        "list": {"workOrders": [v.to_json() for v in source.list_work_orders()]},
        "detail": {i: source.get_work_order(i).to_json() for i in ("wo-1", "wo-2")},
    }


def test_ui_contract_fixture_matches_the_adapter(tmp_path):
    current = served(tmp_path)
    if os.environ.get("UPDATE_UI_CONTRACT"):
        CONTRACT.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    assert json.loads(CONTRACT.read_text()) == current
