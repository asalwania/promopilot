"""Print the OpenAPI document (the frontend contract): `python -m promopilot.api.openapi`."""

import json
import sys

from promopilot.api.main import create_app


class _UnusedProbe:
    async def is_healthy(self) -> bool:
        return False


def main() -> None:
    app = create_app(database_probe=_UnusedProbe())
    document = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    # Write bytes so Windows doesn't emit CRLF; CI diffs this file on Linux.
    sys.stdout.buffer.write(document.encode())


if __name__ == "__main__":
    main()
