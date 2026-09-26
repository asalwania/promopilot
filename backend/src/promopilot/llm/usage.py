"""Per-session token and cost accounting (SPEC §9.6, ADR 0027).

Providers report every billed call with `record_usage`. A planning session opens a
`track_usage()` scope, and every call made inside it, including from the tasks it awaits,
lands in that scope's `UsageMeter`. The scope lives in a context variable, so concurrent
sessions sharing one provider never count each other's calls. Scopes nest: a call counts
towards its own scope and every enclosing one.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel, ConfigDict

from promopilot.config import ModelPrice

_MTOK = 1_000_000


class Usage(BaseModel):
    """The tokens one provider call was billed for, under the configured model id."""

    model_config = ConfigDict(frozen=True)

    model: str
    input_tokens: int
    output_tokens: int


class UsageTotals(BaseModel):
    """A meter's sums: calls, tokens and cost in dollars and rupees."""

    model_config = ConfigDict(frozen=True)

    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_inr: float
    unpriced_models: tuple[str, ...]
    """Models with no configured price: their tokens count, their cost is left out."""


class UsageMeter:
    """Collects the usage recorded inside one `track_usage()` scope."""

    def __init__(self, parent: "UsageMeter | None" = None) -> None:
        self._usages: list[Usage] = []
        self._parent = parent

    def record(self, usage: Usage) -> None:
        self._usages.append(usage)
        if self._parent is not None:
            self._parent.record(usage)

    @property
    def usages(self) -> tuple[Usage, ...]:
        return tuple(self._usages)

    def totals(self, prices: Mapping[str, ModelPrice], *, usd_inr_rate: float) -> UsageTotals:
        cost_usd = 0.0
        unpriced: list[str] = []
        for usage in self._usages:
            price = prices.get(usage.model)
            if price is None:
                if usage.model not in unpriced:
                    unpriced.append(usage.model)
                continue
            cost_usd += (
                usage.input_tokens * price.input_usd_per_mtok
                + usage.output_tokens * price.output_usd_per_mtok
            ) / _MTOK
        return UsageTotals(
            calls=len(self._usages),
            input_tokens=sum(u.input_tokens for u in self._usages),
            output_tokens=sum(u.output_tokens for u in self._usages),
            cost_usd=cost_usd,
            cost_inr=cost_usd * usd_inr_rate,
            unpriced_models=tuple(unpriced),
        )


_current: ContextVar[UsageMeter | None] = ContextVar("promopilot_llm_usage", default=None)


@contextmanager
def track_usage() -> Iterator[UsageMeter]:
    """Count every provider call made inside the `with` block (and in tasks it starts)."""
    meter = UsageMeter(parent=_current.get())
    token = _current.set(meter)
    try:
        yield meter
    finally:
        _current.reset(token)


def record_usage(usage: Usage) -> None:
    """Report one billed call to the enclosing scope; outside any scope it is dropped."""
    meter = _current.get()
    if meter is not None:
        meter.record(usage)
