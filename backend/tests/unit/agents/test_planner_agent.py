"""The LLM planner agent in the agent graph (AG-03, SF-03, #47, ADR 0049), driven with a
FakeProvider: the tools it calls, the plan it ends with, the structured errors it sees and the
default sequence it falls back to."""

import json
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from promopilot.agents import (
    AgentTools,
    DegradedReason,
    GraphTools,
    MemoryTrace,
    PlannedRevision,
    StoredRevisions,
    build_graph,
    checkpoint_serializer,
    graph_state,
    loosening,
    read_planning_request,
    start_planning,
)
from promopilot.agents.planner_agent import MAX_STEPS, MAX_TOOL_CALLS
from promopilot.agents.state import PlanningState
from promopilot.agents.tools import ToolError, ToolOk, ToolRegistry, ToolResult, ToolSpec
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.agents.tools.generate_candidates import (
    GenerateCandidatesOutput,
    generate_candidates_tool,
)
from promopilot.agents.tools.get_competitor_gaps import get_competitor_gaps_tool
from promopilot.agents.tools.run_optimizer import RunOptimizerOutput, run_optimizer_tool
from promopilot.competitors import CompetitorGap, CompetitorGaps
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    DecisionMade,
    PlanningRequest,
    PlanSafetyMargin,
    PromoWindow,
    Region,
    Scope,
    SolveStatus,
    ToolCalled,
)
from promopilot.guardrails import RiskThresholds
from promopilot.llm import (
    CassetteMissError,
    FakeProvider,
    LLMError,
    ToolCall,
    ToolTurn,
)
from promopilot.models.demand import DemandModel
from promopilot.models.registry import ModelKind
from promopilot.models.relations import Relations
from promopilot.optimizer import CandidateStore, SolverSettings
from tests.unit.agents.fakes import InMemoryRetailData, explainer_down
from tests.unit.agents.test_generate_candidates import Fixed, entry
from tests.unit.agents.test_graph import (
    BRIEF,
    POLICY,
    READING,
    RecordedSessions,
    ScriptedPlanner,
    planned,
)
from tests.unit.agents.test_plan_session import FREE, planner_of

HISTORY_WEEKS = 52  # small_config
SET_ID = UUID("00000000-0000-0000-0000-000000000047")


