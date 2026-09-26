"""Per-session token and cost accounting (ADR 0027): totals are hand-checkable sums."""

import asyncio

import pytest

from promopilot.config import ModelPrice, Settings
from promopilot.llm import Usage, UsageMeter, record_usage, track_usage

PRICES = {
    "gpt-4.1-mini": ModelPrice(input_usd_per_mtok=0.40, output_usd_per_mtok=1.60),
    "claude-sonnet-5": ModelPrice(input_usd_per_mtok=2.00, output_usd_per_mtok=10.00),
}


def test_totals_add_tokens_and_price_each_call_by_its_model() -> None:
    with track_usage() as meter:
        record_usage(Usage(model="gpt-4.1-mini", input_tokens=1_000, output_tokens=200))
        record_usage(Usage(model="gpt-4.1-mini", input_tokens=3_000, output_tokens=800))
        record_usage(Usage(model="claude-sonnet-5", input_tokens=2_000, output_tokens=500))

    totals = meter.totals(PRICES, usd_inr_rate=96.0)

    # gpt-4.1-mini: 4,000 in x $0.40/M + 1,000 out x $1.60/M = $0.0016 + $0.0016 = $0.0032
    # claude-sonnet-5: 2,000 in x $2/M + 500 out x $10/M = $0.004 + $0.005 = $0.009
    assert totals.calls == 3
    assert totals.input_tokens == 6_000
    assert totals.output_tokens == 1_500
    assert totals.cost_usd == pytest.approx(0.0122)
    assert totals.cost_inr == pytest.approx(0.0122 * 96.0)
    assert totals.unpriced_models == ()


def test_a_model_without_a_price_counts_tokens_but_no_cost_and_is_named() -> None:
    with track_usage() as meter:
        record_usage(Usage(model="mystery-model", input_tokens=500, output_tokens=50))
        record_usage(Usage(model="claude-sonnet-5", input_tokens=1_000_000, output_tokens=0))

    totals = meter.totals(PRICES, usd_inr_rate=96.0)

    assert (totals.input_tokens, totals.output_tokens) == (1_000_500, 50)
    assert totals.cost_usd == pytest.approx(2.0)
    assert totals.unpriced_models == ("mystery-model",)


def test_an_inner_scope_also_counts_towards_the_enclosing_one() -> None:
    with track_usage() as session:
        record_usage(Usage(model="gpt-4.1-mini", input_tokens=10, output_tokens=1))
        with track_usage() as call:
            record_usage(Usage(model="gpt-4.1-mini", input_tokens=20, output_tokens=2))

    assert [u.input_tokens for u in call.usages] == [20]
    assert [u.input_tokens for u in session.usages] == [10, 20]


def test_usage_outside_any_scope_is_dropped() -> None:
    record_usage(Usage(model="gpt-4.1-mini", input_tokens=10, output_tokens=1))

    assert UsageMeter().usages == ()


async def test_concurrent_sessions_each_count_only_their_own_calls() -> None:
    async def session(tokens: int) -> UsageMeter:
        with track_usage() as meter:
            for _ in range(3):
                await asyncio.sleep(0)
                record_usage(Usage(model="gpt-4.1-mini", input_tokens=tokens, output_tokens=0))
        return meter

    first, second = await asyncio.gather(session(1), session(100))

    assert first.totals(PRICES, usd_inr_rate=96.0).input_tokens == 3
    assert second.totals(PRICES, usd_inr_rate=96.0).input_tokens == 300


def test_settings_price_the_default_models_and_convert_to_rupees() -> None:
    settings = Settings()

    assert settings.llm_prices["gpt-4.1-mini"] == PRICES["gpt-4.1-mini"]
    assert settings.llm_prices["claude-sonnet-5"] == PRICES["claude-sonnet-5"]
    assert settings.usd_inr_rate == 96.0


def test_prices_can_be_overridden_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LLM_PRICES", '{"gpt-x": {"input_usd_per_mtok": 1, "output_usd_per_mtok": 4}}'
    )
    monkeypatch.setenv("USD_INR_RATE", "90.5")

    settings = Settings()

    assert settings.llm_prices == {"gpt-x": ModelPrice(input_usd_per_mtok=1, output_usd_per_mtok=4)}
    assert settings.usd_inr_rate == 90.5
