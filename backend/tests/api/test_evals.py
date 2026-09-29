"""`GET /api/evals/latest` serves the latest eval report for the dashboard (SPEC §9.1, ADR 0069):
the `latest.json` that `make eval` writes, as `EvalReport`, and 404 before any run."""

import json
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient

from promopilot.api.evals import EvalReportService
from promopilot.api.main import create_app
from promopilot.evals.report import write_report
from tests.api.test_health import FakeDatabaseProbe, FakeModelStatus
from tests.evals.test_report import REPORT
from tests.offline import offline_sessions


async def get_latest(directory: Path) -> tuple[int, Any]:
    app = create_app(
        database_probe=FakeDatabaseProbe(healthy=True),
        model_status=FakeModelStatus(loaded=True),
        sessions=offline_sessions(),
        evals=EvalReportService(directory),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/evals/latest")
    return response.status_code, response.json()


async def test_the_latest_report_is_served_as_make_eval_wrote_it(tmp_path: Path) -> None:
    paths = write_report(REPORT, tmp_path)

    status, body = await get_latest(tmp_path)

    assert status == 200
    assert body == json.loads(paths.latest_json.read_text(encoding="utf-8"))
    assert body["scenarios"][0]["runs"][0]["violations"][0]["code"] == "BUDGET"


async def test_a_newer_run_is_served_at_once(tmp_path: Path) -> None:
    write_report(REPORT, tmp_path)
    await get_latest(tmp_path)
    write_report(REPORT.model_copy(update={"world_seed": 7}), tmp_path)

    _, body = await get_latest(tmp_path)

    assert body["world_seed"] == 7


async def test_before_any_run_it_is_404_saying_to_run_make_eval(tmp_path: Path) -> None:
    for directory in (tmp_path, tmp_path / "never-written"):
        status, body = await get_latest(directory)

        assert status == 404
        assert body["detail"] == "No eval report yet: run `make eval`."
        assert body["code"] == "not_found"


async def test_a_report_this_version_cannot_read_is_404_saying_to_run_make_eval_again(
    tmp_path: Path,
) -> None:
    for written in ('{"provider": "replay", "world_seed": 42}', "not json"):
        (tmp_path / "latest.json").write_text(written, encoding="utf-8")

        status, body = await get_latest(tmp_path)

        assert status == 404
        assert body["detail"] == (
            "The latest eval report was written by another version of PromoPilot: "
            "run `make eval` again."
        )
        assert body["code"] == "not_found"


def test_the_contract_serves_the_eval_report_and_documents_the_404(tmp_path: Path) -> None:
    app = create_app(
        database_probe=FakeDatabaseProbe(healthy=True),
        model_status=FakeModelStatus(loaded=True),
        sessions=offline_sessions(),
        evals=EvalReportService(tmp_path),
    )

    operation = app.openapi()["paths"]["/api/evals/latest"]["get"]

    ok = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/EvalReport"}
    assert "404" in operation["responses"]