class ScriptedTools:
    """Tools answered from a script per tool name: an output model, a `ToolError`, or an
    exception the tool raises (a failing tool)."""

    def __init__(self, script: Mapping[str, Sequence[BaseModel | Exception]]) -> None:
        self._script = {name: list(steps) for name, steps in script.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=name,
                description=f"The {name} tool.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            )
            for name in (*self._script, "get_competitor_gaps")
        ]

    async def call(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        self.calls.append((name, dict(arguments)))
        steps = self._script.get(name)
        if not steps:
            if name == "get_competitor_gaps":
                return ToolOk(output=no_gaps())
            raise AssertionError(f"no scripted answer left for {name}")
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        if isinstance(step, Exception):
            raise step
        if isinstance(step, ToolError):
            return step
        return ToolOk(output=step)

    def called(self) -> list[str]:
        return [name for name, _ in self.calls]


class Revisions:
    """The plan revision of each solved candidate set."""

    def __init__(self, solved: Mapping[UUID, PlannedRevision]) -> None:
        self._solved = dict(solved)

    async def revision(self, candidate_set_id: UUID) -> PlannedRevision | None:
        return self._solved.get(candidate_set_id)


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class Generated(BaseModel):
    candidate_set_id: UUID


def optimised(candidate_set_id: UUID = SET_ID) -> RunOptimizerOutput:
    return RunOptimizerOutput(
        candidate_set_id=candidate_set_id,
        status=SolveStatus.OPTIMAL,
        objective=6_250.0,
        lines=[],
        total_promo_cost=1_500.0,
        planned_promo_cost=1_500.0,
        marketing_budget=20_000.0,
        blended_margin=None,
        min_margin=0.15,
        pairwise_cannibalisation=0.0,
        candidate_options=10,
        eligible_options=4,
        pairs=0,
        binding_constraints=[],
        not_selected=[],
        clearance_shortfalls=[],
        policy_findings=[],
        relaxation=None,
        safety_margin=PlanSafetyMargin(planned_promo_cost=1_500.0),
    )


def gap(**changes: Any) -> CompetitorGap:
    fields: dict[str, Any] = {
        "region": Region.NORTH,
        "sku_id": "SKU0001",
        "name": "Masala Chips 100g",
        "category": "Snacks",
        "subcategory": "Chips",
        "is_kvi": True,
        "base_price": 100.0,
        "competitor_price": 94.9,
        "competitor_on_promo": False,
        "price_week": HISTORY_WEEKS - 1,
        "cpi": 0.949,
        "gap": 0.051,
        "undercut": True,
    }
    return CompetitorGap.model_validate(fields | changes)


def no_gaps(*gaps: CompetitorGap) -> CompetitorGaps:
    return CompetitorGaps(
        as_of_week=HISTORY_WEEKS, undercut_threshold=0.05, kvi_price_tolerance=0.02, gaps=gaps
    )


def call(name: str, **arguments: Any) -> ToolTurn:
    return ToolTurn(tool_calls=(ToolCall(id=f"call_{name}", name=name, arguments=arguments),))


def finish(text: str = "The optimiser's plan is selected.") -> ToolTurn:
    return ToolTurn(text=text)


@pytest.fixture
def data(small_dataset: GeneratedDataset) -> InMemoryRetailData:
    return InMemoryRetailData(small_dataset)


@pytest.fixture
async def request_read(data: InMemoryRetailData) -> PlanningRequest:
    """The planning request the Context node reads from READING."""
    return await read_planning_request(BRIEF, FakeProvider([READING]), data)


def generate(request: PlanningRequest, **changes: Any) -> ToolTurn:
    return call("generate_candidates", request=request.model_dump(mode="json") | changes)


def run() -> ToolTurn:
    return call("run_optimizer", candidate_set_id=str(SET_ID))


async def plan(
    data: InMemoryRetailData,
    script: Sequence[BaseModel | Exception],
    tools: ScriptedTools | ToolRegistry,
    *,
    trace: MemoryTrace | None = None,
    revisions: Revisions | StoredRevisions | None = None,
    fallback: ScriptedPlanner | None = None,
    sleep: Sleeps | None = None,
    max_steps: int = MAX_STEPS,
    max_tool_calls: int = MAX_TOOL_CALLS,
    risk_thresholds: RiskThresholds | None = None,
) -> tuple[PlanningState, FakeProvider]:
    llm = FakeProvider([READING, *script, explainer_down()])
    graph_tools = GraphTools(
        brief_data=data,
        planner=fallback or ScriptedPlanner(planned(promo_cost=900.0)),
        sessions=RecordedSessions(),
        policy=POLICY,
        trace=trace or MemoryTrace(),
        agent=AgentTools(
            tools=tools,
            revisions=revisions or Revisions({SET_ID: planned()}),
            sleep=sleep or Sleeps(),
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
        ),
        risk_thresholds=risk_thresholds or RiskThresholds(),
    )
    graph = build_graph(graph_tools, llm, InMemorySaver(serde=checkpoint_serializer()))
    session_id = uuid4()
    route = await start_planning(graph, str(session_id), session_id, BRIEF)
    assert route == ["context", "planner", "critic", "explainer", "approval"]
    snapshot = await graph_state(graph, str(session_id))
    assert snapshot is not None
    return snapshot.values, llm


def tool_messages(llm: FakeProvider, call_index: int) -> list[dict[str, Any]]:
    """The tool results the LLM was sent at its `call_index`th call (0 is the Context's)."""
    messages = llm.calls[call_index].messages
    return [json.loads(m.content) for m in messages if m.role == "tool"]


# Scripted tool calls produce the plan, and each is traced.


async def test_scripted_tool_calls_on_the_small_world_produce_the_optimised_plan_each_traced(
    data: InMemoryRetailData,
    small_models: tuple[DemandModel, Relations],
    request_read: PlanningRequest,
) -> None:
    store = CandidateStore()
    demand = Fixed((entry(ModelKind.DEMAND, 1), small_models[0]))
    relations = Fixed((entry(ModelKind.RELATIONS, 1), small_models[1]))
    week = fixed_as_of_week(HISTORY_WEEKS)
    registry = ToolRegistry(
        [
            get_competitor_gaps_tool(data, week, policy=FREE),
            generate_candidates_tool(demand, relations, data, week, policy=FREE, store=store),
            run_optimizer_tool(store, policy=FREE, settings=SolverSettings(), seed=0),
        ]
    )
    # The candidate set's id depends only on the call and the model versions (ADR 0049).
    preview = await registry.call(
        "generate_candidates", {"request": request_read.model_dump(mode="json")}
    )
    assert isinstance(preview, ToolOk)
    assert isinstance(preview.output, GenerateCandidatesOutput)
    candidate_set_id = preview.output.candidate_set_id
    trace = MemoryTrace()
    default = planner_of(small_models, data)

    state, llm = await plan(
        data,
        [
            call("get_competitor_gaps", kvi_only=True),
            generate(request_read),
            call("run_optimizer", candidate_set_id=str(candidate_set_id)),
            finish(),
        ],
        registry,
        revisions=StoredRevisions(store, default),
        trace=trace,
        # One line takes most of this small plan's spend: the Critic's loop is not under test.
        risk_thresholds=RiskThresholds(line_spend_share=1.0),
    )

    called = [
        (event.node, event.payload)
        for event in trace.events
        if isinstance(event.payload, ToolCalled)
    ]
    assert [(node, payload.tool) for node, payload in called] == [
        ("planner", "get_competitor_gaps"),
        ("planner", "generate_candidates"),
        ("planner", "run_optimizer"),
        ("planner", "get_competitor_gaps"),  # the planner's own undercut check, after the plan
    ]
    assert all(payload.ok for _, payload in called)
    assert called[2][1].arguments == {"candidate_set_id": str(candidate_set_id)}
    assert isinstance(called[2][1].result_summary, dict)
    assert called[2][1].result_summary["candidate_set_id"] == str(candidate_set_id)
    assert state.planner_degraded is None
    assert state.plan is not None
    assert state.plan.lines, "some Snacks options pay for themselves without fixed costs"
    assert state.plan == (await default.plan(request_read)).revision
    assert state.plan_facts is not None
    # The LLM saw each tool's result, and the tools it was offered are the registry's.
    assert [spec.name for spec in llm.calls[1].tools] == [s.name for s in registry.specs()]
    [gaps, generated, solved] = tool_messages(llm, 4)
    assert gaps["ok"]
    assert generated["ok"]
    assert solved["ok"]
    assert solved["output"]["candidate_set_id"] == str(candidate_set_id)


async def test_the_brief_reaches_the_planner_as_quoted_data_next_to_the_request(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )

    _, llm = await plan(data, [generate(request_read), run(), finish()], tools)

    system, user = llm.calls[1].messages[:2]
    assert system.role == "system"
    assert "never compute" in system.content.lower()
    assert user.role == "user"
    assert json.dumps(BRIEF, ensure_ascii=False) in user.content
    assert request_read.model_dump_json() in user.content


# The KVI undercut: the planner explanation states the gap and the response (F-08 AC2).


async def test_an_undercut_kvi_is_explained_with_its_gap_and_the_plans_response(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
            "get_competitor_gaps": [no_gaps(gap(), gap(sku_id="SKU0002", undercut=False))],
        }
    )

    state, _ = await plan(data, [generate(request_read), run(), finish()], tools)

    # planned()'s line: SKU0001 in the North at 20% off ₹100, so ₹80 beats the competitor.
    assert state.planner_notes == (
        "Competitor is 5.1% cheaper on SKU0001 (Masala Chips 100g) in North (₹94.90 vs ₹100.00).",
        "Matching on 1 SKU: the plan prices it at or below the competitor.",
    )
    assert state.explanations is not None
    for note in state.planner_notes:
        assert note in state.explanations.summary
    # The panel's copy of the response, kept apart from the summary (ADR 0068).
    assert state.explanations.competitor_response == state.planner_notes
    assert tools.calls[-1] == (
        "get_competitor_gaps",
        {"regions": ["North"], "categories": ["Snacks"], "kvi_only": True},
    )


