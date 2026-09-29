"""The in-process candidate store the optimiser reads generated options from (ADR 0035)."""

from collections.abc import Sequence
from uuid import uuid4

import pandas as pd
import pytest

from promopilot.domain import PlanLine, PlanningRequest, PromoPlan, PromoWindow, Region, Scope
from promopilot.guardrails import SkuFacts, SubstituteFacts
from promopilot.optimizer import (
    TABLE_COLUMNS,
    CandidateStore,
    OptimisationResult,
    PromoOptions,
    PruneReason,
    SolveStatus,
)

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

    def substitutes(self, sku_ids: Sequence[str]) -> Sequence[SubstituteFacts]:
        return []


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


def result(objective: float) -> OptimisationResult:
    return OptimisationResult(
        status=SolveStatus.OPTIMAL,
        objective=objective,
        plan=PromoPlan(lines=()),
        selected=(),
        pairwise_cannibalisation=0.0,
        eligible=0,
        pairs=0,
    )


def test_a_set_can_be_stored_under_a_given_id_and_replaced_under_it() -> None:
    store = CandidateStore()
    key = uuid4()

    first = store.put(REQUEST, options(1), FACTS, candidate_set_id=key)
    store.record_solution(key, result(5.0))
    second = store.put(REQUEST, options(2), FACTS, candidate_set_id=key)

    assert first.candidate_set_id == second.candidate_set_id == key
    assert store.get(key) is second
    assert store.solution(key) is None, "a replaced set forgets the solution of the old one"


def test_the_latest_solution_of_a_set_is_kept_with_it_until_the_set_is_dropped() -> None:
    store = CandidateStore(capacity=1)
    first = store.put(REQUEST, options(1), FACTS)

    store.record_solution(first.candidate_set_id, result(5.0))
    store.record_solution(first.candidate_set_id, result(7.0))

    solved = store.solution(first.candidate_set_id)
    assert solved is not None
    assert solved.objective == 7.0
    store.put(REQUEST, options(2), FACTS)
    assert store.solution(first.candidate_set_id) is None
    store.record_solution(uuid4(), result(1.0))  # a dropped or unknown set is ignored
