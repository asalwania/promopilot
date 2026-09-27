"""The grounded Explainer (SPEC §9.6, SF-05, #49, ADR 0050): the LLM explains a plan revision,
numeric grounding checks it, an ungrounded answer is regenerated once and a second failure
falls back to the template. Driven through the agent graph with a FakeProvider."""

from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from promopilot.agents import (
    ExplainerAnswer,
    LineRationale,
    build_graph,
    explain_plan,
    graph_state,
    start_planning,
    template_explanations,
)
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    BindingConstraint,
    BindingEvidence,
    ConstraintKind,
    ConstraintSource,
    ExplanationSource,
    FallbackReason,
    PlanExplanation,
    PlanningRequest,
    PlanRevision,
    PromoWindow,
    Region,
    Relaxation,
    RelaxedConstraint,
    Scope,
    SolveStatus,
)
from promopilot.llm import CassetteMissError, FakeProvider, LLMError, request_hash
from tests.unit.agents.fakes import InMemoryRetailData
from tests.unit.agents.test_graph import (
    BRIEF,
    POLICY,
    READING,
    RecordedSessions,
    planned,
    tools,
)

GROUNDED = ExplainerAnswer(
    summary="One Snacks line in North from W54, expected to add ₹6,250 for a ₹1,500 promo cost.",
    rationales=[
        LineRationale(line=1, rationale="SKU0001 at 20% off is expected to sell 400 units.")
    ],
)
UNGROUNDED = GROUNDED.model_copy(
    update={"summary": "One Snacks line in North, expected to add ₹7,000 in profit."}
)
MISSING_A_LINE = GROUNDED.model_copy(update={"rationales": []})


@pytest.fixture
def data(small_dataset: GeneratedDataset) -> InMemoryRetailData:
    return InMemoryRetailData(small_dataset)


async def explained(
    data: InMemoryRetailData, script: list[BaseModel | Exception]
) -> tuple[PlanExplanation, RecordedSessions, FakeProvider]:
    """Plan the brief through the graph with the Explainer answering `script`."""
    sessions = RecordedSessions()
    llm = FakeProvider([READING, *script])
    graph = build_graph(tools(data, sessions), llm, InMemorySaver())
    session_id = uuid4()

    route = await start_planning(graph, str(session_id), session_id, BRIEF)

    assert route == ["context", "planner", "critic", "explainer", "approval"]
    state = await graph_state(graph, str(session_id))
    assert state is not None
    explanation = state.values.explanations
    assert explanation is not None
    assert sessions.explanations[session_id, 1] == explanation
    return explanation, sessions, llm


def template() -> PlanExplanation:
    return template_explanations(planned().revision)


async def test_a_grounded_answer_is_stored_with_the_plan_revision(
    data: InMemoryRetailData,
) -> None:
    explanation, _, llm = await explained(data, [GROUNDED])

    assert explanation == PlanExplanation(
        summary=GROUNDED.summary,
        rationales=(GROUNDED.rationales[0].rationale,),
        source=ExplanationSource.LLM,
    )
    assert len(llm.calls) == 2


async def test_an_ungrounded_first_answer_is_regenerated_once_naming_its_numbers(
    data: InMemoryRetailData,
) -> None:
    explanation, _, llm = await explained(data, [UNGROUNDED, GROUNDED])

    assert explanation.source is ExplanationSource.LLM
    assert explanation.summary == GROUNDED.summary
    first, regenerated = llm.calls[1:]
    assert regenerated.messages[: len(first.messages)] == first.messages
    assert "₹7,000" in regenerated.messages[-1].content


async def test_a_second_ungrounded_answer_falls_back_to_the_template(
    data: InMemoryRetailData,
) -> None:
    explanation, _, llm = await explained(data, [UNGROUNDED, UNGROUNDED])

    assert explanation == template().model_copy(
        update={"fallback_reason": FallbackReason.UNGROUNDED}
    )
    assert len(llm.calls) == 3


async def test_an_answer_that_misses_a_plan_line_twice_falls_back_as_invalid(
    data: InMemoryRetailData,
) -> None:
    explanation, _, _ = await explained(data, [MISSING_A_LINE, MISSING_A_LINE])

    assert explanation == template().model_copy(
        update={"fallback_reason": FallbackReason.INVALID_ANSWER}
    )


async def test_an_answer_with_a_line_the_plan_does_not_have_is_regenerated(
    data: InMemoryRetailData,
) -> None:
    extra = GROUNDED.model_copy(
        update={"rationales": [*GROUNDED.rationales, LineRationale(line=2, rationale="Extra.")]}
    )

    explanation, _, _ = await explained(data, [extra, GROUNDED])

    assert explanation.source is ExplanationSource.LLM


