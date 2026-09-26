import json
from pathlib import Path

import pytest

from tools.coverage_gate import CORE_PACKAGES, core_line_coverage, main


def report(files: dict[str, tuple[int, int]]) -> dict[str, object]:
    """A coverage.py JSON report: path -> (statements, covered lines)."""
    return {
        "files": {
            path: {"summary": {"num_statements": statements, "covered_lines": covered}}
            for path, (statements, covered) in files.items()
        }
    }


def write(tmp_path: Path, files: dict[str, tuple[int, int]]) -> Path:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(report(files)), encoding="utf-8")
    return path


def test_core_packages_are_the_spec_list_plus_economics_and_domain() -> None:
    assert set(CORE_PACKAGES) == {
        "datagen",
        "models",
        "optimizer",
        "simulator",
        "agents",
        "economics",
        "domain",
    }


def test_line_coverage_counts_only_core_package_files() -> None:
    coverage = core_line_coverage(
        report(
            {
                "src/promopilot/datagen/generator.py": (100, 90),
                "src\\promopilot\\domain\\plan.py": (100, 70),
                "src/promopilot/api/main.py": (100, 0),
                "src/promopilot/data/retail.py": (100, 0),
                "src/promopilot/evals/oracle.py": (100, 0),
            }
        )
    )

    assert coverage == pytest.approx(80.0)


def test_a_core_package_that_does_not_exist_yet_is_simply_absent() -> None:
    coverage = core_line_coverage(report({"src/promopilot/economics/profit.py": (10, 9)}))

    assert coverage == pytest.approx(90.0)


def test_the_gate_fails_below_85_percent(tmp_path: Path) -> None:
    path = write(tmp_path, {"src/promopilot/datagen/a.py": (1000, 849)})

    assert main([str(path)]) == 1


def test_the_gate_passes_at_exactly_85_percent(tmp_path: Path) -> None:
    path = write(tmp_path, {"src/promopilot/datagen/a.py": (1000, 850)})

    assert main([str(path)]) == 0


def test_the_gate_passes_when_no_core_package_exists_yet(tmp_path: Path) -> None:
    path = write(tmp_path, {"src/promopilot/api/main.py": (10, 0)})

    assert main([str(path)]) == 0
