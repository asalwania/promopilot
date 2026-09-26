"""The in-process candidate store the optimiser reads generated options from (ADR 0035)."""

from uuid import uuid4

import pandas as pd
import pytest

from promopilot.domain import PlanningRequest, PromoWindow, Region, Scope
from promopilot.optimizer import TABLE_COLUMNS, CandidateStore, PromoOptions, PruneReason

REQUEST = PlanningRequest(
    as_of_week=10,
    scope=Scope(regions=(Region.NORTH,), categories=("Snacks",)),
    promo_window=PromoWindow(start_week=11, end_week=12),
    marketing_budget=1000.0,
)


def options(enumerated: int) -> PromoOptions:
    return PromoOptions(
        lines=(),
        table=pd.DataFrame(columns=TABLE_COLUMNS),
        enumerated=enumerated,
        pruned=dict.fromkeys(PruneReason, 0),
    )


def test_a_stored_set_is_found_by_its_id() -> None:
    store = CandidateStore()

    stored = store.put(REQUEST, options(7))

    found = store.get(stored.candidate_set_id)
    assert found is stored
    assert found.request == REQUEST
    assert found.options.enumerated == 7
    assert store.get(uuid4()) is None


def test_only_the_most_recently_used_sets_are_kept() -> None:
    store = CandidateStore(capacity=2)
    first = store.put(REQUEST, options(1))
    second = store.put(REQUEST, options(2))

    assert store.get(first.candidate_set_id) is first  # now the most recent
    third = store.put(REQUEST, options(3))

    assert store.get(second.candidate_set_id) is None
    assert store.get(first.candidate_set_id) is first
    assert store.get(third.candidate_set_id) is third
    with pytest.raises(ValueError, match="at least one"):
        CandidateStore(capacity=0)