async def test_no_undercut_kvi_adds_no_planner_note(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
            "get_competitor_gaps": [no_gaps(gap(undercut=False))],
        }
    )

    state, _ = await plan(data, [generate(request_read), run(), finish()], tools)

    assert state.planner_notes == ()
    assert state.explanations is not None
    assert state.explanations.competitor_response == ()


# LLM down: the default sequence plans the degraded plan, with template explanations (SF-03).


async def test_an_llm_down_at_the_first_step_gives_the_degraded_default_plan(
    data: InMemoryRetailData,
) -> None:
    default = ScriptedPlanner(planned(promo_cost=900.0))
    tools = ScriptedTools({"get_competitor_gaps": [no_gaps(gap())]})

    state, _ = await plan(
        data, [LLMError("primary failed; secondary failed")], tools, fallback=default
    )

    assert state.planner_degraded is DegradedReason.LLM_UNAVAILABLE
    assert state.plan == planned(promo_cost=900.0).revision
    assert len(default.requests) == 1
    assert state.planner_notes[0] == (
        "The language model was unavailable, so the default sequence (generate candidates, "
        "optimise, simulate) planned this revision."
    )
    assert state.planner_notes[1].startswith("Competitor is 5.1% cheaper on SKU0001")
    assert state.explanations is not None
    assert state.explanations.summary.startswith("Plan revision 1.")
    assert state.planner_notes[0] in state.explanations.summary
    # Only the undercut response is the competitor's; the degraded note is not (ADR 0068).
    assert state.explanations.competitor_response == state.planner_notes[1:]
    assert len(state.explanations.rationales) == 1
    assert tools.called() == ["get_competitor_gaps"]


