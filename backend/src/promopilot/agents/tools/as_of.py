"""The as-of week a data tool reads at: bound when the tool is built, never set by the LLM.

Every data tool takes an `AsOfWeekSource` and awaits it on each call (ADR 0032). The API binds
`RetailData.default_as_of_week`, so newly loaded data moves the clock without a restart; a
planning session or eval scenario binds a fixed week with `fixed_as_of_week`.
"""

from collections.abc import Awaitable, Callable

from promopilot.agents.tools.registry import ToolCallError

type AsOfWeekSource = Callable[[], Awaitable[int]]


def fixed_as_of_week(week: int) -> AsOfWeekSource:
    async def as_of_week() -> int:
        return week

    return as_of_week


async def current_as_of_week(source: AsOfWeekSource) -> int:
    """The source's week; no loaded data (a `LookupError`) becomes a `data_unavailable` error."""
    try:
        return await source()
    except LookupError as error:
        raise ToolCallError("data_unavailable", str(error)) from error
