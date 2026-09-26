"""Record the LLM cassettes that let planning sessions replay with no API key (ADR 0019)."""

import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

from promopilot.agents.context import BriefError
from promopilot.agents.session import PlanningData, PlanningResult, plan_session
from promopilot.llm import LLMError, LLMProvider, RecordingProvider, cassette_paths


class RecordingError(Exception):
    """A brief did not reach a plan, so no cassette was changed."""


async def record_cassettes(
    briefs: Sequence[str], live: LLMProvider, data: PlanningData, cassette_dir: Path
) -> list[PlanningResult]:
    """Plan each brief through `live`, recording every LLM request as a cassette.

    Cassettes are recorded into a scratch directory and replace those in `cassette_dir` only
    once every brief has reached a plan, so a failed run changes nothing and a full run
    leaves no stale cassette behind. Other files in `cassette_dir` are kept.
    """
    with tempfile.TemporaryDirectory() as scratch:
        recorder = RecordingProvider(live, Path(scratch))
        results = []
        for brief in briefs:
            try:
                results.append(await plan_session(brief, recorder, data))
            except (BriefError, LLMError) as error:
                raise RecordingError(f"brief {brief!r} did not reach a plan: {error}") from error
        _replace_cassettes(Path(scratch), cassette_dir)
    return results


def _replace_cassettes(recorded: Path, cassette_dir: Path) -> None:
    for stale in cassette_paths(cassette_dir):
        stale.unlink()
    cassette_dir.mkdir(parents=True, exist_ok=True)
    for cassette in cassette_paths(recorded):
        shutil.copy2(cassette, cassette_dir / cassette.name)
