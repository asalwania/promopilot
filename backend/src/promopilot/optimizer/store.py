"""Candidate sets kept in process between `generate_candidates` and `run_optimizer` (ADR 0035).

The planner sees only a summary of the options it generated and the id of the full set; the
optimiser looks the set up by that id, so tens of thousands of options never pass through
the LLM. A set keeps the facts it was generated with, so the optimiser prices pairs on the
same models even after a retrain (ADR 0036). Only the most recent sets are kept.
"""

from collections import OrderedDict
from dataclasses import dataclass
from uuid import UUID, uuid4

from promopilot.domain import PlanningRequest
from promopilot.optimizer.options import PromoOptions
from promopilot.optimizer.solver import OptionFacts

DEFAULT_CAPACITY = 16


@dataclass(frozen=True)
class CandidateSet:
    """The promo options generated for a planning request, under the id the planner holds."""

    candidate_set_id: UUID
    request: PlanningRequest
    options: PromoOptions
    facts: OptionFacts


class CandidateStore:
    """The last `capacity` candidate sets, oldest dropped first."""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("a candidate store holds at least one set")
        self._capacity = capacity
        self._sets: OrderedDict[UUID, CandidateSet] = OrderedDict()

    def put(
        self, request: PlanningRequest, options: PromoOptions, facts: OptionFacts
    ) -> CandidateSet:
        stored = CandidateSet(
            candidate_set_id=uuid4(), request=request, options=options, facts=facts
        )
        self._sets[stored.candidate_set_id] = stored
        while len(self._sets) > self._capacity:
            self._sets.popitem(last=False)
        return stored

    def get(self, candidate_set_id: UUID) -> CandidateSet | None:
        """The set, or None when it was never stored or has been dropped."""
        found = self._sets.get(candidate_set_id)
        if found is not None:
            self._sets.move_to_end(candidate_set_id)
        return found
