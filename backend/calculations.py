"""
calculations.py — Health Index, comparison, anomaly detection, projections.
All functions take already-fetched records — no re-fetching inside this file.
Uses only Python stdlib (statistics module). No scikit-learn, no numpy.
"""

import statistics
from collections import defaultdict
from typing import Any

# ---------------------------------------------------------------------------
# Health Index weight constants
# ---------------------------------------------------------------------------
W_BIODIVERSITY   = 0.35   # species richness contribution
W_TREND          = 0.25   # occurrence trend (recent vs older)
W_ANOMALY_STABLE = 0.20   # stability = inverse SST variance
W_CONFIDENCE     = 0.20   # data volume confidence score

MAX_SPECIES_BASELINE    = 200   # species count considered "full" biodiversity
MAX_RECORDS_BASELINE    = 1000  # record count considered "full" confidence
SST_VARIANCE_SCALE      = 5.0   # degrees² — variance at this level → stability 0

ANOMALY_STD_THRESHOLD   = 2.0   # flag if value is >N std deviations from mean

# Stressor multipliers for what-if projection
STRESSOR_EFFECTS = {
    "temperature_rise":    {"species_count": -0.03, "health_index": -0.025},
    "ocean_acidification": {"species_count": -0.025, "health_index": -0.02},
    "overfishing":         {"species_count": -0.04, "health_index": -0.035},
    "pollution":           {"species_count": -0.035, "health_index": -0.03},
    "habitat_loss":        {"species_count": -0.045, "health_index": -0.04},
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _aggregate(records: list[dict]) -> dict:
    """Compute summary stats from a list of occurrence records."""
    species = {r["scientificName"] for r in records if r.get("scientificName")}
    sst_vals = [r["sst"] for r in records if r.get("sst") is not None]
    return {
        "species_count": len(species),
        "occurrence_count": len(records),
        "avg_sst": round(statistics.mean(sst_vals), 2) if sst_vals else None,
        "sst_variance": round(statistics.variance(sst_vals), 4) if len(sst_vals) > 1 else 0.0,
        "species_list": sorted(species),
    }


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """
    Manual least-squares linear regression. Returns (slope, intercept).
    y = slope * x + intercept
    """
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    x_mean = statistics.mean(xs)
    y_mean = statistics.mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    slope = numerator / denominator if denominator != 0 else 0.0
    intercept = y_mean - slope * x_mean
    return slope, intercept


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def regional_health_index(
    records_recent: list[dict], records_older: list[dict]
) -> dict:
    """
    Compute a composite 0-100 Regional Health Index.
    Returns {"score": float, "components": {...}, "grade": str, "interpretation": str}
    """
    recent = _aggregate(records_recent)
    older  = _aggregate(records_older)

    # Biodiversity score (0-100)
    biodiversity_score = _clamp(
        (recent["species_count"] / MAX_SPECIES_BASELINE) * 100
    )

    # Trend score (0-100): based on % change in occurrences
    if older["occurrence_count"] > 0:
        pct_change = (
            (recent["occurrence_count"] - older["occurrence_count"])
            / older["occurrence_count"]
        ) * 100
    else:
        pct_change = 0.0
    # Map -50% → 0, 0% → 50, +50% → 100
    trend_score = _clamp(50 + pct_change)

    # Anomaly stability score (0-100): low SST variance = high stability
    sst_var = recent["sst_variance"]
    stability_score = _clamp(
        (1 - sst_var / SST_VARIANCE_SCALE) * 100
    )

    # Confidence score (0-100): based on record count
    confidence_score = _clamp(
        (recent["occurrence_count"] / MAX_RECORDS_BASELINE) * 100
    )

    composite = (
        W_BIODIVERSITY   * biodiversity_score
        + W_TREND          * trend_score
        + W_ANOMALY_STABLE * stability_score
        + W_CONFIDENCE     * confidence_score
    )
    composite = round(_clamp(composite), 1)

    grade = (
        "Excellent" if composite >= 80 else
        "Good"      if composite >= 60 else
        "Fair"      if composite >= 40 else
        "Poor"
    )

    interpretation = (
        f"Health score of {composite}/100 ({grade}). "
        f"{recent['species_count']} species recorded; "
        f"{'increasing' if pct_change >= 0 else 'decreasing'} trend "
        f"({pct_change:+.1f}% occurrence change). "
        f"SST variance: {sst_var:.2f}°C²."
    )

    return {
        "score": composite,
        "grade": grade,
        "interpretation": interpretation,
        "components": {
            "biodiversity":  round(biodiversity_score, 1),
            "trend":         round(trend_score, 1),
            "stability":     round(stability_score, 1),
            "confidence":    round(confidence_score, 1),
        },
        "recent_summary":  recent,
        "older_summary":   older,
    }


def _period_stats(records: list[dict]) -> dict:
    agg = _aggregate(records)
    return {
        "species_count":    agg["species_count"],
        "occurrence_count": agg["occurrence_count"],
        "avg_sst":          agg["avg_sst"],
    }


def compare_periods(records_a: list[dict], records_b: list[dict]) -> dict:
    """
    Compare two time periods for the same region.
    Returns stats for each period + deltas.
    """
    a = _period_stats(records_a)
    b = _period_stats(records_b)

    def delta(va, vb):
        if va is None or vb is None:
            return None
        return round(vb - va, 2)

    def pct(va, vb):
        if va is None or vb is None or va == 0:
            return None
        return round(((vb - va) / abs(va)) * 100, 1)

    return {
        "period_a": a,
        "period_b": b,
        "delta": {
            "species_count":    delta(a["species_count"],    b["species_count"]),
            "occurrence_count": delta(a["occurrence_count"], b["occurrence_count"]),
            "avg_sst":          delta(a["avg_sst"],          b["avg_sst"]),
        },
        "pct_change": {
            "species_count":    pct(a["species_count"],    b["species_count"]),
            "occurrence_count": pct(a["occurrence_count"], b["occurrence_count"]),
            "avg_sst":          pct(a["avg_sst"],          b["avg_sst"]),
        },
    }


def compare_regions(
    records_region_a: list[dict], records_region_b: list[dict]
) -> dict:
    """
    Compare two regions using the same aggregation as compare_periods.
    """
    return compare_periods(records_region_a, records_region_b)


def detect_anomalies(records: list[dict]) -> dict:
    """
    Flag SST and occurrence-density values beyond ANOMALY_STD_THRESHOLD std deviations.
    Returns {"flagged": [...], "sst_stats": {...}, "occurrence_stats": {...}}
    """
    flagged = []

    # --- SST anomaly detection ---
    sst_vals = [(r, r["sst"]) for r in records if r.get("sst") is not None]
    if len(sst_vals) >= 2:
        sst_numbers = [v for _, v in sst_vals]
        sst_mean = statistics.mean(sst_numbers)
        sst_std  = statistics.stdev(sst_numbers)
        sst_stats = {"mean": round(sst_mean, 2), "std": round(sst_std, 2)}
        for rec, sst in sst_vals:
            if sst_std > 0 and abs(sst - sst_mean) > ANOMALY_STD_THRESHOLD * sst_std:
                flagged.append({
                    "type": "SST",
                    "value": sst,
                    "date": rec.get("date", ""),
                    "lat": rec.get("lat"),
                    "lon": rec.get("lon"),
                    "species": rec.get("scientificName", ""),
                    "reason": (
                        f"SST {sst:.1f}°C is "
                        f"{abs(sst - sst_mean) / sst_std:.1f}σ from mean "
                        f"({sst_mean:.1f}°C)"
                    ),
                })
    else:
        sst_stats = {}

    # --- Occurrence density anomaly detection (records per year) ---
    year_counts: dict[int, int] = defaultdict(int)
    for r in records:
        if r.get("year"):
            year_counts[r["year"]] += 1

    if len(year_counts) >= 2:
        occ_numbers = list(year_counts.values())
        occ_mean = statistics.mean(occ_numbers)
        occ_std  = statistics.stdev(occ_numbers)
        occ_stats = {"mean": round(occ_mean, 2), "std": round(occ_std, 2)}
        for yr, cnt in year_counts.items():
            if occ_std > 0 and abs(cnt - occ_mean) > ANOMALY_STD_THRESHOLD * occ_std:
                flagged.append({
                    "type": "Occurrence density",
                    "value": cnt,
                    "date": str(yr),
                    "lat": None,
                    "lon": None,
                    "species": "",
                    "reason": (
                        f"{cnt} occurrences in {yr} is "
                        f"{abs(cnt - occ_mean) / occ_std:.1f}σ from mean "
                        f"({occ_mean:.1f}/year)"
                    ),
                })
    else:
        occ_stats = {}

    return {
        "flagged": flagged,
        "flagged_count": len(flagged),
        "sst_stats": sst_stats,
        "occurrence_stats": occ_stats,
    }


def project_scenario(
    records: list[dict],
    stressor_type: str,
    severity: float,
    target_year: int,
) -> dict:
    """
    Linear trend extrapolation adjusted by stressor severity.
    severity: 0.0–1.0 (0 = negligible, 1 = extreme).
    Returns projected species_count and health_index for target_year.
    """
    # Build annual data
    year_species: dict[int, set] = defaultdict(set)
    for r in records:
        yr = r.get("year")
        sp = r.get("scientificName")
        if yr and sp:
            year_species[yr].add(sp)

    if not year_species:
        return {"error": "Insufficient data for projection"}

    sorted_years = sorted(year_species.keys())
    xs = [float(y) for y in sorted_years]
    ys = [float(len(year_species[y])) for y in sorted_years]

    slope, intercept = _linear_regression(xs, ys)
    current_year = sorted_years[-1]
    years_ahead = target_year - current_year

    # Baseline linear projection
    baseline_projected = slope * target_year + intercept

    # Stressor effect — compound annual decline per year ahead
    effect = STRESSOR_EFFECTS.get(stressor_type, {"species_count": 0, "health_index": 0})
    stressor_multiplier = (1 + effect["species_count"] * severity) ** years_ahead
    adjusted_projected = max(0, baseline_projected * stressor_multiplier)

    # Rough health index projection (scale species count to 0-100 via baseline)
    current_species = len(year_species.get(current_year, set()))
    current_health_est = min(100, (current_species / 200) * 100)
    health_multiplier = (1 + effect["health_index"] * severity) ** years_ahead
    projected_health = max(0, current_health_est * health_multiplier)

    return {
        "current_year": current_year,
        "target_year": target_year,
        "stressor_type": stressor_type,
        "severity": severity,
        "current_species_count": current_species,
        "baseline_projected_species": round(baseline_projected, 1),
        "adjusted_projected_species": round(adjusted_projected, 1),
        "projected_health_index": round(projected_health, 1),
        "trend_slope": round(slope, 3),
        "years_ahead": years_ahead,
        "interpretation": (
            f"Under '{stressor_type}' at severity {severity:.0%}, "
            f"species count projected to change from {current_species} "
            f"(in {current_year}) to ~{round(adjusted_projected)} by {target_year}. "
            f"Estimated Health Index: {round(projected_health, 1)}/100."
        ),
    }


def timeseries(records: list[dict], metric: str) -> list[dict]:
    """
    Group records by year, return [{year, value}] for the chosen metric.
    metric: "species_count" | "occurrence_count" | "avg_sst"
    """
    year_species: dict[int, set] = defaultdict(set)
    year_records: dict[int, list] = defaultdict(list)

    for r in records:
        yr = r.get("year")
        if not yr:
            continue
        year_records[yr].append(r)
        sp = r.get("scientificName")
        if sp:
            year_species[yr].add(sp)

    result = []
    for yr in sorted(year_records.keys()):
        recs = year_records[yr]
        if metric == "species_count":
            value = len(year_species[yr])
        elif metric == "occurrence_count":
            value = len(recs)
        elif metric == "avg_sst":
            sst_vals = [r["sst"] for r in recs if r.get("sst") is not None]
            value = round(statistics.mean(sst_vals), 2) if sst_vals else None
        else:
            value = len(recs)

        result.append({"year": yr, "value": value})

    return result
