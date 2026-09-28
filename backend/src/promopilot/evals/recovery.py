"""Model-recovery metrics (SPEC §12.2, ADR 0064): how close the fitted models come to the
ground truth the world was generated with.

They read the eval world's own fit at its default as-of week, the first week after the
history: the models `make train` registers for the same world and seed (ADR 0056 D4). They run
once per report, whatever the scenarios.

- **Elasticity recovery**: the median of |estimate - truth| / |truth| of the own-price
  elasticity over every SKU x segment; target ≤ 20%.
- **Substitute and complement detection**: precision and recall of the pairs the relations
  model keeps, as unordered pairs across the catalogue, against every true pair; targets
  ≥ 0.8 and ≥ 0.7.
- **Baseline WAPE**: the demand model's own 12-week holdout WAPE at its three grains
  (ADR 0023); reported, aiming for ≤ 25%.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from promopilot.evals.report import Metric
from promopilot.evals.world import EvalWorld
from promopilot.models.demand import WAPE_GRAINS
from promopilot.models.relations import Relations

ELASTICITY_TARGET = 0.20
PRECISION_TARGET = 0.8
RECALL_TARGET = 0.7
WAPE_AIM = 0.25

Pair = tuple[str, str]
Relation = Literal["substitute", "complement"]

WAPE_LABELS = {
    "": "Baseline WAPE, store x SKU x segment",
    "_store_sku": "Baseline WAPE, store x SKU",
    "_region_sku": "Baseline WAPE, region x SKU",
}
"""The grain each holdout WAPE is summed to, per `WAPE_GRAINS` suffix (ADR 0023)."""


async def recovery_metrics(world: EvalWorld) -> tuple[Metric, ...]:
    """Every model-recovery metric, for the models fitted as of the world's default week.

    Fits them if no scenario did; a fit that fails raises.
    """
    fitted = await world.fitted(world.default_as_of_week)
    truth = world.ground_truth
    coefficients = fitted.demand.coefficients()
    beta = coefficients[coefficients["parameter"] == "beta"]
    estimated = {
        (str(sku), str(level)): float(value)
        for sku, level, value in beta[["sku_id", "level", "estimate"]].itertuples(index=False)
    }
    true = {
        (sku.sku_id, segment.value): value
        for sku in truth.skus
        for segment, value in sku.elasticity.items()
    }
    sku_ids = [sku.sku_id for sku in truth.skus]
    return (
        elasticity_recovery(estimated, true),
        *detection(
            "substitute",
            _detected(fitted.relations, sku_ids, "substitute"),
            set(truth.substitute_pairs),
        ),
        *detection(
            "complement",
            _detected(fitted.relations, sku_ids, "complement"),
            set(truth.complement_pairs),
        ),
        *baseline_wape(fitted.demand.metrics),
    )


def median_abs_pct_error(estimated: Sequence[float], true: Sequence[float]) -> float:
    """The median of |estimated - true| / |true|. Raises ValueError for a zero truth."""
    truth = np.asarray(true, dtype=float)
    if np.any(truth == 0):
        raise ValueError("a percentage error against a zero truth is undefined")
    return float(np.median(_abs_pct_errors(np.asarray(estimated, dtype=float), truth)))


def elasticity_recovery(
    estimated: Mapping[tuple[str, str], float], true: Mapping[tuple[str, str], float]
) -> Metric:
    """Own-price elasticity recovery over every true (SKU, segment): the median absolute %
    error, with how many are within the target. A true elasticity with no estimate raises."""
    missing = sorted(key for key in true if key not in estimated)
    if missing:
        raise ValueError(f"no estimated elasticity for {missing[:5]}")
    keys = list(true)
    truth = [true[key] for key in keys]
    guesses = [estimated[key] for key in keys]
    value = median_abs_pct_error(guesses, truth) if keys else None
    within = int(
        np.sum(
            _abs_pct_errors(np.asarray(guesses, dtype=float), np.asarray(truth, dtype=float))
            <= ELASTICITY_TARGET
        )
    )
    return Metric(
        name="elasticity_recovery",
        label="Elasticity recovery (median abs % error)",
        value=value,
        count=within,
        of=len(keys),
        target=ELASTICITY_TARGET,
        direction="at_most",
        passed=None if value is None else value <= ELASTICITY_TARGET,
    )


def precision_recall(
    found: Iterable[Pair], true: Iterable[Pair]
) -> tuple[float | None, float | None]:
    """Precision over the found pairs and recall over the true ones; pairs are unordered.
    Either is None with nothing to divide by."""
    found_pairs, true_pairs = _unordered(found), _unordered(true)
    hits = len(found_pairs & true_pairs)
    return _share(hits, len(found_pairs)), _share(hits, len(true_pairs))


def detection(
    relation: Relation, found: Iterable[Pair], true: Iterable[Pair]
) -> tuple[Metric, Metric]:
    """Precision and recall of the detected pairs of one relation, each against its target."""
    found_pairs, true_pairs = _unordered(found), _unordered(true)
    hits = len(found_pairs & true_pairs)
    precision, recall = precision_recall(found_pairs, true_pairs)
    title = relation.capitalize()
    return (
        _at_least(
            f"{relation}_precision",
            f"{title} precision",
            precision,
            hits,
            len(found_pairs),
            PRECISION_TARGET,
        ),
        _at_least(
            f"{relation}_recall", f"{title} recall", recall, hits, len(true_pairs), RECALL_TARGET
        ),
    )


def baseline_wape(metrics: Mapping[str, float]) -> tuple[Metric, ...]:
    """The demand model's 12-week holdout WAPE at each grain (ADR 0023): reported, with an
    aim of at most 25%. A model missing one raises KeyError."""
    return tuple(
        Metric(
            name=f"baseline_wape{suffix}",
            label=WAPE_LABELS[suffix],
            value=float(metrics[f"baseline_wape{suffix}"]),
            count=0,
            of=0,
            direction="at_most",
            aim=WAPE_AIM,
        )
        for suffix in WAPE_GRAINS
    )


def _detected(relations: Relations, sku_ids: Sequence[str], relation: Relation) -> set[Pair]:
    """Every pair the relations model keeps, catalogue-wide."""
    partners = relations.substitutes if relation == "substitute" else relations.complements
    return _unordered(
        (sku_id, str(other)) for sku_id in sku_ids for other in partners(sku_id)["sku_id"]
    )


def _unordered(pairs: Iterable[Pair]) -> set[Pair]:
    return {(min(a, b), max(a, b)) for a, b in pairs}


def _abs_pct_errors(
    estimated: NDArray[np.float64], true: NDArray[np.float64]
) -> NDArray[np.float64]:
    return np.asarray(np.abs(estimated - true) / np.abs(true), dtype=np.float64)


def _at_least(
    name: str, label: str, value: float | None, count: int, of: int, target: float
) -> Metric:
    return Metric(
        name=name,
        label=label,
        value=value,
        count=count,
        of=of,
        target=target,
        direction="at_least",
        passed=None if value is None else value >= target,
    )


def _share(count: int, of: int) -> float | None:
    return None if of == 0 else count / of
