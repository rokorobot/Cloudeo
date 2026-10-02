"""ADR-030 boundary checks for cloudeo.orchestration (and cloudeo.control).

Each check runs on the real packages, on a conforming fixture, and on a
violating fixture that it must catch.
"""

import ast
import inspect
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel

import cloudeo.control
import cloudeo.orchestration
from cloudeo.control import machine
from cloudeo.control.model import WorkOrder

CONTROL = Path(cloudeo.control.__file__).parent
ORCHESTRATION = Path(cloudeo.orchestration.__file__).parent


def sources(package: Path) -> dict[str, str]:
    return {path.name: path.read_text() for path in sorted(package.glob("*.py"))}


def imported_modules(tree: ast.AST, package: str) -> list[str]:
    """Absolute names of every imported module, including `from x import y` as x.y."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
                base = f"{parent}.{base}" if base else parent
            found += [base, *(f"{base}.{alias.name}" for alias in node.names)]
    return found


def _root(node: ast.AST) -> str | None:
    """The name an attribute, subscript, or call chain starts from."""
    while isinstance(node, ast.Attribute | ast.Subscript | ast.Call):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


# --- Check 1: cloudeo.control never imports cloudeo.orchestration ---


def control_imports_orchestration(source: str) -> list[str]:
    tree = ast.parse(source)
    return [
        f"import {name}"
        for name in imported_modules(tree, "cloudeo.control")
        if name == "cloudeo.orchestration" or name.startswith("cloudeo.orchestration.")
    ]


def test_control_never_imports_orchestration():
    for name, source in sources(CONTROL).items():
        assert control_imports_orchestration(source) == [], name
    assert control_imports_orchestration("from cloudeo.control import model") == []


@pytest.mark.negative
@pytest.mark.parametrize(
    "source",
    [
        "import cloudeo.orchestration",
        "from cloudeo.orchestration.kernel_outcome import kernel_outcome_from_gate",
        "from cloudeo import orchestration",
        "from ..orchestration import baseline",
    ],
)
def test_check_1_catches_control_importing_orchestration(source):
    assert control_imports_orchestration(source)


# --- Check 2: promotion stays gate-owned; lifecycle primitives in this slice ---

PERMANENT_CALLS = {"promote"}  # ADR-030: forbidden outside the gate, permanently
SLICE_CALLS = {"checkpoint_candidate", "reject", "cleanup"}  # changes only by explicit decision
FORBIDDEN_IMPORTS = ("cloudeo.workspace.git", "subprocess")
FORBIDDEN_STRINGS = ("refs/cloudeo", "update-ref")


def lifecycle_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    found = []

    def forbidden(name: str) -> str | None:
        if name in PERMANENT_CALLS:
            return f"{name} (permanent)"
        if name in SLICE_CALLS:
            return f"{name} (this slice)"
        return None

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and (label := forbidden(node.func.attr))
        ):
            found.append(f"call {label}")
        # getattr(broker, "promote") is the same call spelled differently.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and (label := forbidden(node.args[1].value))
        ):
            found.append(f"getattr {label}")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found += [f"string {s}" for s in FORBIDDEN_STRINGS if s in node.value]
    found += [
        f"import {name}"
        for name in imported_modules(tree, "cloudeo.orchestration")
        if name.startswith(FORBIDDEN_IMPORTS)
    ]
    return found


LIFECYCLE_CONFORMING = """
from cloudeo.longhorizon.promotion_gate import checkpoint_and_promote_verified
from cloudeo.workspace.broker import WorkspaceBroker

def run(broker: WorkspaceBroker, candidate, verification):
    state = broker.accepted_state()
    return checkpoint_and_promote_verified(broker, candidate, verification, message="m")
