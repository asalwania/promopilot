"""Competitor gaps over HTTP: `GET /api/competitors/gaps` (SPEC §10, ADR 0031).

A person may look at any as-of week; it defaults to the data's default as-of week (ADR 0008).
"""

from typing import Annotated, Protocol

from fastapi import APIRouter, HTTPException, Query, status

from promopilot.competitors import CompetitorData, CompetitorGaps, read_competitor_gaps
from promopilot.domain import CompanyPolicy, Region


class CompetitorSource(CompetitorData, Protocol):
    """`promopilot.data.RetailData`: the repositories plus the default as-of week."""

    async def default_as_of_week(self) -> int: ...


class NoDataError(Exception):
    """No data is loaded to find the default as-of week."""


class CompetitorService:
    def __init__(self, data: CompetitorSource, *, policy: CompanyPolicy) -> None:
        self._data = data
        self._policy = policy

    async def gaps(
        self,
        *,
        as_of_week: int | None = None,
        region: Region | None = None,
        category: str | None = None,
        kvi_only: bool = False,
    ) -> CompetitorGaps:
        """Raises `NoDataError` without data, `ValueError` for an unknown category."""
        if as_of_week is None:
            try:
                as_of_week = await self._data.default_as_of_week()
            except LookupError as error:
                raise NoDataError(str(error)) from error
        return await read_competitor_gaps(
            self._data,
            as_of_week=as_of_week,
            policy=self._policy,
            regions=None if region is None else [region],
            categories=None if category is None else [category],
            kvi_only=kvi_only,
        )


def competitors_router(competitors: CompetitorService) -> APIRouter:
    router = APIRouter(prefix="/api/competitors", tags=["competitors"])

    @router.get(
        "/gaps",
        responses={status.HTTP_409_CONFLICT: {"description": "No data is loaded"}},
    )
    async def competitor_gaps(
        as_of_week: Annotated[
            int | None, Query(ge=0, description="Defaults to the data's default as-of week.")
        ] = None,
        region: Region | None = None,
        category: str | None = None,
        kvi_only: bool = False,
    ) -> CompetitorGaps:
        """Competitor price index, gap and KVI undercut per SKU x region, widest gap first.

        An unknown category is 422.
        """
        try:
            return await competitors.gaps(
                as_of_week=as_of_week, region=region, category=category, kvi_only=kvi_only
            )
        except NoDataError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    return router
