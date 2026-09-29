"""Per-client rate limits on the endpoints that start or advance planning (SPEC §6, #70,
ADR 0079).

Creating, amending and clarifying a session each cost LLM calls, so they share one planning
budget per client; re-simulating a plan costs CPU and has its own. Each budget is an
in-process token bucket per client: it holds at most its per-minute limit and refills at that
rate, so a client may send a burst of the limit and then one request per refill. A request
over the limit is 429 `rate_limited` with the error schema and a `Retry-After` header; a
refused request takes no token. Every attempt counts, one the API then refuses as invalid
included, since the limiter runs before the body is validated.

The client is the connection's peer address as uvicorn reports it: uvicorn's
`FORWARDED_ALLOW_IPS` (127.0.0.1 by default) decides which proxy may name the real client in
`X-Forwarded-For`. Behind the Docker web proxy every browser therefore shares one budget.
Buckets live in the process, so each uvicorn worker keeps its own.
"""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Self

from fastapi import Depends, HTTPException, Request, status

from promopilot.config import Settings

DEFAULT_MAX_CLIENTS: Final = 10_000
"""Tracked buckets above which those that have refilled completely are forgotten."""
_WINDOW_S: Final = 60.0
_EPSILON: Final = 1e-9

RETRY_AFTER_DOC: Final = {
    "Retry-After": {
        "description": "Whole seconds until the client may send this request again.",
        "schema": {"type": "integer"},
    }
}
"""The 429's header, as the OpenAPI contract documents it."""


class RateLimitGroup(StrEnum):
    PLANNING = "planning"
    """Creating, amending and clarifying a session."""
    SIMULATIONS = "simulations"
    """Re-simulating a plan revision."""


_WHAT: Final = {
    RateLimitGroup.PLANNING: "planning requests",
    RateLimitGroup.SIMULATIONS: "simulations",
}


@dataclass
class _Bucket:
    tokens: float
    at: float


class RateLimiter:
    def __init__(
        self,
        *,
        planning_per_minute: int,
        simulations_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        max_clients: int = DEFAULT_MAX_CLIENTS,
    ) -> None:
        for name, limit in (
            ("planning_per_minute", planning_per_minute),
            ("simulations_per_minute", simulations_per_minute),
        ):
            if limit < 0:
                raise ValueError(f"{name} must be 0 (off) or more")
        self.per_minute: dict[RateLimitGroup, int] = {
            RateLimitGroup.PLANNING: planning_per_minute,
            RateLimitGroup.SIMULATIONS: simulations_per_minute,
        }
        self._clock = clock
        self._max_clients = max_clients
        self._buckets: dict[tuple[str, RateLimitGroup], _Bucket] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            planning_per_minute=settings.rate_limit_planning_per_minute,
            simulations_per_minute=settings.rate_limit_simulations_per_minute,
        )

    def acquire(self, client: str, group: RateLimitGroup) -> float | None:
        """Take a token from `client`'s `group` bucket: None when there was one, else the
        seconds until there is."""
        limit = self.per_minute[group]
        if limit == 0:
            return None
        now = self._clock()
        rate = limit / _WINDOW_S
        key = (client, group)
        bucket = self._buckets.get(key)
        if bucket is None:
            self._forget_refilled(now)
            bucket = self._buckets[key] = _Bucket(tokens=float(limit), at=now)
        else:
            bucket.tokens = min(float(limit), bucket.tokens + (now - bucket.at) * rate)
            bucket.at = now
        if bucket.tokens >= 1 - _EPSILON:
            bucket.tokens = max(bucket.tokens - 1, 0.0)
            return None
        return (1 - bucket.tokens) / rate

    def tracked(self) -> int:
        """How many buckets are tracked."""
        return len(self._buckets)

    def dependency(self, group: RateLimitGroup) -> Callable[[Request], None]:
        """A FastAPI dependency that answers 429 when the request's client is over the
        `group` limit."""

        def limit(request: Request) -> None:
            client = request.client.host if request.client is not None else "unknown"
            wait = self.acquire(client, group)
            if wait is None:
                return
            seconds = max(1, math.ceil(wait - _EPSILON))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Too many {_WHAT[group]} from this client: at most {self.per_minute[group]} a "
                f"minute. Try again in {seconds} s.",
                headers={"Retry-After": str(seconds)},
            )

        return limit

    def _forget_refilled(self, now: float) -> None:
        if len(self._buckets) < self._max_clients:
            return
        for key, bucket in list(self._buckets.items()):
            limit = self.per_minute[key[1]]
            if bucket.tokens + (now - bucket.at) * limit / _WINDOW_S >= limit - _EPSILON:
                del self._buckets[key]


def rate_limited(limiter: RateLimiter | None, group: RateLimitGroup) -> list[Any]:
    """The route dependencies that limit `group`: none without a limiter."""
    return [] if limiter is None else [Depends(limiter.dependency(group))]


TOO_MANY_REQUESTS: Final[dict[int | str, dict[str, Any]]] = {
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "description": "Too many requests from this client (RATE_LIMIT_*_PER_MINUTE)",
        "headers": RETRY_AFTER_DOC,
    }
}
"""The 429 every limited operation documents, whether or not a limiter is on."""
