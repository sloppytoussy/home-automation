from __future__ import annotations

import pytest

from dashboard.calculator import (
    calculate_net_consumption,
    calculate_tiered_cost,
    detect_variance,
    load_breakdown,
    project_monthly,
)

TIERS = [
    {"name": "lifeline", "start_kwh": 0, "end_kwh": 20, "rate_rwf_per_kwh": 89},
    {"name": "standard", "start_kwh": 20, "end_kwh": 50, "rate_rwf_per_kwh": 310},
    {"name": "high_usage", "start_kwh": 50, "end_kwh": None, "rate_rwf_per_kwh": 369},
]


@pytest.mark.parametrize(
    "kwh,expected",
    [
        (0, 0),
        (1, 89),
        (5, 445),
        (10, 890),
        (19.5, 1735.5),
        (20, 1780),
        (21, 2090),
        (25, 3330),
        (35, 6430),
        (50, 11080),
        (51, 11449),
        (60, 14770),
        (75, 20305),
        (100, 29530),
        (125.25, 38847.25),
    ],
)
def test_calculate_tiered_cost_valid_usage_returns_expected_total(kwh, expected):
    assert calculate_tiered_cost(kwh, TIERS)["total_cost_rwf"] == expected


@pytest.mark.parametrize("kwh", [0, 5, 20, 21, 50, 60])
def test_calculate_tiered_cost_returns_three_tier_breakdown(kwh):
    result = calculate_tiered_cost(kwh, TIERS)
    assert len(result["tier_breakdown"]) == 3
    assert result["currency"] == "RWF"


@pytest.mark.parametrize(
    "kwh,expected_kwh",
    [
        (10, [10, 0, 0]),
        (20, [20, 0, 0]),
        (30, [20, 10, 0]),
        (50, [20, 30, 0]),
        (55, [20, 30, 5]),
    ],
)
def test_calculate_tiered_cost_allocates_kwh_across_tiers(kwh, expected_kwh):
    breakdown = calculate_tiered_cost(kwh, TIERS)["tier_breakdown"]
    assert [tier["kwh"] for tier in breakdown] == expected_kwh


@pytest.mark.parametrize("bad_kwh", [-1, "10", None, True])
def test_calculate_tiered_cost_invalid_kwh_raises_value_error(bad_kwh):
    with pytest.raises(ValueError, match="kwh"):
        calculate_tiered_cost(bad_kwh, TIERS)


@pytest.mark.parametrize(
    "bad_tiers",
    [
        [],
        [{"start_kwh": 1, "end_kwh": None, "rate_rwf_per_kwh": 1}],
        [{"start_kwh": 0, "end_kwh": 0, "rate_rwf_per_kwh": 1}],
        [{"start_kwh": 0, "end_kwh": None, "rate_rwf_per_kwh": 1}, {"start_kwh": 1, "end_kwh": None, "rate_rwf_per_kwh": 1}],
        [{"start_kwh": 0, "end_kwh": 1, "rate_rwf_per_kwh": -1}, {"start_kwh": 1, "end_kwh": None, "rate_rwf_per_kwh": 1}],
    ],
)
def test_calculate_tiered_cost_invalid_tiers_raise_value_error(bad_tiers):
    with pytest.raises(ValueError):
        calculate_tiered_cost(10, bad_tiers)


@pytest.mark.parametrize(
    "consumed,solar,expected",
    [
        (10, 0, 10),
        (10, 2.5, 7.5),
        (10, 10, 0),
        (10, 12, 0),
        (0, 0, 0),
    ],
)
def test_calculate_net_consumption_handles_solar_export(consumed, solar, expected):
    assert calculate_net_consumption(consumed, solar)["net_kwh"] == expected


@pytest.mark.parametrize("consumed,solar", [(-1, 0), (1, -1), ("1", 0), (1, None)])
def test_calculate_net_consumption_invalid_input_raises_value_error(consumed, solar):
    with pytest.raises(ValueError):
        calculate_net_consumption(consumed, solar)


def test_load_breakdown_sorts_by_watts_descending():
    result = load_breakdown([
        {"circuit": "lighting", "watts": 100},
        {"circuit": "kitchen", "watts": 400},
        {"circuit": "pump", "watts": 250},
    ])
    assert [row["circuit"] for row in result] == ["kitchen", "pump", "lighting"]


def test_load_breakdown_percentages_sum_to_100():
    result = load_breakdown([
        {"circuit": "a", "watts": 1},
        {"circuit": "b", "watts": 1},
        {"circuit": "c", "watts": 1},
    ])
    assert sum(row["pct_of_total"] for row in result) == 100


def test_load_breakdown_empty_returns_empty_list():
    assert load_breakdown([]) == []


def test_load_breakdown_zero_total_returns_zero_percentages():
    assert load_breakdown([{"circuit": "a", "watts": 0}])[0]["pct_of_total"] == 0


@pytest.mark.parametrize("reading", [{"watts": 10}, {"circuit": "a"}, "bad", {"circuit": "a", "watts": -1}])
def test_load_breakdown_invalid_reading_raises_value_error(reading):
    with pytest.raises(ValueError):
        load_breakdown([reading])


@pytest.mark.parametrize(
    "manual,automated,threshold,flagged",
    [
        (100, 101, 2, False),
        (100, 102, 2, False),
        (100, 102.1, 2, True),
        (100, 97.9, 2, True),
        (50, 49.5, 2, False),
        (50, 45, 5, True),
    ],
)
def test_detect_variance_flags_only_above_threshold(manual, automated, threshold, flagged):
    assert detect_variance(manual, automated, threshold)["flagged"] is flagged


@pytest.mark.parametrize("manual,automated,threshold", [(0, 1, 2), (-1, 1, 2), (1, -1, 2), (1, 1, -1), ("1", 1, 2)])
def test_detect_variance_invalid_input_raises_value_error(manual, automated, threshold):
    with pytest.raises(ValueError):
        detect_variance(manual, automated, threshold)


@pytest.mark.parametrize(
    "values,confidence",
    [
        ([1], "low"),
        ([1, 2, 3, 4], "low"),
        ([1, 2, 3, 4, 5], "medium"),
        ([1] * 14, "medium"),
        ([1] * 15, "high"),
        ([1] * 31, "high"),
    ],
)
def test_project_monthly_confidence_by_sample_days(values, confidence):
    assert project_monthly(values)["confidence"] == confidence


def test_project_monthly_projects_average_to_month():
    result = project_monthly([2, 4], days_in_month=30)
    assert result["avg_daily_kwh"] == 3
    assert result["projected_monthly_kwh"] == 90


@pytest.mark.parametrize("values,days", [([], 30), ([1], 0), ([1], 32), (["1"], 30), ([-1], 30), ("bad", 30)])
def test_project_monthly_invalid_input_raises_value_error(values, days):
    with pytest.raises(ValueError):
        project_monthly(values, days)
