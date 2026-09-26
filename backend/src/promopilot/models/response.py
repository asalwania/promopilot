"""The promo response model (SPEC §9.1, stage two): what a promotion does beyond baseline.

Per SKU, a Poisson GLM on region x segment x week unit totals estimates

    log E[units] = log baseline + alpha
                 + beta_g * log(p / p_ref)        own-price elasticity, per segment g
                 + gamma * log(cp / p)            competitor sensitivity
                 + mu_m * [mechanism m]           mechanism effect beyond price
                 - phi * pull_forward_share       post-promo dip

where the baseline is forecast with the competitor price index at 1 (cp = p_ref). Our own
price appears in both the beta and the gamma term, so gamma is identified by competitor
price moves and beta is recovered directly rather than as beta - gamma (ADR 0016).
Standard errors are heteroskedasticity-robust, since units are overdispersed.

Empirical Bayes then shrinks every per-SKU estimate toward its subcategory mean (beta per
segment, mu per mechanism), with the between-SKU variance pooled over subcategories; a
term a SKU's history never exercised takes the subcategory mean. The posterior standard
deviation is the reported standard error (ADR 0024). The shrunk pull-forward phi is floored
at 0: a promotion never lifts demand in the weeks after it (ADR 0037).
"""

import warnings
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm

from promopilot.domain import Mechanism, Segment

SEGMENTS = [segment.value for segment in Segment]
MECHANISMS = [mechanism.value for mechanism in Mechanism]
TERMS: list[tuple[str, str | None]] = [
    ("alpha", None),
    *[("beta", segment) for segment in SEGMENTS],
    ("gamma", None),
    *[("mu", mechanism) for mechanism in MECHANISMS],
    ("phi", None),
]
"""(parameter, level) for every term; beta's level is a segment, mu's a mechanism."""
UNSHRUNK = {"alpha"}
"""alpha only recalibrates the baseline for its SKU; it has no subcategory prior."""
NON_NEGATIVE = {"phi"}
"""Terms whose sign the demand function fixes: the pull-forward dip is never a lift."""

ROW_COLUMNS = [
    "sku_id",
    "segment",
    "log_price_ratio",
    "log_competitor_ratio",
    "mechanism",
    "pull_forward_share",
]
"""What `log_effect` and `variance` read from each row; `mechanism` is None when none applies."""

TAU2_FLOOR = 1e-4
EB_ITERATIONS = 50
DISPERSION_BOUNDS = (0.5, 1_000.0)


def design(rows: pd.DataFrame) -> np.ndarray:
    """One column per term in TERMS order."""
    columns = []
    for parameter, level in TERMS:
        column: np.ndarray
        if parameter == "alpha":
            column = np.ones(len(rows))
        elif parameter == "beta":
            column = rows["log_price_ratio"].to_numpy() * (rows["segment"] == level).to_numpy()
        elif parameter == "gamma":
            column = rows["log_competitor_ratio"].to_numpy()
        elif parameter == "mu":
            column = (rows["mechanism"] == level).to_numpy()
        else:
            column = -rows["pull_forward_share"].to_numpy()
        columns.append(np.asarray(column, dtype=float))
    return np.column_stack(columns)


@dataclass(frozen=True)
class PromoResponse:
    coefficients: pd.DataFrame
    """sku_id, parameter, level, estimate, std_error: one row per SKU and term."""
    dispersion: pd.Series
    """Negative binomial size per SKU, for store-level demand noise."""
    fitted_skus: int
    """SKUs with enough promo history for a GLM; the rest take their subcategory means."""

    @classmethod
    def fit(cls, rows: pd.DataFrame, subcategories: Mapping[str, str]) -> "PromoResponse":
        """Fit on region-level rows: ROW_COLUMNS plus units, offset (log baseline) and
        baseline_sq (the sum of squared store baselines behind the offset)."""
        raw = []
        fitted = 0
        dispersion_terms = []
        for sku_id in subcategories:
            sku_rows = rows[rows["sku_id"] == sku_id]
            estimates, errors, fitted_log = _glm(sku_rows)
            fitted += fitted_log is not None
            raw.append((sku_id, estimates, errors))
            if fitted_log is not None:
                mean = np.exp(sku_rows["offset"].to_numpy() + fitted_log)
                excess = (sku_rows["units"].to_numpy() - mean) ** 2 - mean
                squares = np.exp(2 * fitted_log) * sku_rows["baseline_sq"].to_numpy()
                dispersion_terms.append((sku_id, squares.sum(), excess.sum()))
        coefficients = pd.DataFrame(
            [
                {
                    "sku_id": sku_id,
                    "parameter": parameter,
                    "level": level,
                    "estimate": estimates[k],
                    "std_error": errors[k],
                }
                for sku_id, estimates, errors in raw
                for k, (parameter, level) in enumerate(TERMS)
            ]
        )
        coefficients["subcategory"] = coefficients["sku_id"].map(subcategories)
        coefficients = _shrink(coefficients)
        return cls(
            coefficients=coefficients.drop(columns="subcategory"),
            dispersion=_dispersion(dispersion_terms, list(subcategories)),
            fitted_skus=fitted,
        )

    def log_effect(self, rows: pd.DataFrame) -> np.ndarray:
        """log(units / baseline) for each row."""
        return np.asarray((design(rows) * self._matrix("estimate", rows)).sum(axis=1))

    def variance(self, rows: pd.DataFrame, means: np.ndarray, groups: np.ndarray) -> np.ndarray:
        """Variance of the summed units of each group of store-level rows.

        Parameter uncertainty by the delta method, treating terms as independent normals
        (as the simulator samples them), plus negative binomial demand noise.
        """
        size = int(groups.max()) + 1 if len(groups) else 0
        noise = means + means**2 / self.dispersion.loc[rows["sku_id"]].to_numpy()
        pairs, pair_index = np.unique(
            np.column_stack([groups, pd.factorize(rows["sku_id"])[0]]), axis=0, return_inverse=True
        )
        gradient = np.zeros((len(pairs), len(TERMS)))
        np.add.at(gradient, pair_index.ravel(), design(rows) * means[:, None])
        first = np.unique(pair_index.ravel(), return_index=True)[1]
        errors = self._matrix("std_error", rows.iloc[first])
        parameter = ((gradient * errors) ** 2).sum(axis=1)
        return np.asarray(
            np.bincount(pairs[:, 0], weights=parameter, minlength=size)
            + np.bincount(groups, weights=noise, minlength=size)
        )

    def _matrix(self, column: str, rows: pd.DataFrame) -> np.ndarray:
        wide = self.coefficients.assign(
            term=self.coefficients["parameter"] + ":" + self.coefficients["level"].fillna("")
        ).pivot(index="sku_id", columns="term", values=column)
        wide = wide[[f"{parameter}:{level or ''}" for parameter, level in TERMS]]
        return np.asarray(wide.loc[rows["sku_id"]].to_numpy(dtype=float))


