"""Hidden ground truth and the true demand function (SPEC §8.3, ADR 0003).

Only promopilot.datagen and promopilot.evals may import this module (SPEC §13.4).

For SKU i, store s, week t, segment g:

    log E[units] = base_level_i + store_level_s + log segment_mix_s,g + affinity_cat(i),g
                 + season_i(t) + holiday_sensitivity_cat(i),h(t) * intensity_r(t)
                 + beta_i,g * log(p_i,t,g / p_ref_i)
                 + gamma_i * log(cp_i,r,t / p_i,t,g)
                 + sum_j theta_ij * log(p_j,t,g / p_ref_j)
                 + mu_i,mechanism(t,g)
                 - phi_i * (share of the previous k weeks on promotion for segment g)
    units ~ NegativeBinomial(mean, dispersion_i)
"""

from collections.abc import Sequence
from datetime import date

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict

from promopilot.domain import Mechanism, Region, Segment

SEGMENTS: list[Segment] = list(Segment)
MECHANISMS: list[Mechanism] = list(Mechanism)
"""Mechanism codes used in scenario arrays: the index in this list; -1 means no promotion."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SkuTruth(_Frozen):
    sku_id: str
    category: str
    subcategory: str
    reference_price: float
    base_level: float
    season_amplitude: float
    season_phase_week: float
    elasticity: dict[Segment, float]
    competitor_sensitivity: float
    mechanism_effect: dict[Mechanism, float]
    pull_forward: float
    dispersion: float


class StoreTruth(_Frozen):
    store_id: str
    region: Region
    level: float
    segment_mix: dict[Segment, float]


class CrossEffect(_Frozen):
    """theta: the effect of other_sku_id's log price ratio on sku_id's log units."""

    sku_id: str
    other_sku_id: str
    theta: float


class HolidayWeek(_Frozen):
    name: str | None
    intensity: float


class GroundTruth(_Frozen):
    start_date: date
    history_weeks: int
    horizon_weeks: int
    pull_forward_window_weeks: int
    skus: list[SkuTruth]
    stores: list[StoreTruth]
    segment_affinity: dict[str, dict[Segment, float]]
    holiday_sensitivity: dict[str, dict[str, float]]
    holidays: dict[Region, list[HolidayWeek]]
    competitor_prices: dict[Region, dict[str, list[float]]]
    """Per region and SKU, one price per week over history and horizon."""
    cross_effects: list[CrossEffect]
    substitute_pairs: list[tuple[str, str]]
    complement_pairs: list[tuple[str, str]]

    @property
    def total_weeks(self) -> int:
        return self.history_weeks + self.horizon_weeks


Array = NDArray[np.float64]


class TrueDemand:
    """Expected units under the true demand function, vectorised over a region.

    Scenario arrays have shape (weeks, segments, skus), in SEGMENTS and `sku_ids` order:
    `prices` is the unit price each segment pays; `mechanisms` holds a MECHANISMS index
    where a promotion's mechanism effect applies, else -1. A SKU-segment counts as promoted
    (for the pull-forward dip) when its mechanism is set or its price is below reference.
    """

    def __init__(self, truth: GroundTruth) -> None:
        self.truth = truth
        skus = truth.skus
        self.sku_ids = [sku.sku_id for sku in skus]
        self.reference_prices: Array = np.array([sku.reference_price for sku in skus])
        index = self._index = {sku_id: i for i, sku_id in enumerate(self.sku_ids)}
        n = len(skus)
        self._base = np.array([sku.base_level for sku in skus])
        self._affinity = np.array(
            [[truth.segment_affinity[sku.category][g] for g in SEGMENTS] for sku in skus]
        ).T  # (G, N)
        self._amplitude = np.array([sku.season_amplitude for sku in skus])
        self._phase = np.array([sku.season_phase_week for sku in skus])
        self._beta = np.array([[sku.elasticity[g] for g in SEGMENTS] for sku in skus]).T
        self._gamma = np.array([sku.competitor_sensitivity for sku in skus])
        self._mu = np.array([[sku.mechanism_effect[m] for m in MECHANISMS] for sku in skus])
        self._phi = np.array([sku.pull_forward for sku in skus])
        self._theta = np.zeros((n, n))
        for effect in truth.cross_effects:
            self._theta[index[effect.sku_id], index[effect.other_sku_id]] = effect.theta
        categories = [sku.category for sku in skus]
        self._holiday_lift = {
            region: np.array(
                [
                    [
                        truth.holiday_sensitivity[c].get(week.name, 0.0) * week.intensity
                        if week.name
                        else 0.0
                        for c in categories
                    ]
                    for week in weeks
                ]
            )
            for region, weeks in truth.holidays.items()
        }  # region -> (T, N)
        self._competitor = {
            region: np.array([by_sku[sku_id] for sku_id in self.sku_ids]).T
            for region, by_sku in truth.competitor_prices.items()
        }  # region -> (T, N)
        self._stores = {
            region: [store for store in truth.stores if store.region is region]
            for region in truth.holidays
        }
        self.dispersion: Array = np.array([sku.dispersion for sku in skus])

    def store_ids(self, region: Region) -> list[str]:
        return [store.store_id for store in self._stores[region]]

    def expected_units(
        self,
        region: Region,
        start_week: int,
        prices: Array,
        mechanisms: NDArray[np.int_],
        promoted_before: NDArray[np.bool_] | None = None,
        *,
        sku_ids: Sequence[str] | None = None,
    ) -> Array:
        """Expected units, shape (stores in region, weeks, segments, skus).

        `promoted_before` (k, segments, skus) marks promotions in the k weeks before
        `start_week`; by default none. With `sku_ids`, the SKU axis of every array holds only
        those SKUs, in that order: every other SKU is at its reference price and unpromoted,
        so it moves none of them.
        """
        at = slice(None) if sku_ids is None else [self._index[sku_id] for sku_id in sku_ids]
        weeks = prices.shape[0]
        if start_week < 0 or start_week + weeks > self.truth.total_weeks:
            raise ValueError(
                f"weeks {start_week}..{start_week + weeks - 1} fall outside the generated "
                f"timeline 0..{self.truth.total_weeks - 1}"
            )
        span = slice(start_week, start_week + weeks)
        t = np.arange(start_week, start_week + weeks)[:, None]  # (W, 1)
        reference = self.reference_prices[at]
        log_ratio = np.log(prices / reference)  # (W, G, N)
        competitor = self._competitor[region][span][:, at][:, None, :]  # (W, 1, N)

        time_effect = (
            self._amplitude[at] * np.sin(2 * np.pi * (t - self._phase[at]) / 52.0)
            + self._holiday_lift[region][span][:, at]
        )  # (W, N)
        log_mean = (
            time_effect[:, None, :]
            + self._beta[:, at] * log_ratio
            + self._gamma[at] * np.log(competitor / prices)
            + log_ratio @ self._theta[at][:, at].T
            + self._mechanism_effect(mechanisms, self._mu[at])
            - self._phi[at]
            * self._pull_forward_share(prices, mechanisms, promoted_before, reference)
        )  # (W, G, N)
        stores = self._stores[region]
        store_level = np.array([store.level for store in stores])[:, None]  # (S, 1)
        mix = np.log(np.array([[store.segment_mix[g] for g in SEGMENTS] for store in stores]))
        static = self._base[at] + store_level[:, :, None] + mix[:, :, None] + self._affinity[:, at]
        return np.asarray(np.exp(static[:, None, :, :] + log_mean[None, ...]))  # (S, W, G, N)

    @staticmethod
    def _mechanism_effect(mechanisms: NDArray[np.int_], mu: Array) -> Array:
        effect = np.zeros(mechanisms.shape)
        promoted = mechanisms >= 0
        sku = np.broadcast_to(np.arange(mechanisms.shape[-1]), mechanisms.shape)
        effect[promoted] = mu[sku[promoted], mechanisms[promoted]]
        return effect

    def _pull_forward_share(
        self,
        prices: Array,
        mechanisms: NDArray[np.int_],
        promoted_before: NDArray[np.bool_] | None,
        reference: Array,
    ) -> Array:
        k = self.truth.pull_forward_window_weeks
        promoted = (mechanisms >= 0) | (prices < reference - 1e-9)
        history = np.zeros((k, *promoted.shape[1:]), dtype=bool)
        if promoted_before is not None:
            recent = promoted_before[-k:]
            history[k - recent.shape[0] :] = recent
        timeline = np.concatenate([history, promoted]).astype(float)
        window = np.cumsum(np.concatenate([np.zeros((1, *promoted.shape[1:])), timeline]), axis=0)
        weeks = promoted.shape[0]
        # For week w (timeline index k + w): promoted weeks among timeline[w : k + w].
        return np.asarray((window[k : k + weeks] - window[:weeks]) / k)