"""


def test_orchestration_has_no_direct_lifecycle_calls():
    for name, source in sources(ORCHESTRATION).items():
        assert lifecycle_violations(source) == [], name
    # Calling the authorized gate by name is allowed.
    assert lifecycle_violations(LIFECYCLE_CONFORMING) == []


@pytest.mark.negative
@pytest.mark.parametrize(
    "source,violation",
    [
        ("broker.promote(checkpoint)", "call promote (permanent)"),
        ("getattr(broker, 'promote')(checkpoint)", "getattr promote (permanent)"),
        ("broker.checkpoint_candidate(candidate, 'm')", "call checkpoint_candidate (this slice)"),
        ("broker.reject(candidate, 'no')", "call reject (this slice)"),
        ("broker.cleanup(candidate)", "call cleanup (this slice)"),
        ("from cloudeo.workspace.git import GitWorkspaceBroker", "import cloudeo.workspace.git"),
        ("import subprocess", "import subprocess"),
        ("REF = 'refs/cloudeo/workspaces/demo/accepted'", "string refs/cloudeo"),
    ],
)
def test_check_2_catches_direct_lifecycle_access(source, violation):
    assert violation in lifecycle_violations(source)


# --- Check 3: every WorkOrder transition goes through cloudeo.control.machine ---


def _models(annotation) -> set[type[BaseModel]]:
    """Every pydantic model an annotation refers to, through unions and containers."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {annotation}
    return {m for arg in typing.get_args(annotation) for m in _models(arg)}


def _reachable(roots: set[type[BaseModel]]) -> set[type[BaseModel]]:
    seen: set[type[BaseModel]] = set()
    todo = list(roots)
    while todo:
        model = todo.pop()
        if model in seen:
            continue
        seen.add(model)
        for field in model.model_fields.values():
            todo += _models(field.annotation)
    return seen


def _machine_inputs() -> set[type[BaseModel]]:
    """Records a caller may build and pass to a public transition function."""
    inputs: set[type[BaseModel]] = set()
    for name, function in inspect.getmembers(machine, inspect.isfunction):
        if name.startswith("_") or function.__module__ != machine.__name__:
            continue
        hints = typing.get_type_hints(function)
        hints.pop("return", None)
        for annotation in hints.values():
            inputs |= _models(annotation)
    # The WorkOrder argument is what the function transforms, not an input record.
    return _reachable(inputs - {WorkOrder})


# Records only the state machine creates: reachable from WorkOrder, never an input.
STATE_TYPES = _reachable({WorkOrder}) - _machine_inputs()
STATE_NAMES = {model.__name__ for model in STATE_TYPES}
COPY_METHODS = {"evolve", "model_copy"}
CLASS_BUILDERS = {
    "model_validate",
    "model_validate_json",
    "model_validate_strings",
    "model_construct",
}


def workorder_violations(source: str) -> list[str]:
    """Construction, changed copies, or mutation of WorkOrder state (flow-insensitive)."""
    tree = ast.parse(source)
    machine_aliases, machine_functions, state = set(), set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "cloudeo.control":
            machine_aliases |= {a.asname or a.name for a in node.names if a.name == "machine"}
        elif isinstance(node, ast.ImportFrom) and node.module == "cloudeo.control.machine":
            machine_functions |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.Import):
            machine_aliases |= {
                a.asname for a in node.names if a.name == "cloudeo.control.machine" and a.asname
            }

    def names_state(annotation: ast.AST | None) -> bool:
        if annotation is None:
            return False
        for n in ast.walk(annotation):
            if isinstance(n, ast.Name) and n.id in STATE_NAMES:
                return True
            # String annotations: "WorkOrder", "WorkOrder | None".
            if (
                isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and any(s in n.value for s in STATE_NAMES)
            ):
                return True
        return False

    def from_machine(value: ast.AST) -> bool:
        if not isinstance(value, ast.Call):
            return False
        func = value.func
        if isinstance(func, ast.Name):
            return func.id in machine_functions
        return isinstance(func, ast.Attribute) and _root(func) in machine_aliases

    # Names that hold WorkOrder state: annotated as such, or results of transitions.
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and names_state(node.annotation):
            state.add(node.arg)
        elif isinstance(node, ast.AnnAssign) and names_state(node.annotation):
            state.add(_root(node.target))
        elif isinstance(node, ast.Assign) and from_machine(node.value):
            state |= {_root(t) for t in node.targets}
    state.discard(None)

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if called in STATE_NAMES:
                found.append(f"constructs {called}")
            elif (
                isinstance(func, ast.Attribute)
                and func.attr in CLASS_BUILDERS
                and isinstance(func.value, ast.Name)
                and func.value.id in STATE_NAMES
            ):
                found.append(f"builds {func.value.id} via {func.attr}")
            elif (
                isinstance(func, ast.Attribute)
                and func.attr in COPY_METHODS
                and _root(func.value) in state
            ):
                found.append(f"changed copy of {_root(func.value)} via {func.attr}")
            elif (
                called in ("setattr", "__setattr__", "delattr", "__delattr__")
                and node.args
                and _root(node.args[0]) in state
            ):
                found.append(f"mutates {_root(node.args[0])} via {called}")
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = node.targets
        for target in targets:
            if isinstance(target, ast.Attribute | ast.Subscript) and _root(target) in state:
                found.append(f"mutates {_root(target)}")
    return found


