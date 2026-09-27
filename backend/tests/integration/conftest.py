"""Integration tests run on a selector event loop: psycopg's async mode, which LangGraph's
Postgres checkpointer uses, cannot run on the Proactor loop Windows defaults to (ADR 0046)."""

import asyncio
from collections.abc import Callable, Mapping

import pytest


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
    return {"selector": asyncio.SelectorEventLoop}
