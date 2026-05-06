from __future__ import annotations

from collections.abc import Sequence
from typing import Any

Number = Any
Tier = dict[str, Any]


def _require_number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be greater than or equal to {minimum}")
    return result


def _validate_tiers(tiers: Sequence[Tier]) -> list[Tier]:
    if not tiers:
        raise ValueError("tiers must contain at least one tier")

    normalised: list[Tier] = []
    expected_start = 0.0
    open_ended_seen = False

    for index, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            raise ValueError("each tier must be a dictionary")
        start = _require_number(tier.get("start_kwh"), "tier start_kwh", minimum=0.0)
        if start != expected_start:
            raise ValueError("tiers must be contiguous and start at 0")
        end_raw = tier.get("end_kwh")
        end = None if end_raw is None else _require_number(end_raw, "tier end_kwh", minimum=0.0)
        if end is not None and end <= start:
            raise ValueError("tier end_kwh must be greater than start_kwh")
        if open_ended_seen:
            raise ValueError("open-ended tier must be the final tier")
        rate = _require_number(tier.get("rate_rwf_per_kwh"), "tier rate_rwf_per_kwh", minimum=0.0)
        normalised.append({
            "name": str(tier.get("name", f"tier_{index + 1}")),
            "start_kwh": start,
            "end_kwh": end,
            "rate_rwf_per_kwh": rate,
        })
        if end is None:
            open_ended_seen = True
        else:
            expected_start = end

    if normalised[-1]["end_kwh"] is not None:
        raise ValueError("final tier must be open-ended")
    return normalised


def calculate_tiered_cost(kwh: Number, tiers: Sequence[Tier]) -> dict[str, Any]:
    """Calculate RWF electricity cost from configured contiguous tariff tiers."""
    usage = _require_number(kwh, "kwh", minimum=0.0)
    valid_tiers = _validate_tiers(tiers)
    remaining = usage
    total = 0.0
    breakdown: list[dict[str, float | str]] = []

    for tier in valid_tiers:
        start = tier["start_kwh"]
        end = tier["end_kwh"]
        width = remaining if end is None else max(min(usage, end) - start, 0.0)
        tier_kwh = max(min(width, remaining), 0.0)
        cost = tier_kwh * tier["rate_rwf_per_kwh"]
        breakdown.append({
            "tier": tier["name"],
            "start_kwh": start,
            "end_kwh": end if end is not None else "open",
            "kwh": round(tier_kwh, 4),
            "rate_rwf_per_kwh": tier["rate_rwf_per_kwh"],
            "cost_rwf": round(cost, 2),
        })
        total += cost
        remaining = max(usage - (end if end is not None else usage), 0.0)
        if remaining <= 0:
            for unused in valid_tiers[len(breakdown):]:
                breakdown.append({
                    "tier": unused["name"],
                    "start_kwh": unused["start_kwh"],
                    "end_kwh": unused["end_kwh"] if unused["end_kwh"] is not None else "open",
                    "kwh": 0.0,
                    "rate_rwf_per_kwh": unused["rate_rwf_per_kwh"],
                    "cost_rwf": 0.0,
                })
            break

    return {
        "kwh": round(usage, 4),
        "currency": "RWF",
        "total_cost_rwf": round(total, 2),
        "tier_breakdown": breakdown,
    }


def calculate_net_consumption(consumed_kwh: Number, solar_export_kwh: Number = 0.0) -> dict[str, float]:
    consumed = _require_number(consumed_kwh, "consumed_kwh", minimum=0.0)
    solar_export = _require_number(solar_export_kwh, "solar_export_kwh", minimum=0.0)
    net = max(consumed - solar_export, 0.0)
    return {
        "consumed_kwh": round(consumed, 4),
        "solar_export_kwh": round(solar_export, 4),
        "net_kwh": round(net, 4),
    }


def load_breakdown(readings: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(readings, Sequence) or isinstance(readings, (str, bytes)):
        raise ValueError("readings must be a sequence")

    normalised: list[dict[str, Any]] = []
    total_watts = 0.0
    for reading in readings:
        if not isinstance(reading, dict):
            raise ValueError("each reading must be a dictionary")
        circuit = reading.get("circuit")
        if not circuit:
            raise ValueError("each reading must include circuit")
        watts = _require_number(reading.get("watts"), "watts", minimum=0.0)
        total_watts += watts
        normalised.append({"circuit": str(circuit), "watts": watts})

    sorted_rows = sorted(normalised, key=lambda item: item["watts"], reverse=True)
    if not sorted_rows:
        return []
    if total_watts == 0:
        return [{"circuit": row["circuit"], "watts": 0.0, "pct_of_total": 0.0} for row in sorted_rows]

    result: list[dict[str, Any]] = []
    running_pct = 0.0
    for index, row in enumerate(sorted_rows):
        if index == len(sorted_rows) - 1:
            pct = round(100.0 - running_pct, 2)
        else:
            pct = round(row["watts"] / total_watts * 100.0, 2)
            running_pct += pct
        result.append({
            "circuit": row["circuit"],
            "watts": round(row["watts"], 4),
            "pct_of_total": pct,
        })
    return result


def detect_variance(manual_kwh: Number, automated_kwh: Number, threshold_pct: Number = 2.0) -> dict[str, float | bool]:
    manual = _require_number(manual_kwh, "manual_kwh", minimum=0.0)
    automated = _require_number(automated_kwh, "automated_kwh", minimum=0.0)
    threshold = _require_number(threshold_pct, "threshold_pct", minimum=0.0)
    if manual == 0:
        raise ValueError("manual_kwh must be greater than 0")
    delta = automated - manual
    delta_pct = delta / manual * 100.0
    return {
        "manual_kwh": round(manual, 4),
        "automated_kwh": round(automated, 4),
        "delta_kwh": round(delta, 4),
        "delta_pct": round(delta_pct, 4),
        "threshold_pct": round(threshold, 4),
        "flagged": abs(delta_pct) > threshold,
    }


def project_monthly(daily_kwh: Sequence[Number], days_in_month: int = 30) -> dict[str, float | str | int]:
    if not isinstance(daily_kwh, Sequence) or isinstance(daily_kwh, (str, bytes)):
        raise ValueError("daily_kwh must be a sequence")
    days = int(_require_number(days_in_month, "days_in_month", minimum=1.0))
    if days > 31:
        raise ValueError("days_in_month must be 31 or less")
    values = [_require_number(value, "daily_kwh value", minimum=0.0) for value in daily_kwh]
    if not values:
        raise ValueError("daily_kwh must contain at least one value")

    sample_days = len(values)
    average = sum(values) / sample_days
    if sample_days < 5:
        confidence = "low"
    elif sample_days < 15:
        confidence = "medium"
    else:
        confidence = "high"

    return {
        "sample_days": sample_days,
        "avg_daily_kwh": round(average, 4),
        "projected_monthly_kwh": round(average * days, 4),
        "days_in_month": days,
        "confidence": confidence,
    }