async def test_falling_back_to_the_default_sequence_is_a_traced_decision(
    data: InMemoryRetailData,
) -> None:
    trace = MemoryTrace()
    tools = ScriptedTools({"get_competitor_gaps": [no_gaps()]})

    await plan(data, [LLMError("primary failed; secondary failed")], tools, trace=trace)

    decisions = [
        (event.node, event.payload)
        for event in trace.events
        if isinstance(event.payload, DecisionMade)
    ]
    [(node, degraded)] = [d for d in decisions if d[1].decision == "planner_degraded"]
    assert node == "planner"
    assert degraded.summary == (
        "The planner agent could not plan (llm_unavailable), so the deterministic default "
        "sequence plans instead."
    )
    [(node, fallback)] = [d for d in decisions if d[1].decision == "explainer_fallback"]
    assert node == "explainer"
    assert "llm_unavailable" in fallback.summary


async def test_an_llm_down_mid_round_restarts_the_conversation_once_from_the_start(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    # A fallback provider may reject another provider's tool round (ADR 0027): start over.
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )

    state, llm = await plan(
        data,
        [generate(request_read), LLMError("rejected"), generate(request_read), run(), finish()],
        tools,
    )

    assert state.planner_degraded is None
    assert state.plan == planned().revision
    opening = llm.calls[1].messages
    assert llm.calls[3].messages == opening


