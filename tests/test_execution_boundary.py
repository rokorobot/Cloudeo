"""ADR-035 dependency direction (PN-12) and control provider-blindness (PN-01).

Each forbidden edge has a mechanical AST check with a negative test, in the
style of test_orchestration_boundary.py. The allowed edges (orchestration ->
control, orchestration -> execution) are deliberately not checked here.
"""

import ast
from pathlib import Path

import pytest
from test_orchestration_boundary import imported_modules

import cloudeo.control
import cloudeo.execution
import cloudeo.orchestration

PACKAGES = {
    "cloudeo.control": Path(cloudeo.control.__file__).parent,
    "cloudeo.execution": Path(cloudeo.execution.__file__).parent,
    "cloudeo.orchestration": Path(cloudeo.orchestration.__file__).parent,
}

# (importer, forbidden target)
FORBIDDEN_EDGES = [
    ("cloudeo.control", "cloudeo.execution"),
    ("cloudeo.control", "cloudeo.orchestration"),
    ("cloudeo.execution", "cloudeo.control"),
    ("cloudeo.execution", "cloudeo.orchestration"),
]


def edge_violations(source: str, importer: str, target: str) -> list[str]:
    tree = ast.parse(source)
    return [
        name
        for name in imported_modules(tree, importer)
        if name == target or name.startswith(target + ".")
    ]


@pytest.mark.parametrize("importer,target", FORBIDDEN_EDGES)
def test_forbidden_dependency_edges_are_absent(importer, target):
    for path in sorted(PACKAGES[importer].rglob("*.py")):
        assert edge_violations(path.read_text(), importer, target) == [], path.name


@pytest.mark.negative
@pytest.mark.parametrize("importer,target", FORBIDDEN_EDGES)
@pytest.mark.parametrize(
    "template",
    ["import {t}", "from {t}.sub import x", "from {p} import {leaf}"],
)
def test_edge_check_catches_each_forbidden_edge(importer, target, template):
    parent, leaf = target.rsplit(".", 1)
    source = template.format(t=target, p=parent, leaf=leaf)
    assert edge_violations(source, importer, target)


@pytest.mark.negative
def test_edge_check_catches_a_relative_import_of_the_target():
    assert edge_violations("from ..control import model", "cloudeo.execution", "cloudeo.control")


def test_allowed_edges_are_not_flagged():
    assert (
        edge_violations(
            "from cloudeo.control import model", "cloudeo.orchestration", "cloudeo.execution"
        )
        == []
    )


# --- PN-01: control is provider-blind ---

PROVIDER_SDKS = ("anthropic", "openai", "google.generativeai", "mistralai", "cohere")
PROVIDER_NAMES = {"anthropic", "openai", "moonshot", "kimi", "claude", "codex", "gpt"}


def provider_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    found = [
        f"import {name}"
        for name in imported_modules(tree, "cloudeo.control")
        if any(name == sdk or name.startswith(sdk + ".") for sdk in PROVIDER_SDKS)
    ]
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for operand in [node.left, *node.comparators]:
                if (
                    isinstance(operand, ast.Constant)
                    and isinstance(operand.value, str)
                    and operand.value.lower() in PROVIDER_NAMES
                ):
                    found.append(f"compares to provider name {operand.value!r}")
    return found


def test_control_imports_no_provider_sdk_and_has_no_provider_branching():
    for path in sorted(PACKAGES["cloudeo.control"].rglob("*.py")):
        assert provider_violations(path.read_text()) == [], path.name


@pytest.mark.negative
@pytest.mark.parametrize(
    "source",
    [
        "import anthropic",
        "from openai import OpenAI",
        "if provider == 'anthropic':\n    pass",
        "x = model.provider in ('a',) or 'Kimi' == model.provider",
    ],
)
def test_provider_blindness_check_catches_sdk_imports_and_provider_branches(source):
    assert provider_violations(source)
