"""
Statistical power analysis for A/B tests.
No external dependencies — pure Python math.
"""

import math


def _normal_ppf(p: float) -> float:
    """Percent point function of standard normal (Abramowitz & Stegun approximation)."""
    a = [2.515517, 0.802853, 0.010328]
    b = [1.432788, 0.189269, 0.001308]
    q = p if p >= 0.5 else 1 - p
    t = math.sqrt(-2 * math.log(1 - q))
    num = a[0] + a[1] * t + a[2] * t ** 2
    den = 1 + b[0] * t + b[1] * t ** 2 + b[2] * t ** 3
    z = t - num / den
    return z if p >= 0.5 else -z


def _n_per_variant_z(baseline: float, uplift: float, alpha: float = 0.05, power: float = 0.80) -> int:
    """Sample size per variant for a proportion metric (two-sided z-test)."""
    p2 = min(baseline + uplift, 0.9999)
    effect = abs(2 * math.asin(math.sqrt(p2)) - 2 * math.asin(math.sqrt(baseline)))
    if effect == 0:
        return 999_999
    z = (_normal_ppf(1 - alpha / 2) + _normal_ppf(power)) / effect
    return math.ceil(z ** 2)


def _n_per_variant_mw(baseline: float, std: float, uplift: float, alpha: float = 0.05, power: float = 0.80) -> int:
    """Sample size per variant for a continuous metric (Mann-Whitney approximation via t-test)."""
    if uplift == 0:
        return 999_999
    z_sum = _normal_ppf(1 - alpha / 2) + _normal_ppf(power)
    n = 2 * (z_sum * std / uplift) ** 2
    return math.ceil(n)


def run_power_analysis(
    metric_id: str,
    baseline: float,
    expected_uplift: float,
    segment_size: int,
    n_variants: int,
    stat_test: str,
    weekly_rate: int | None = None,
    alpha: float = 0.05,
    power: float = 0.80,
) -> dict:
    """
    Build MDE table at 5 uplift levels (0.5x, 1x, 1.5x, 2x, 3x of expected_uplift).
    Returns table rows + overall verdict.
    """
    users_per_variant = segment_size // n_variants
    std = math.sqrt(baseline * (1 - baseline)) if stat_test == "z_test" else baseline * 0.5  # rough std for continuous

    uplift_multipliers = [0.5, 1.0, 1.5, 2.0, 3.0]
    rows = []

    for mult in uplift_multipliers:
        uplift = expected_uplift * mult

        if stat_test == "z_test":
            n_needed = _n_per_variant_z(baseline, uplift, alpha, power)
        else:
            n_needed = _n_per_variant_mw(baseline, std, uplift, alpha, power)

        if weekly_rate and weekly_rate > 0:
            weeks = math.ceil(n_needed / (weekly_rate / n_variants))
        else:
            weeks = math.ceil(n_needed / (users_per_variant / 4)) if users_per_variant else 999

        rows.append({
            "uplift_mult": f"{mult}x",
            "absolute_uplift": round(uplift, 4),
            "n_per_variant": n_needed,
            "total_n": n_needed * n_variants,
            "feasible": n_needed <= users_per_variant,
            "weeks_needed": weeks,
        })

    # Verdict based on expected uplift (1x row)
    base_row = rows[1]
    if base_row["feasible"]:
        verdict = "feasible"
    elif rows[2]["feasible"]:
        verdict = "borderline"
    else:
        verdict = "underpowered"

    return {
        "mde_table": rows,
        "verdict": verdict,
        "required_n_per_variant": base_row["n_per_variant"],
        "available_n_per_variant": users_per_variant,
        "metric_id": metric_id,
    }
