"""Generating the demo brief's candidates is fast, and gives the same options as before (#113).

The seed-42 world is fitted as `make train` fits it. Generation is timed twice and the faster
run counts, so one stall on a busy machine does not fail the test (ADR 0087).
"""

import time

import pytest
from pandas.testing import assert_frame_equal

from promopilot.domain import PlanLine
from promopilot.models.demand import DemandModel, Prediction, PredictionContext
from promopilot.optimizer import OptionContext, generate_options
from tests.conftest import DEMO_BRIEF
from tests.unit.models.reference_demand import Reference

BUDGET_SECONDS = 4.0
RUNS = 2


@pytest.mark.model
def test_the_demo_brief_generates_its_candidates_within_four_seconds(
    demo_context: OptionContext,
) -> None:
    timings = []
    for _ in range(RUNS):
        started = time.perf_counter()
        options = generate_options(DEMO_BRIEF, demo_context)
        timings.append(time.perf_counter() - started)

    assert len(options.lines) > 10_000
    assert min(timings) < BUDGET_SECONDS, (
        f"generation took {', '.join(f'{t:.1f} s' for t in timings)}"
    )


@pytest.mark.model
def test_the_demo_briefs_candidates_equal_the_reference_pipelines_bit_for_bit(
    demo_context: OptionContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    options = generate_options(DEMO_BRIEF, demo_context)

    def predict(self: DemandModel, lines: list[PlanLine], context: PredictionContext) -> Prediction:
        return Reference(self).predict(lines, context)

    monkeypatch.setattr(DemandModel, "predict", predict)
    monkeypatch.setattr(
        DemandModel,
        "line_paths",
        lambda self, lines, context: Reference(self).line_paths(lines, context),
    )
    reference = generate_options(DEMO_BRIEF, demo_context)

    assert options.lines == reference.lines
    assert options.enumerated == reference.enumerated
    assert options.pruned == reference.pruned
    assert_frame_equal(options.table, reference.table, check_exact=True)
