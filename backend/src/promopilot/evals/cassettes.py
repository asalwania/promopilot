"""The eval's LLM cassettes (#56, ADR 0065): `evals/cassettes/`, beside the app's `cassettes/`.

The app's recorder plays `cassettes/sessions.json` on Postgres with the registered models, which
are trained as of week 104. It cannot record a scenario planned at another as-of week, and it
prunes every cassette its manifest does not list (ADR 0054). So the eval keeps its own folder:

- **Replay** reads the eval's folder first, then the app's, so a scenario that asks what an app
  session asked (the starter scenarios) replays the app's cassettes.
- **Recording** (`make record-eval-cassettes`) answers from either folder first, and asks the
  live model only what neither holds, writing that into the eval's folder. It is additive:
  nothing is pruned, and no manifest is kept. To record afresh, empty the folder first.

A request no folder holds raises `CassetteMissError`, and the stack falls back as it does for
any cassette miss (ADR 0056 D11).
"""

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from promopilot.llm import (
    CassetteMissError,
    LLMProvider,
    Message,
    RecordingProvider,
    ReplayProvider,
    ToolSpec,
    ToolTurn,
    UsageMeter,
    track_usage,
)

EVAL_CASSETTE_DIR = Path("evals/cassettes")
"""The eval's own cassettes, relative to backend/."""


class _Layered:
    """Asks each provider in turn, moving on to the next only on a cassette miss."""

    def __init__(self, *providers: LLMProvider) -> None:
        self._providers = providers

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        *first, last = self._providers
        for provider in first:
            try:
                return await provider.complete_structured(schema, messages)
            except CassetteMissError:
                continue
        return await last.complete_structured(schema, messages)

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        *first, last = self._providers
        for provider in first:
            try:
                return await provider.complete_with_tools(tools, messages)
            except CassetteMissError:
                continue
        return await last.complete_with_tools(tools, messages)


class LiveUsage:
    """Wraps the live model and keeps what its calls were billed, so a recording can say what
    it cost; answers replayed from a cassette are not counted."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.meter = UsageMeter()

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        with track_usage() as billed:
            answer = await self._inner.complete_structured(schema, messages)
        self._keep(billed)
        return answer

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        with track_usage() as billed:
            answer = await self._inner.complete_with_tools(tools, messages)
        self._keep(billed)
        return answer

    def _keep(self, billed: UsageMeter) -> None:
        for usage in billed.usages:
            self.meter.record(usage)


def replay_provider(eval_dir: Path, app_dir: Path) -> LLMProvider:
    """Replays the eval's cassettes, then the app's; a request neither holds misses."""
    return _Layered(ReplayProvider(eval_dir), ReplayProvider(app_dir))


def recording_provider(live: LLMProvider, eval_dir: Path, app_dir: Path) -> LLMProvider:
    """Replays the eval's cassettes, then the app's, and asks `live` only what neither holds,
    writing its answer into `eval_dir`."""
    return _Layered(
        ReplayProvider(eval_dir), ReplayProvider(app_dir), RecordingProvider(live, eval_dir)
    )