async def test_an_llm_that_fails_again_after_the_restart_degrades(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    tools = ScriptedTools({"generate_candidates": [Generated(candidate_set_id=SET_ID)]})

    state, _ = await plan(
        data, [generate(request_read), LLMError("down"), LLMError("still down")], tools
    )

    assert state.planner_degraded is DegradedReason.LLM_UNAVAILABLE
    assert state.plan == planned(promo_cost=900.0).revision


async def test_a_cassette_miss_degrades_without_a_restart(data: InMemoryRetailData) -> None:
    tools = ScriptedTools({})

    state, llm = await plan(data, [CassetteMissError("no cassette for request abc")], tools)

    assert state.planner_degraded is DegradedReason.CASSETTE_MISSING
    assert state.plan == planned(promo_cost=900.0).revision
    assert len(llm.calls) == 3, "the reading, the planner's miss and the Explainer"


# Tool errors reach the planner as structured errors; failing tools are retried first.


async def test_a_failing_tool_is_retried_then_reaches_the_planner_as_a_structured_error(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    failing = ConnectionError("database went away")
    tools = ScriptedTools(
        {
            "generate_candidates": [
                failing,
                failing,
                failing,
                Generated(candidate_set_id=SET_ID),
            ],
            "run_optimizer": [optimised()],
        }
    )
    sleeps = Sleeps()

    state, llm = await plan(
        data,
        [generate(request_read), generate(request_read), run(), finish()],
        tools,
        sleep=sleeps,
    )

    [error] = tool_messages(llm, 2)
    assert error["ok"] is False
    assert error["code"] == "tool_failed"
    assert "generate_candidates" in error["message"]
    assert "database went away" in error["message"]
    assert sleeps.delays == [0.5, 1.0]
    assert tools.called()[:4] == ["generate_candidates"] * 4
    assert state.planner_degraded is None
    assert state.plan == planned().revision


async def test_each_attempt_at_a_failing_tool_is_traced(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    trace = MemoryTrace()
    tools = ScriptedTools(
        {
            "generate_candidates": [
                ConnectionError("database went away"),
                Generated(candidate_set_id=SET_ID),
            ],
            "run_optimizer": [optimised()],
        }
    )

    await plan(data, [generate(request_read), run(), finish()], tools, trace=trace)

    called = [e.payload for e in trace.events if isinstance(e.payload, ToolCalled)]
    assert [(c.tool, c.ok, c.error_code) for c in called][:3] == [
        ("generate_candidates", False, "exception"),
        ("generate_candidates", True, None),
        ("run_optimizer", True, None),
    ]
    assert called[0].result_summary == "ConnectionError: database went away"


async def test_a_tool_that_fails_once_is_retried_and_the_planner_sees_its_result(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    tools = ScriptedTools(
        {
            "generate_candidates": [TimeoutError("slow"), Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )

    _, llm = await plan(data, [generate(request_read), run(), finish()], tools)

    [generated] = tool_messages(llm, 2)
    assert generated == {"ok": True, "output": {"candidate_set_id": str(SET_ID)}}


async def test_a_tool_error_is_handed_to_the_planner_without_a_retry(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    unknown = ToolError(code="invalid_input", message="no candidate set is stored")
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [unknown, optimised()],
        }
    )

    state, llm = await plan(
        data, [run(), generate(request_read), run(), finish()], tools, sleep=Sleeps()
    )

    [error] = tool_messages(llm, 2)
    assert error["code"] == "invalid_input"
    assert tools.called()[:2] == ["run_optimizer", "generate_candidates"]
    assert state.plan == planned().revision


# The planner may tighten the optimiser options, never the brief's constraints (ADR 0049).


async def test_a_request_that_loosens_the_brief_is_refused_as_a_structured_error(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )
    doubled = request_read.marketing_budget * 2

    state, llm = await plan(
        data,
        [generate(request_read, marketing_budget=doubled), generate(request_read), run(), finish()],
        tools,
    )

    [error] = tool_messages(llm, 2)
    assert error["ok"] is False
    assert error["code"] == "invalid_input"
    assert "marketing_budget" in error["message"]
    assert tools.called()[:1] == ["generate_candidates"]
    assert len([name for name in tools.called() if name == "generate_candidates"]) == 1
    assert state.plan == planned().revision


@pytest.mark.parametrize(
    "changes",
    [
        {"regional_budget_caps": {"North": 8_000.0}},
        {"kvi_price_tolerance": 0.02},
        {"max_promoted_skus_per_category_per_region": 3},
    ],
)
async def test_the_planner_may_add_optimiser_options_that_tighten_the_plan(
    data: InMemoryRetailData, request_read: PlanningRequest, changes: dict[str, Any]
) -> None:
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )

    state, llm = await plan(data, [generate(request_read, **changes), run(), finish()], tools)

    [generated] = tool_messages(llm, 2)
    assert generated["ok"] is True
    assert state.planner_degraded is None


def test_an_option_the_brief_set_may_only_be_tightened() -> None:
    given = PlanningRequest(
        as_of_week=HISTORY_WEEKS,
        scope=Scope(regions=(Region.NORTH, Region.SOUTH), categories=("Snacks",)),
        promo_window=PromoWindow(start_week=HISTORY_WEEKS + 2, end_week=HISTORY_WEEKS + 3),
        marketing_budget=20_000.0,
        regional_budget_caps={Region.NORTH: 8_000.0},
        kvi_price_tolerance=0.02,
        max_promoted_skus_per_category_per_region=4,
    )

    def loosened(**changes: Any) -> tuple[str, ...]:
        return loosening(given, given.model_copy(update=changes))

    assert loosened() == ()
    assert loosened(regional_budget_caps={Region.NORTH: 7_000.0, Region.SOUTH: 5e3}) == ()
    assert loosened(kvi_price_tolerance=0.01, max_promoted_skus_per_category_per_region=2) == ()
    assert loosened(regional_budget_caps={Region.NORTH: 9_000.0}) == (
        "raises the North regional budget cap",
    )
    assert loosened(regional_budget_caps={}) == ("drops the North regional budget cap",)
    assert loosened(kvi_price_tolerance=None) == ("turns off the KVI price tolerance",)
    assert loosened(kvi_price_tolerance=0.03) == ("widens the KVI price tolerance",)
    assert loosened(max_promoted_skus_per_category_per_region=None) == (
        "drops the promoted-SKU cap",
    )
    assert loosened(max_promoted_skus_per_category_per_region=5) == ("raises the promoted-SKU cap",)
    assert loosened(marketing_budget=10_000.0, min_margin=0.2) == (
        "changes marketing_budget",
        "changes min_margin",
    )
    assert loosened(scope=given.scope.model_copy(update={"sku_ids": ("SKU0001",)})) == (
        "changes scope",
    )


def test_an_analysis_may_narrow_the_scope_but_never_widen_it() -> None:
    given = PlanningRequest(
        as_of_week=HISTORY_WEEKS,
        scope=Scope(regions=(Region.NORTH, Region.SOUTH), categories=("Snacks", "Beverages")),
        promo_window=PromoWindow(start_week=HISTORY_WEEKS + 2, end_week=HISTORY_WEEKS + 3),
        marketing_budget=20_000.0,
    )

    def narrowing(**scope: Any) -> tuple[str, ...]:
        proposed = given.model_copy(update={"scope": given.scope.model_copy(update=scope)})
        return loosening(given, proposed, scope_may_narrow=True)

    assert narrowing() == ()
    assert narrowing(regions=(Region.SOUTH,), categories=("Snacks",), sku_ids=("SKU0001",)) == ()
    assert narrowing(regions=(Region.NORTH, Region.WEST)) == ("widens scope",)
    assert narrowing(categories=("Snacks", "Dairy")) == ("widens scope",)
    listed = given.model_copy(
        update={"scope": given.scope.model_copy(update={"sku_ids": ("SKU0001", "SKU0002")})}
    )
    assert loosening(listed, given, scope_may_narrow=True) == ("widens scope",)
    fewer = given.scope.model_copy(update={"sku_ids": ("SKU0002",)})
    assert (
        loosening(listed, listed.model_copy(update={"scope": fewer}), scope_may_narrow=True) == ()
    )
    # Planning keeps the brief's scope.
    assert loosening(given, listed) == ("changes scope",)


async def test_compare_mechanisms_may_narrow_the_scope_but_generate_candidates_may_not(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    tools = ScriptedTools(
        {
            "compare_mechanisms": [Generated(candidate_set_id=SET_ID)],
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )
    narrowed = request_read.scope.model_copy(update={"sku_ids": ("SKU0001",)})
    scope = narrowed.model_dump(mode="json")

    state, llm = await plan(
        data,
        [
            call(
                "compare_mechanisms",
                request=request_read.model_dump(mode="json") | {"scope": scope},
                sku_id="SKU0001",
                region="North",
            ),
            generate(request_read, scope=scope),
            generate(request_read),
            run(),
            finish(),
        ],
        tools,
    )

    [compared] = tool_messages(llm, 2)
    assert compared["ok"] is True
    [_, refused] = tool_messages(llm, 3)
    assert refused["ok"] is False
    assert "changes scope" in refused["message"]
    assert "exclude_sku_ids" in refused["message"]
    assert tools.called()[:2] == ["compare_mechanisms", "generate_candidates"]
    assert state.planner_degraded is None


# Bounds: the planner always ends, with the optimiser's plan or the default sequence's.


async def test_a_planner_that_stops_without_an_optimised_plan_is_reminded_once_then_degrades(
    data: InMemoryRetailData,
) -> None:
    state, llm = await plan(data, [finish("Done."), finish("Done.")], ScriptedTools({}))

    assert state.planner_degraded is DegradedReason.NO_OPTIMISED_PLAN
    assert state.plan == planned(promo_cost=900.0).revision
    reminder = llm.calls[2].messages[-1]
    assert reminder.role == "user"
    assert "run_optimizer" in reminder.content
    assert state.planner_notes[0].startswith("The planner agent did not reach an optimised plan")


async def test_the_step_limit_ends_planning_with_the_latest_optimised_plan(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )

    state, llm = await plan(data, [generate(request_read), run()], tools, max_steps=2)

    assert len(llm.calls) == 4, "the reading, two planner steps and the Explainer"
    assert state.planner_degraded is None
    assert state.plan == planned().revision


async def test_the_step_limit_with_no_optimised_plan_degrades(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    tools = ScriptedTools({"generate_candidates": [Generated(candidate_set_id=SET_ID)]})

    state, _ = await plan(
        data, [generate(request_read), generate(request_read)], tools, max_steps=2
    )

    assert state.planner_degraded is DegradedReason.NO_OPTIMISED_PLAN


async def test_the_tool_call_limit_stops_the_calls_beyond_it(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )
    both = ToolTurn(tool_calls=(*generate(request_read).tool_calls, *run().tool_calls))

    state, _ = await plan(data, [both], tools, max_tool_calls=1)

    assert tools.called()[:1] == ["generate_candidates"]
    assert "run_optimizer" not in tools.called()
    assert state.planner_degraded is DegradedReason.NO_OPTIMISED_PLAN


async def test_a_solved_set_whose_revision_is_gone_degrades(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )

    state, _ = await plan(
        data, [generate(request_read), run(), finish()], tools, revisions=Revisions({})
    )

    assert state.planner_degraded is DegradedReason.NO_OPTIMISED_PLAN


def test_the_planner_prompt_is_versioned() -> None:
    from importlib.resources import files

    prompt = (files("promopilot.agents") / "prompts" / "planner.md").read_text("utf-8")

    assert prompt.startswith("<!-- prompt: planner v3")
