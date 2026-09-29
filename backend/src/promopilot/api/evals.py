"""The latest eval report over HTTP, for the `/evals` dashboard (SPEC §9.1, §12.3, ADR 0069).

`GET /api/evals/latest` serves the `latest.json` that `make eval` writes into `EVAL_REPORT_DIR`,
read on every request so a new run shows at once, as `EvalReport` itself (ADR 0056 D10). Before
any run it is 404; so is a report this version cannot read, such as one written before the
report changed shape, with its own detail.
"""

from pathlib import Path

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError

from promopilot.evals.report import EvalReport

log = structlog.get_logger(__name__)

NO_REPORT = "No eval report yet: run `make eval`."
UNREADABLE_REPORT = (
    "The latest eval report was written by another version of PromoPilot: run `make eval` again."
)


class NoEvalReportError(Exception):
    """There is no latest eval report this version can serve; the message says why."""


class EvalReportService:
    """The eval reports `make eval` writes into one folder."""

    def __init__(self, directory: Path) -> None:
        self._latest = directory / "latest.json"

    def latest(self) -> EvalReport:
        try:
            text = self._latest.read_text(encoding="utf-8")
        except FileNotFoundError as missing:
            raise NoEvalReportError(NO_REPORT) from missing
        try:
            return EvalReport.model_validate_json(text)
        except ValidationError as unreadable:
            log.warning(
                "evals.latest_unreadable", path=str(self._latest), errors=unreadable.error_count()
            )
            raise NoEvalReportError(UNREADABLE_REPORT) from unreadable


def evals_router(service: EvalReportService) -> APIRouter:
    router = APIRouter(prefix="/api/evals", tags=["evals"])

    @router.get(
        "/latest",
        responses={
            status.HTTP_404_NOT_FOUND: {"description": "No eval report this version can read"}
        },
    )
    async def latest() -> EvalReport:
        try:
            return service.latest()
        except NoEvalReportError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error

    return router