def _glm(rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Raw per-SKU estimates and robust standard errors; NaN for unexercised terms."""
    estimates = np.full(len(TERMS), np.nan)
    errors = np.full(len(TERMS), np.nan)
    matrix = design(rows)
    used = np.abs(matrix).sum(axis=0) > 0
    promoted = used[[parameter in {"beta", "mu"} for parameter, _ in TERMS]].any()
    if rows.empty or not promoted:
        return estimates, errors, None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = sm.GLM(
                rows["units"].to_numpy(dtype=float),
                matrix[:, used],
                family=sm.families.Poisson(),
                offset=rows["offset"].to_numpy(dtype=float),
            ).fit(cov_type="HC0")
    except (ValueError, np.linalg.LinAlgError):
        return estimates, errors, None
    estimates[used] = result.params
    errors[used] = result.bse
    return estimates, errors, np.asarray(matrix[:, used] @ result.params)


def _shrink(coefficients: pd.DataFrame) -> pd.DataFrame:
    shrunk = []
    for (parameter, _level), term in coefficients.groupby(
        ["parameter", "level"], dropna=False, sort=False
    ):
        if parameter in UNSHRUNK:
            shrunk.append(term.fillna({"estimate": 0.0, "std_error": 0.0}))
        else:
            shrunk.append(_empirical_bayes(term))
    result = pd.concat(shrunk).sort_index()
    floored = result["parameter"].isin(NON_NEGATIVE)
    result.loc[floored, "estimate"] = result.loc[floored, "estimate"].clip(lower=0.0)
    return result


def _empirical_bayes(term: pd.DataFrame) -> pd.DataFrame:
    """Normal-normal shrinkage toward the precision-weighted subcategory mean."""
    b = term["estimate"].to_numpy()
    s2 = term["std_error"].to_numpy() ** 2
    ok = np.isfinite(b) & np.isfinite(s2) & (s2 > 0)
    group = pd.factorize(term["subcategory"])[0]
    groups = group.max() + 1
    if not ok.any():
        return term.assign(estimate=0.0, std_error=np.sqrt(TAU2_FLOOR))
    tau2 = max(float(np.var(b[ok]) - np.mean(s2[ok])), TAU2_FLOOR)
    for _ in range(EB_ITERATIONS):
        w = np.where(ok, 1 / (s2 + tau2), 0.0)
        wb = np.where(ok, w * b, 0.0)
        total = np.bincount(group, weights=w, minlength=groups)
        overall = wb.sum() / w.sum()
        mean = np.where(
            total > 0,
            np.bincount(group, weights=wb, minlength=groups) / np.where(total > 0, total, 1),
            overall,
        )[group]
        mean_var = np.where(total > 0, 1 / np.where(total > 0, total, 1), 1 / w.sum())[group]
        # Deviations from an estimated group mean shrink by (1 - w / W): correct for that.
        kept = 1 - w / np.where(total > 0, total, 1)[group]
        use = ok & (kept > 1e-9)
        if not use.any():
            break
        excess = (b - mean) ** 2 / np.where(use, kept, 1) - s2
        updated = max(float((w * excess)[use].sum() / w[use].sum()), TAU2_FLOOR)
        converged = abs(updated - tau2) < 1e-10
        tau2 = updated
        if converged:
            break
    shrink = np.where(ok, s2 / np.where(ok, s2 + tau2, 1), 1.0)
    estimate = mean + (1 - shrink) * np.where(ok, b - mean, 0.0)
    variance = np.where(ok, (1 - shrink) * s2, tau2) + shrink**2 * mean_var
    return term.assign(estimate=estimate, std_error=np.sqrt(variance))


def _dispersion(terms: list[tuple[str, float, float]], sku_ids: list[str]) -> pd.Series:
    """Method of moments: Var = mean + mean^2 / size, pooled for SKUs without a fit."""
    frame = pd.DataFrame(terms, columns=["sku_id", "squares", "excess"]).set_index("sku_id")
    low, high = DISPERSION_BOUNDS
    pooled = (
        frame["squares"].sum() / frame["excess"].sum()
        if not frame.empty and frame["excess"].sum() > 0
        else high
    )
    size = frame["squares"] / frame["excess"].where(frame["excess"] > 0)
    size = size.reindex(sku_ids).fillna(pooled)
    return size.clip(low, high)
