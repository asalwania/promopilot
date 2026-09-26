"""Print the OpenAPI document (the frontend contract): `python -m promopilot.api.openapi`."""

import json
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from promopilot.api.main import create_app
from promopilot.api.sessions import SessionService
from promopilot.data import RetailData, SessionStore
from promopilot.llm import FakeProvider


class _UnusedProbe:
    async def is_healthy(self) -> bool:
        return False


def main() -> None:
    engine = create_async_engine("postgresql+asyncpg://unused@127.0.0.1:1/unused")  # never connects
    sessions = SessionService(
        store=SessionStore(engine), data=RetailData(engine), llm=FakeProvider([])
    )
    app = create_app(database_probe=_UnusedProbe(), sessions=sessions)
    document = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    # Write bytes so Windows doesn't emit CRLF; CI diffs this file on Linux.
    sys.stdout.buffer.write(document.encode())


if __name__ == "__main__":
    main()
