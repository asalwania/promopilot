"""Enumerations and scalar types from the CONTEXT.md glossary."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field


class Region(StrEnum):
    NORTH = "North"
    SOUTH = "South"
    EAST = "East"
    WEST = "West"


class Segment(StrEnum):
    """A behavioural customer group; never defined by protected attributes."""

    VALUE_SEEKERS = "Value Seekers"
    FAMILIES = "Families"
    PREMIUM = "Premium"
    YOUNG_URBAN = "Young Urban"


class TargetSegment(StrEnum):
    """Who a plan line is offered to: one segment exclusively, or All customers (ADR 0006)."""

    VALUE_SEEKERS = "Value Seekers"
    FAMILIES = "Families"
    PREMIUM = "Premium"
    YOUNG_URBAN = "Young Urban"
    ALL_CUSTOMERS = "All customers"


class Mechanism(StrEnum):
    PCT_OFF = "PCT_OFF"
    BOGO = "BOGO"
    BUNDLE = "BUNDLE"
    FIXED_PRICE = "FIXED_PRICE"


Week = Annotated[int, Field(ge=0)]
"""A week id: 0 is the first week of generated history."""