@pytest.mark.parametrize(
    "failure", [LLMError("both providers down"), CassetteMissError("no cassette abc123")]
)
async def test_an_llm_failure_falls_back_to_the_template_without_regenerating(
    data: InMemoryRetailData, failure: LLMError
) -> None:
    explanation, _, llm = await explained(data, [failure])

    assert explanation == template().model_copy(
        update={"fallback_reason": FallbackReason.LLM_UNAVAILABLE}
    )
    assert len(llm.calls) == 2


def infeasible() -> PlanRevision:
    return planned().revision.model_copy(
        update={
            "solver_status": SolveStatus.INFEASIBLE,
            "binding_constraints": (
                BindingConstraint(
                    kind=ConstraintKind.CLEARANCE_TARGET,
                    source=ConstraintSource.BRIEF,
                    limit=0.9,
                    sku_id="SKU0001",
                    region=Region.NORTH,
                    evidence=BindingEvidence.INFEASIBLE,
                    objective_gain=None,
                ),
            ),
            "relaxation": Relaxation(
                changes=(
                    RelaxedConstraint(
                        kind=ConstraintKind.CLEARANCE_TARGET,
                        sku_id="SKU0001",
                        current=0.9,
                        relaxed=0.7027,
                        change=0.219,
                        policy_allows=0.7027,
                    ),
                ),
                policy_binds=True,
                proven=True,
            ),
        }
    )


async def test_an_infeasible_summary_opens_with_what_binds_then_the_planner_notes() -> None:
    note = "The language model was unavailable, so the default sequence planned this revision."
    request = planned_request()

    explanation = await explain_plan(
        FakeProvider([GROUNDED]), infeasible(), request=request, policy=POLICY, notes=(note,)
    )

    assert explanation.source is ExplanationSource.LLM
    summary = explanation.summary
    assert summary.startswith("Binding constraints: the clearance target for SKU0001 in North")
    assert "the clearance target for SKU0001 from 90% to 70.3%" in summary
    assert "Company policy binds" in summary
    assert summary.index("Company policy binds") < summary.index(note)
    assert summary.endswith(GROUNDED.summary)


async def test_a_feasible_summary_opens_with_the_planner_notes_only() -> None:
    note = "Competitor is 5.1% cheaper on SKU0002 in North (₹94.90 vs ₹100.00); matching on 2 SKUs."

    explanation = await explain_plan(
        FakeProvider([GROUNDED]),
        planned().revision,
        request=planned_request(),
        policy=POLICY,
        notes=(note,),
    )

    assert explanation.summary == f"{note} {GROUNDED.summary}"


async def test_money_must_be_cited_as_the_plan_data_shows_it_in_lakh() -> None:
    line = planned().revision.lines[0]
    big = planned().revision.model_copy(
        update={
            "lines": (line.model_copy(update={"expected_incremental_profit": 1_72_384.2}),),
            "objective": 1_72_384.2,
        }
    )
    in_lakh = GROUNDED.model_copy(update={"summary": "It adds ₹1.72 lakh."})
    exact = GROUNDED.model_copy(update={"summary": "It adds ₹1,72,384."})

    rounded = await explain_plan(
        FakeProvider([in_lakh]), big, request=planned_request(), policy=POLICY
    )
    exact_twice = await explain_plan(
        FakeProvider([exact, exact]), big, request=planned_request(), policy=POLICY
    )

    assert rounded.source is ExplanationSource.LLM
    assert exact_twice.fallback_reason is FallbackReason.UNGROUNDED


async def test_the_request_is_the_same_whatever_the_binding_analysis_had_time_to_prove() -> None:
    def binding(evidence: BindingEvidence, gain: float | None) -> BindingConstraint:
        return BindingConstraint(
            kind=ConstraintKind.MARKETING_BUDGET,
            source=ConstraintSource.BRIEF,
            limit=20_000.0,
            evidence=evidence,
            objective_gain=gain,
        )

    def unproven(kind: ConstraintKind) -> BindingConstraint:
        return BindingConstraint(
            kind=kind,
            source=ConstraintSource.COMPANY_POLICY,
            limit=0.15,
            evidence=BindingEvidence.UNPROVEN,
            objective_gain=None,
        )

    fast = planned().revision.model_copy(
        update={"binding_constraints": (binding(BindingEvidence.EXACT, 8_030.0),)}
    )
    slow = planned().revision.model_copy(
        update={
            "binding_constraints": (
                binding(BindingEvidence.LOWER_BOUND, 2_241.0),
                unproven(ConstraintKind.MARGIN_FLOOR),
            )
        }
    )

    requests = []
    for revision in (fast, slow):
        llm = FakeProvider([GROUNDED])
        await explain_plan(llm, revision, request=planned_request(), policy=POLICY)
        requests.append(request_hash(ExplainerAnswer, llm.calls[0].messages))

    assert requests[0] == requests[1]


def planned_request() -> PlanningRequest:
    return PlanningRequest(
        as_of_week=52,
        scope=Scope(regions=(Region.NORTH,), categories=("Snacks",)),
        promo_window=PromoWindow(start_week=54, end_week=55),
        marketing_budget=20_000.0,
    )
