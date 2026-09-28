"""`python -m promopilot.cassettes`: re-record the LLM cassettes with a live provider.

`make record-cassettes` reads every brief in `cassettes/briefs.json` through the provider named
by LLM_PROVIDER, against the data loaded in Postgres (`make data`), then plans it with the
planner agent on the trained models (`make train`), so its tool-calling turns are recorded too.
It replaces the cassettes only if every brief becomes a planning request and the planner agent
plans it (ADR 0019, ADR 0038, ADR 0049).
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from promopilot.agents import PlanningError, RecordedPlanning, RecordingError, record_cassettes
from promopilot.api.planning import build_planning
from promopilot.config import Settings
from promopilot.llm import build_provider, cassette_paths


async def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m promopilot.cassettes", description=__doc__)
    parser.add_argument("--briefs", type=Path, default=Path("cassettes/briefs.json"))
    args = parser.parse_args(argv)

    settings = Settings()
    if settings.llm_provider in ("replay", "fake"):
        print(
            f"recording needs a live provider, not LLM_PROVIDER={settings.llm_provider}",
            file=sys.stderr,
        )
        return 2
    briefs = json.loads(args.briefs.read_text(encoding="utf-8"))
    engine = create_async_engine(settings.database_url)
    planning = build_planning(settings, engine)
    try:
        results = await record_cassettes(
            briefs,
            build_provider(settings),
            planning.data,
            settings.llm_cassette_dir,
            planning=RecordedPlanning(planning.agent, planning.planner),
        )
    except (RecordingError, PlanningError, LookupError, ValueError) as error:
        print(f"no cassettes changed: {error}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    for brief, request in zip(briefs, results, strict=True):
        print(f"{request.model_dump_json()} for {brief!a}")
    print(f"recorded {len(cassette_paths(settings.llm_cassette_dir))} cassettes")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    sys.exit(main())