def test_state_types_are_derived_from_the_control_model():
    # Inputs the machine accepts (KernelOutcome, Candidate, AuditRecord, ...)
    # may be built by callers; these records only the state machine creates.
    assert STATE_NAMES == {
        "WorkOrder",
        "Block",
        "AttemptRecord",
        "AttentionRequest",
        "PlanApproval",
    }


WORKORDER_CONFORMING = """
from cloudeo.control import machine as m
from cloudeo.control.model import EvidenceRef, KernelOutcome, WorkOrder

def apply(wo: WorkOrder, result, baseline: str) -> WorkOrder:
    outcome = KernelOutcome(promotion_attempted=True, stage="promoted", reason="r",
                            evidence=EvidenceRef(kind="k", ref="x"))
    workspace = wo.candidate.workspace_id if wo.candidate else None  # reading is fine
    copied = result.model_copy(update={"stage": "promoted"})  # an unrelated model
    other = something.evolve(x=1)  # an unrelated object with evolve()
    wo = m.start_execution(wo, accepted_baseline=baseline)
    return m.record_kernel_outcome(wo, outcome)
"""


def test_orchestration_changes_workorders_only_through_the_machine():
    for name, source in sources(ORCHESTRATION).items():
        assert workorder_violations(source) == [], name
    assert workorder_violations(WORKORDER_CONFORMING) == []


VIOLATING_HEADER = """
from cloudeo.control import machine as m
from cloudeo.control.model import Block, WorkOrder
"""


@pytest.mark.negative
@pytest.mark.parametrize(
    "body,violation",
    [
        ("wo = WorkOrder(work_order_id='x')", "constructs WorkOrder"),
        ("b = Block(spec=spec)", "constructs Block"),
        ("wo = WorkOrder.model_validate(data)", "builds WorkOrder via model_validate"),
        ("wo = WorkOrder.model_construct(**data)", "builds WorkOrder via model_construct"),
        (
            "def f(wo: WorkOrder):\n    return wo.evolve(status='PROMOTED')",
            "changed copy of wo via evolve",
        ),
        (
            "def f(wo: WorkOrder):\n    return wo.model_copy(update={})",
            "changed copy of wo via model_copy",
        ),
        (
            "def f(wo: 'WorkOrder'):\n    return wo.blocks[0].evolve(status='X')",
            "changed copy of wo via evolve",
        ),
        (
            "wo = m.start_intake(w, accepted_baseline=b)\nwo2 = wo.evolve(status='X')",
            "changed copy of wo via evolve",
        ),
        ("def f(wo: WorkOrder):\n    wo.status = 'PROMOTED'", "mutates wo"),
        (
            "def f(wo: WorkOrder):\n    object.__setattr__(wo, 'status', 'PROMOTED')",
            "mutates wo via __setattr__",
        ),
        ("def f(wo: WorkOrder):\n    setattr(wo, 'status', 'PROMOTED')", "mutates wo via setattr"),
    ],
)
def test_check_3_catches_workorder_construction_copies_and_mutation(body, violation):
    assert violation in workorder_violations(VIOLATING_HEADER + body)
