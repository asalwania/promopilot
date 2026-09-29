"""`python -m promopilot.evals` (`make eval`): run the eval scenarios and write the report.

Every scenario in `evals/scenarios/` (or those named with `--only`) plays through the full
agent graph on the eval's own world, the one `make data` generates with this seed, with models
fitted as of each scenario's week. The LLM is the provider LLM_PROVIDER names: `replay` (the
default) answers from the committed cassettes, the eval's `evals/cassettes/` first and then the
app's, and needs no key; a request with no cassette falls back as the stack does, and the report
counts every fallback (ADR 0056, ADR 0065). The report goes to `evals/reports/` as
`<timestamp>.json` and `.md`, and as `latest.json` and `latest.md`.

`--record` (`make record-eval-cassettes`) plays the scenarios on the live provider LLM_PROVIDER
names and writes every answer no cassette holds into `evals/cassettes/`; it costs money.

It exits 0 once the report is written, whatever the metrics say; 1 for an invalid scenario and
2 for bad arguments.
"""

import argparse
import asyncio
import io
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from promopilot.agents import LLMPricing, PlanningSettings
from promopilot.config import Settings
from promopilot.datagen import load_config
from promopilot.evals.cassettes import (
    EVAL_CASSETTE_DIR,
    LiveUsage,
    recording_provider,
    replay_provider,
)
from promopilot.evals.report import (
    REPORT_DIR,
    EvalReport,
    format_amount,
    format_value,
    write_report,
)
from promopilot.evals.runner import run as run_scenarios
from promopilot.evals.scenarios import SCENARIO_DIR, load_scenarios
from promopilot.evals.world import EvalWorld
from promopilot.llm import LLMProvider, build_provider


async def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m promopilot.evals", description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=SCENARIO_DIR, help="scenario folder")
    parser.add_argument(
        "--only", action="append", metavar="NAME", help="run only this scenario (repeatable)"
    )
    parser.add_argument("--runs", type=int, default=1, help="runs per scenario")
    parser.add_argument("--seed", type=int, help="the world's seed; defaults to the config's")
    parser.add_argument("--config", type=Path, help="YAML overriding datagen/config.yaml")
    parser.add_argument("--out", type=Path, default=REPORT_DIR, help="report folder")
    parser.add_argument(
        "--cassettes", type=Path, default=EVAL_CASSETTE_DIR, help="the eval's cassette folder"
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="play live and record every answer no cassette holds (costs money)",
    )
    args = parser.parse_args(argv)
    if args.runs < 1:
        print("--runs must be at least 1", file=sys.stderr)
        return 2
    settings = Settings()
    if args.record and settings.llm_provider in ("replay", "fake"):
        print(
            f"recording needs a live provider, not LLM_PROVIDER={settings.llm_provider}",
            file=sys.stderr,
        )
        return 2

    try:
        scenarios = load_scenarios(args.scenarios)
    except (ValidationError, ValueError) as error:
        print(f"invalid scenario: {error}", file=sys.stderr)
        return 1
    if args.only:
        unknown = sorted(set(args.only).difference(s.name for s in scenarios))
        if unknown:
            print(f"no scenario is named {', '.join(unknown)}", file=sys.stderr)
            return 2
        scenarios = [scenario for scenario in scenarios if scenario.name in args.only]
    if not scenarios:
        print(f"no scenario in {args.scenarios}", file=sys.stderr)
        return 2

    config = load_config(args.config)
    world = EvalWorld.generated(config.seed if args.seed is None else args.seed, config)
    live = LiveUsage(build_provider(settings)) if args.record else None
    provider, provider_name = _provider(settings, args.cassettes, live)
    print(
        f"running {len(scenarios)} scenario(s) x {args.runs} on the seed-{world.seed} world "
        f"with LLM_PROVIDER={provider_name}",
        flush=True,
    )
    report = await run_scenarios(
        scenarios,
        provider,
        args.runs,
        world=world,
        settings=PlanningSettings.from_settings(settings),
        pricing=LLMPricing(prices=settings.llm_prices, usd_inr_rate=settings.usd_inr_rate),
        provider_name=provider_name,
        progress=lambda line: print(line, flush=True),
    )
    paths = write_report(report, args.out)
    _summary(report)
    print(f"wrote {paths.json} and {paths.markdown} (and {paths.latest_markdown.name})")
    if live is not None:
        totals = live.meter.totals(settings.llm_prices, usd_inr_rate=settings.usd_inr_rate)
        print(
            f"recorded into {args.cassettes}: {totals.calls} live calls, {totals.input_tokens} "
            f"input and {totals.output_tokens} output tokens, ${totals.cost_usd:.2f} "
            f"(INR {totals.cost_inr:.0f})"
        )
    return 0


def _provider(
    settings: Settings, cassettes: Path, live: LLMProvider | None
) -> tuple[LLMProvider, str]:
    """The LLM the scenarios play on, and its name in the report: the live model recording into
    the eval's cassettes, the eval's and the app's cassettes replayed, or the live model."""
    if live is not None:
        recorder = recording_provider(live, cassettes, settings.llm_cassette_dir)
        return recorder, f"{settings.llm_provider} (recording)"
    if settings.llm_provider == "replay":
        return replay_provider(cassettes, settings.llm_cassette_dir), "replay"
    return build_provider(settings), settings.llm_provider


def _summary(report: EvalReport) -> None:
    for metric in report.metrics:
        value = format_value(metric)
        counted = f", {metric.count} of {metric.of}" if metric.of else ""
        target = (
            ""
            if metric.target is None
            else f" (target {format_amount(metric, metric.target, share_digits=0)})"
        )
        aim = (
            ""
            if metric.aim is None
            else f" (aim {format_amount(metric, metric.aim, share_digits=0)})"
        )
        verdict = "" if metric.passed is None else (" pass" if metric.passed else " FAIL")
        print(f"{metric.label}: {value}{counted}{target}{aim}{verdict}")
    if report.runs_per_scenario < 2:
        print("consistency needs at least two runs per scenario: make eval RUNS=5")
    passed = sum(scenario.passed for scenario in report.scenarios)
    print(f"scenarios passed: {passed} of {len(report.scenarios)}")


def main(argv: Sequence[str] | None = None) -> int:
    # Briefs carry ₹: never let a Windows console's code page stop the report.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
    return asyncio.run(run(argv))


if __name__ == "__main__":
    sys.exit(main())
