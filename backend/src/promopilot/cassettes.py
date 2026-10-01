"""`python -m promopilot.cassettes`: record the LLM cassettes live, or check they replay.

`make record-cassettes` plays every session script in `cassettes/sessions.json` through the full
agent graph on the provider named by LLM_PROVIDER, against the data loaded in Postgres
(`make data`) and the trained models (`make train`), and records every LLM request. It changes
the cassettes only if every session plays as scripted with nothing falling back; `--only NAME`
re-records just the named sessions and keeps the others (ADR 0019, ADR 0022, ADR 0054).

`--check` plays the same scripts on the cassettes alone, whatever LLM_PROVIDER says, and exits
non-zero naming every miss or fallback, so CI proves the stack replays whole sessions with no
key (ADR 0054).

A refused recording keeps the cassettes but writes the Explainer's live requests and answers to
`cassettes/failed/`, to see what it was shown and wrote when it fell back (ADR 0090).
"""

import argparse
import asyncio
import io
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from promopilot.agents import (
    CassetteManifest,
    PlanningError,
    RecordingError,
    check_cassettes,
    load_scripts,
    record_cassettes,
)
from promopilot.api.planning import build_planning
from promopilot.config import Settings
from promopilot.llm import build_provider, track_usage

FAILED_DIR = "failed"
"""Where a refused recording leaves the Explainer's requests and answers, inside the cassette
folder (git-ignored), to see why it fell back (ADR 0090)."""


async def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m promopilot.cassettes", description=__doc__)
    parser.add_argument("--sessions", type=Path, default=Path("cassettes/sessions.json"))
    parser.add_argument(
        "--only", action="append", metavar="NAME", help="re-record only this session (repeatable)"
    )
    parser.add_argument(
        "--check", action="store_true", help="replay every session from the cassettes alone"
    )
    args = parser.parse_args(argv)

    settings = Settings()
    if not args.check and settings.llm_provider in ("replay", "fake"):
        print(
            f"recording needs a live provider, not LLM_PROVIDER={settings.llm_provider}",
            file=sys.stderr,
        )
        return 2
    scripts = load_scripts(args.sessions)
    engine = create_async_engine(settings.database_url)
    stack = build_planning(settings, engine)
    planning, data = stack.recorded(), stack.data
    try:
        if args.check:
            problems = await check_cassettes(scripts, data, settings.llm_cassette_dir, planning)
            for problem in problems:
                print(problem, file=sys.stderr)
            if problems:
                return 1
            print(f"every session in {args.sessions} replays from {settings.llm_cassette_dir}")
            return 0
        with track_usage() as meter:
            manifest = await record_cassettes(
                scripts,
                build_provider(settings),
                data,
                settings.llm_cassette_dir,
                planning,
                only=args.only,
                failed_dir=settings.llm_cassette_dir / FAILED_DIR,
            )
    except (RecordingError, PlanningError, LookupError, ValueError) as error:
        print(f"{error}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    _report(manifest)
    totals = meter.totals(settings.llm_prices, usd_inr_rate=settings.usd_inr_rate)
    print(
        f"{totals.calls} live calls, {totals.input_tokens} input and {totals.output_tokens} "
        f"output tokens, ${totals.cost_usd:.2f} (INR {totals.cost_inr:.0f})"
    )
    return 0


def _report(manifest: CassetteManifest) -> None:
    for name, session in manifest.sessions.items():
        revisions = ", ".join(
            f"revision {revision.number} ({revision.explanation})" for revision in session.revisions
        )
        print(
            f"{name}: {' -> '.join(session.route)}; {len(session.cassettes)} cassettes; {revisions}"
        )
    cassettes = {digest for session in manifest.sessions.values() for digest in session.cassettes}
    print(f"recorded {len(cassettes)} cassettes and the manifest")


def main(argv: Sequence[str] | None = None) -> int:
    # Briefs and questions carry ₹: never let a Windows console's code page stop the report.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
    return asyncio.run(run(argv))


if __name__ == "__main__":
    sys.exit(main())
