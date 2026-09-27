"""Candidate sets kept in process between `generate_candidates` and `run_optimizer` (ADR 0035).

The planner sees only a summary of the options it generated and the id of the full set; the
optimiser looks the set up by that id, so tens of thousands of options never pass through
the LLM. A set keeps the facts it was generated with, so the optimiser prices pairs on the
same models even after a retrain (ADR 0036). Only the most recent sets are kept. Each keeps
the latest optimiser solution found on it, which the planner agent's plan revision is built
from (ADR 0049).
"""

from collections import OrderedDict
from dataclasses import dataclass
from uuid import UUID, uuid4

from promopilot.domain import PlanningRequest
from promopilot.optimizer.options import PromoOptions
from promopilot.optimizer.solver import OptimisationResult, OptionFacts

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
        self._solutions: dict[UUID, OptimisationResult] = {}

    def put(
        self,
        request: PlanningRequest,
        options: PromoOptions,
        facts: OptionFacts,
        *,
        candidate_set_id: UUID | None = None,
    ) -> CandidateSet:
        """Store a set under `candidate_set_id`, or a fresh id. A set already under that id is
        replaced, and its solution forgotten."""
        stored = CandidateSet(
            candidate_set_id=candidate_set_id or uuid4(),
            request=request,
            options=options,
            facts=facts,
        )
        self._sets[stored.candidate_set_id] = stored
        self._sets.move_to_end(stored.candidate_set_id)
        self._solutions.pop(stored.candidate_set_id, None)
        while len(self._sets) > self._capacity:
            dropped, _ = self._sets.popitem(last=False)
            self._solutions.pop(dropped, None)
        return stored

    def get(self, candidate_set_id: UUID) -> CandidateSet | None:
        """The set, or None when it was never stored or has been dropped."""
        found = self._sets.get(candidate_set_id)
        if found is not None:
            self._sets.move_to_end(candidate_set_id)
        return found

    def record_solution(self, candidate_set_id: UUID, result: OptimisationResult) -> None:
        """Keep the latest optimiser result for a stored set, so the planner can build its plan
        revision without solving again (ADR 0049). A set no longer stored is ignored."""
        if candidate_set_id in self._sets:
            self._solutions[candidate_set_id] = result

    def solution(self, candidate_set_id: UUID) -> OptimisationResult | None:
        """The latest optimiser result recorded for the set; None when none is."""
        return self._solutions.get(candidate_set_id)
