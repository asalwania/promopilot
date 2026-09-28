"""Record the LLM cassettes that let planning sessions replay with no API key (ADR 0019).

With the planner agent (ADR 0049), each brief is also planned through the tools, so its
tool-calling turns are recorded too; that needs trained models and loaded data.
"""

import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from promopilot.agents.context import BriefError
from promopilot.agents.planner_agent import AgentTools, DefaultSequence, plan_with_tools
from promopilot.agents.session import BriefData, read_planning_request
from promopilot.domain import PlanningRequest
from promopilot.llm import LLMError, LLMProvider, RecordingProvider, cassette_paths


class RecordingError(Exception):
    """A brief did not become a planning request, or the planner agent could not plan it, so
    no cassette was changed."""


@dataclass(frozen=True)
class RecordedPlanning:
    """The planner agent to record each brief's planning turns with, and its default sequence."""

    agent: AgentTools
    default: DefaultSequence


async def record_cassettes(
    briefs: Sequence[str],
    live: LLMProvider,
    data: BriefData,
    cassette_dir: Path,
    *,
    planning: RecordedPlanning | None = None,
) -> list[PlanningRequest]:
    """Read each brief through `live`, recording every LLM request as a cassette.

    With `planning`, each brief is then planned by the planner agent through `live`, so its
    tool-calling turns are recorded too (ADR 0049); a brief the agent cannot plan without the
    default sequence fails the run. Without it, recording needs no trained model (ADR 0038).

    Cassettes are recorded into a scratch directory and replace those in `cassette_dir` only
    once every brief has become a planning request, so a failed run changes nothing and a full run
    leaves no stale cassette behind. Other files in `cassette_dir` are kept.
    """
    with tempfile.TemporaryDirectory() as scratch:
        recorder = RecordingProvider(live, Path(scratch))
        results = []
        for brief in briefs:
            try:
                request = await read_planning_request(brief, recorder, data)
            except (BriefError, LLMError) as error:
                raise RecordingError(
                    f"brief {brief!r} did not become a planning request: {error}"
                ) from error
            if planning is not None:
                planned = await plan_with_tools(
                    brief, request, recorder, planning.agent, planning.default
                )
                if planned.degraded is not None:
                    raise RecordingError(
                        f"the planner agent could not plan brief {brief!r} "
                        f"({planned.degraded.value})"
                    )
            results.append(request)
        _replace_cassettes(Path(scratch), cassette_dir)
    return results


def _replace_cassettes(recorded: Path, cassette_dir: Path) -> None:
    for stale in cassette_paths(cassette_dir):
        stale.unlink()
    cassette_dir.mkdir(parents=True, exist_ok=True)
    for cassette in cassette_paths(recorded):
        shutil.copy2(cassette, cassette_dir / cassette.name)
