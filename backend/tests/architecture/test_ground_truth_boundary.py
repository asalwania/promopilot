"""SPEC §13.4 / ADR 0003: only promopilot.datagen and promopilot.evals touch the ground truth.

Test code is exempt (ADR 0010): tests may compare fitted models with the in-memory truth.
"""

import ast
from pathlib import Path

import promopilot

ALLOWED_PACKAGES = {"datagen", "evals"}
TRUTH_MODULE = "promopilot.datagen.truth"
TRUTH_NAMES = {"GroundTruth", "TrueDemand", "SkuTruth", "StoreTruth", "CrossEffect"}


def ground_truth_references(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.startswith(TRUTH_MODULE)]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(TRUTH_MODULE):
                found.append(node.module)
            elif node.module.startswith("promopilot"):
                found += [a.name for a in node.names if a.name in TRUTH_NAMES]
        elif isinstance(node, ast.Attribute) and node.attr == "ground_truth":
            found.append(f".{node.attr}")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "ground_truth" in node.value
        ):
            found.append(repr(node.value))
    return found


def test_only_datagen_and_evals_reference_the_ground_truth() -> None:
    root = Path(promopilot.__file__).parent
    violations = {}
    for source in root.rglob("*.py"):
        relative = source.relative_to(root)
        if relative.parts[0] in ALLOWED_PACKAGES:
            continue
        found = ground_truth_references(source.read_text(encoding="utf-8"))
        if found:
            violations[str(relative)] = found

    assert violations == {}


def test_the_boundary_check_catches_every_kind_of_reference() -> None:
    assert ground_truth_references("from promopilot.datagen.truth import TrueDemand")
    assert ground_truth_references("import promopilot.datagen.truth")
    assert ground_truth_references("from promopilot.datagen import GroundTruth")
    assert ground_truth_references("x = dataset.ground_truth")
    assert ground_truth_references("path = 'data/ground_truth/ground_truth.json'")
    assert not ground_truth_references("from promopilot.datagen import generate")
