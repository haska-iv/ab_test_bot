"""
Sample size calculation for A/B tests.
Supports proportion and continuous metrics.
"""

from dataclasses import dataclass
from typing import Optional
import math


@dataclass
class SampleSizeResult:
    mde: float
    sample_per_variant: int
    total_sample: int
    days_needed: float
    power: float
    alpha: float


def proportion_effect_size(p1: float, p2: float) -> float:
    """Cohen's h for two proportions."""
    return 2 * math.asin(math.sqrt(p2)) - 2 * math.asin(math.sqrt(p1))


def normal_ppf(p: float) -> float:
    """Percent point function of standard normal (approximation)."""
    # Rational approximation (Abramowitz & Stegun)
    a = [2.515517, 0.802853, 0.010328]
    b = [1.432788, 0.189269, 0.001308]
    if p < 0.5:
        t = math.sqrt(-2 * math.log(p))
    else:
        t = math.sqrt(-2 * math.log(1 - p))
    num = a[0] + a[1] * t + a[2] * t ** 2
    den = 1 + b[0] * t + b[1] * t ** 2 + b[2] * t ** 3
    result = t - num / den
    return result if p >= 0.5 else -result


def calculate_sample_size_proportion(
    baseline: float,
    mde_relative: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> int:
    """
    Sample size per variant for a proportion metric.

    Args:
        baseline:     baseline conversion rate, e.g. 0.05
        mde_relative: minimum detectable effect as relative lift, e.g. 0.10 for +10%
        alpha:        significance level (two-sided)
        power:        desired statistical power

    Returns:
        Required sample size per variant.
    """
    p1 = baseline
    p2 = baseline * (1 + mde_relative)
    p2 = min(p2, 0.9999)

    effect_size = abs(proportion_effect_size(p1, p2))

    z_alpha = normal_ppf(1 - alpha / 2)
    z_beta = normal_ppf(power)

    n = ((z_alpha + z_beta) / effect_size) ** 2
    return math.ceil(n)


def calculate_sample_size_continuous(
    mean: float,
    std: float,
    mde_absolute: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> int:
    """
    Sample size per variant for a continuous metric (t-test, Welch).

    Args:
        mean:         baseline mean
        std:          baseline standard deviation
        mde_absolute: minimum detectable absolute difference
        alpha:        significance level (two-sided)
        power:        desired statistical power

    Returns:
        Required sample size per variant.
    """
    z_alpha = normal_ppf(1 - alpha / 2)
    z_beta = normal_ppf(power)

    n = 2 * ((z_alpha + z_beta) * std / mde_absolute) ** 2
    return math.ceil(n)


def build_mde_table(
    baseline: float,
    daily_users: int,
    alpha: float = 0.05,
    power: float = 0.80,
    mde_range: Optional[list] = None,
    split: float = 0.5,
) -> list[dict]:
    """
    Build a table: for each MDE, how many days are needed.

    Args:
        baseline:    baseline conversion rate
        daily_users: daily unique users eligible for the test
        alpha:       significance level
        power:       desired power
        mde_range:   list of relative MDE values to evaluate
        split:       traffic fraction per variant (0.5 = 50/50)

    Returns:
        List of dicts with mde, n_per_variant, total_n, days_needed.
    """
    if mde_range is None:
        mde_range = [0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30]

    results = []
    users_per_variant_per_day = daily_users * split

    for mde in mde_range:
        n = calculate_sample_size_proportion(baseline, mde, alpha, power)
        days = n / users_per_variant_per_day
        results.append({
            "mde_pct": round(mde * 100, 1),
            "n_per_variant": n,
            "total_n": n * round(1 / split),
            "days_needed": math.ceil(days),
            "weeks_needed": round(days / 7, 1),
        })

    return results


def format_mde_table(rows: list[dict]) -> str:
    """Format MDE table as a plain-text table for Slack."""
    header = f"{'MDE':>6} | {'n/variant':>10} | {'Days':>6} | {'Weeks':>6}"
    sep = "-" * len(header)
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"{r['mde_pct']:>5}% | {r['n_per_variant']:>10,} | {r['days_needed']:>6} | {r['weeks_needed']:>6}"
        )
    return "\n".join(lines)
