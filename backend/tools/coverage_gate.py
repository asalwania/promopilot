"""Coverage gate (SPEC §6): line coverage of the core packages must be at least 85%.

Reads a coverage.py JSON report (`coverage json`). Core packages that do not exist yet
contribute no files, so the gate keeps working as epics land.

    uv run coverage json -o coverage.json && uv run python -m tools.coverage_gate coverage.json
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

CORE_PACKAGES = ("datagen", "models", "optimizer", "simulator", "agents", "economics", "domain")
THRESHOLD = 85.0


def core_line_coverage(report: dict[str, Any]) -> float | None:
    """Covered lines / statements over core-package files, in percent; None if there are none."""
    statements = covered = 0
    for path, data in report["files"].items():
        parts = Path(path.replace("\\", "/")).parts
        if "promopilot" not in parts:
            continue
        package = parts[parts.index("promopilot") + 1 : parts.index("promopilot") + 2]
        if package and package[0] in CORE_PACKAGES:
            statements += data["summary"]["num_statements"]
            covered += data["summary"]["covered_lines"]
    return 100.0 * covered / statements if statements else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("report", type=Path, help="coverage.py JSON report")
    args = parser.parse_args(argv)
    coverage = core_line_coverage(json.loads(args.report.read_text(encoding="utf-8")))
    if coverage is None:
        print("coverage gate: no core package files measured yet; passing")
        return 0
    verdict = "passes" if coverage >= THRESHOLD else "FAILS"
    print(f"coverage gate: core line coverage {coverage:.1f}% {verdict} (>= {THRESHOLD:.0f}%)")
    return 0 if coverage >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
