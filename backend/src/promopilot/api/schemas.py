"""Request/response schemas: the OpenAPI contract consumed by the frontend."""

from typing import Literal

from pydantic import BaseModel


class HealthChecks(BaseModel):
    database: Literal["ok", "error"]
    model_registry: Literal["not_initialised"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: HealthChecks
