"""Data access: the Postgres schema, the Parquet loader and as-of-week repositories."""

from promopilot.data.loader import load_dataset, migrate
from promopilot.data.retail import RetailData

__all__ = ["RetailData", "load_dataset", "migrate"]
