"""The in-process candidate store the optimiser reads generated options from (ADR 0035)."""

from collections.abc import Sequence
from uuid import uuid4

import pandas as pd
import pytest

from promopilot.domain import PlanLine, PlanningRequest, PromoWindow, Region, Scope
from promopilot.guardrails import SkuFacts
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


class Facts:
    def sku(self, sku_id: str, region: Region) -> SkuFacts:
        return SkuFacts(category="Snacks", base_price=10.0, unit_cost=5.0, overstocked=False)

    def pairwise_cannibalisation(
        self, pairs: Sequence[tuple[PlanLine, PlanLine]]
    ) -> Sequence[float]:
        return [0.0] * len(pairs)


FACTS = Facts()


def test_a_stored_set_is_found_by_its_id_with_the_facts_it_was_generated_with() -> None:
    store = CandidateStore()

    stored = store.put(REQUEST, options(7), FACTS)

    found = store.get(stored.candidate_set_id)
    assert found is stored
    assert found.request == REQUEST
    assert found.options.enumerated == 7
    assert found.facts is FACTS
    assert store.get(uuid4()) is None


def test_only_the_most_recently_used_sets_are_kept() -> None:
    store = CandidateStore(capacity=2)
    first = store.put(REQUEST, options(1), FACTS)
    second = store.put(REQUEST, options(2), FACTS)

    assert store.get(first.candidate_set_id) is first  # now the most recent
    third = store.put(REQUEST, options(3), FACTS)

    assert store.get(second.candidate_set_id) is None
    assert store.get(first.candidate_set_id) is first
    assert store.get(third.candidate_set_id) is third
    with pytest.raises(ValueError, match="at least one"):
        CandidateStore(capacity=0)
