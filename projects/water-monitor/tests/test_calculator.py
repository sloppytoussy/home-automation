import pytest
from collector.calculator import (
    compute_reading,
    normalise_distance,
    consumption_rate_lph,
    days_remaining,
    TankReading,
)


# ------------------------------------------------------------------
# Test normalise_distance()
# ------------------------------------------------------------------


class TestNormaliseDistance:
    """Tests for unit conversion from mm/cm to cm."""

    def test_mm_to_cm_conversion(self):
        """Convert millimeters to centimeters."""
        assert normalise_distance(100.0, "mm") == 10.0
        assert normalise_distance(50.0, "mm") == 5.0
        assert normalise_distance(1.0, "mm") == 0.1

    def test_cm_passthrough(self):
        """Centimeters remain unchanged."""
        assert normalise_distance(10.0, "cm") == 10.0
        assert normalise_distance(50.0, "cm") == 50.0
        assert normalise_distance(0.0, "cm") == 0.0

    def test_unknown_unit_treated_as_cm(self):
        """Unknown units are treated as centimeters (passthrough)."""
        assert normalise_distance(25.0, "unknown") == 25.0
        assert normalise_distance(25.0, "inches") == 25.0

    def test_zero_distance(self):
        """Zero distance in either unit."""
        assert normalise_distance(0.0, "mm") == 0.0
        assert normalise_distance(0.0, "cm") == 0.0

    def test_float_precision(self):
        """Float precision is preserved in conversion."""
        result = normalise_distance(25.5, "mm")
        assert abs(result - 2.55) < 1e-9


# ------------------------------------------------------------------
# Test compute_reading()
# ------------------------------------------------------------------


class TestComputeReading:
    """Tests for tank reading computation."""

    def test_basic_reading_half_full(self):
        """Tank at 50% capacity."""
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}
        reading = compute_reading(cfg, 50.0)

        assert reading.tank_id == "tank1"
        assert reading.distance_raw_cm == 50.0
        assert reading.level_cm == 50.0
        assert reading.level_pct == 50.0
        assert reading.volume_liters == 500.0
        assert reading.usable_depth_cm == 100.0
        assert reading.capacity_liters == 1000.0

    def test_reading_with_sensor_offset(self):
        """Tank with sensor mounted at an offset."""
        cfg = {
            "id": "tank1",
            "depth_cm": 100,
            "sensor_offset_cm": 10,
            "capacity_liters": 1000,
        }
        # Sensor offset 10cm means usable depth is 90cm
        # Distance reading of 45 → level_cm = 90 - 45 = 45
        reading = compute_reading(cfg, 45.0)

        assert reading.usable_depth_cm == 90.0
        assert reading.level_cm == 45.0
        assert reading.level_pct == 50.0  # 45/90 = 50%
        assert reading.volume_liters == 500.0  # 50% of 1000

    def test_reading_empty_tank(self):
        """Sensor reading indicates empty tank."""
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}
        reading = compute_reading(cfg, 100.0)

        assert reading.level_cm == 0.0
        assert reading.level_pct == 0.0
        assert reading.volume_liters == 0.0

    def test_reading_full_tank(self):
        """Sensor reading indicates full tank."""
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}
        reading = compute_reading(cfg, 0.0)

        assert reading.level_cm == 100.0
        assert reading.level_pct == 100.0
        assert reading.volume_liters == 1000.0

    def test_reading_beyond_full_capped_at_100_percent(self):
        """Negative sensor distance = overflow condition detected.

        Physical scenario: Water level exceeds design capacity. This can happen if:
        - Tank with open_outlet: Safe outlet below ceiling is allowing overflow (normal)
        - Tank with no_outlet: Inlet shutoff failed, water above tank top (error)

        The calculator reports the condition; collector/alert service uses tank_cfg
        to determine if it's normal or error based on overflow_handling setting.

        Expected behavior:
        - level_pct capped at 100% for UI display consistency
        - volume_liters exceeds capacity to preserve overflow information
        """
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}
        reading = compute_reading(cfg, -10.0)

        assert reading.level_cm == 110.0  # max(0, 100 - (-10))
        assert reading.level_pct == 100.0  # capped by min(100, ...)
        # Volume is 110/100*1000 = 1100L (exceeds capacity to indicate overflow)
        # Note: The meaning of volume > capacity depends on tank configuration:
        # - overflow_handling: "open_outlet" → normal operation (safe outlet working)
        # - overflow_handling: "no_outlet" → error condition (inlet shutoff failed)
        assert reading.volume_liters == 1100.0

    def test_reading_negative_distance_clamped_level(self):
        """Negative distance is clamped to 0 for level_cm."""
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}
        reading = compute_reading(cfg, -5.0)

        # level_cm = max(0, 100 - (-5)) = max(0, 105) = 105
        # But min(100, 105/100*100) = min(100, 105) = 100
        assert reading.level_pct == 100.0

    def test_zero_usable_depth_prevents_division_by_zero(self):
        """When usable depth is zero, percentages default to 0%."""
        cfg = {
            "id": "tank1",
            "depth_cm": 50,
            "sensor_offset_cm": 50,
            "capacity_liters": 1000,
        }
        reading = compute_reading(cfg, 10.0)

        assert reading.usable_depth_cm == 0.0
        assert reading.level_pct == 0.0
        assert reading.volume_liters == 0.0
        assert reading.level_cm == 0.0  # max(0, 0 - 10)

    def test_small_tank(self):
        """Very small tank (e.g., 10L)."""
        cfg = {"id": "tiny", "depth_cm": 20, "capacity_liters": 10}
        reading = compute_reading(cfg, 10.0)

        assert reading.volume_liters == 5.0
        assert reading.level_pct == 50.0

    def test_large_tank(self):
        """Very large tank (e.g., 50,000L)."""
        cfg = {"id": "large", "depth_cm": 500, "capacity_liters": 50000}
        reading = compute_reading(cfg, 250.0)

        assert reading.volume_liters == 25000.0
        assert reading.level_pct == 50.0

    def test_rounding_distance_raw(self):
        """distance_raw_cm is rounded to 1 decimal place."""
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}
        reading = compute_reading(cfg, 50.12345)

        assert reading.distance_raw_cm == 50.1

    def test_rounding_level_cm(self):
        """level_cm is rounded to 1 decimal place."""
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}
        reading = compute_reading(cfg, 50.55555)

        assert reading.level_cm == 49.4  # 100 - 50.55555 ≈ 49.44445 → 49.4

    def test_rounding_volume_liters(self):
        """volume_liters is rounded to 1 decimal place."""
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}
        reading = compute_reading(cfg, 50.55555)

        # level_cm = 100 - 50.55555 = 49.44445
        # volume = 49.44445 / 100 * 1000 = 494.4445
        assert reading.volume_liters == 494.4

    def test_rounding_level_pct(self):
        """level_pct is rounded to 2 decimal places."""
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}
        reading = compute_reading(cfg, 33.33333)

        # level_cm = 100 - 33.33333 = 66.66667
        # pct = 66.66667 / 100 * 100 = 66.66667 → 66.67
        assert reading.level_pct == 66.67

    def test_string_inputs_converted_to_float(self):
        """Config values are strings but converted to float."""
        cfg = {
            "id": "tank1",
            "depth_cm": "100",
            "capacity_liters": "1000",
            "sensor_offset_cm": "10",
        }
        reading = compute_reading(cfg, 45.0)

        assert reading.usable_depth_cm == 90.0
        assert reading.level_pct == 50.0

    def test_missing_sensor_offset_defaults_to_zero(self):
        """Sensor offset is optional and defaults to 0."""
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}
        reading = compute_reading(cfg, 50.0)

        assert reading.usable_depth_cm == 100.0


# ------------------------------------------------------------------
# Test consumption_rate_lph()
# ------------------------------------------------------------------


class TestConsumptionRateLph:
    """Tests for drain rate calculation from readings."""

    def test_simple_drain_rate(self):
        """Two readings over 1 hour show 100 L/h drain."""
        readings = [
            (0.0, 1000.0),      # t=0s, v=1000L
            (3600.0, 900.0),    # t=3600s (1h), v=900L
        ]
        rate = consumption_rate_lph(readings)

        assert rate == 100.0  # (1000-900) / 1h

    def test_drain_rate_over_multiple_hours(self):
        """Drain over 10 hours."""
        readings = [
            (0.0, 1000.0),
            (36000.0, 500.0),   # 10 hours later
        ]
        rate = consumption_rate_lph(readings)

        assert rate == 50.0  # (1000-500) / 10h

    def test_no_drain_returns_none(self):
        """No consumption (volume unchanged)."""
        readings = [
            (0.0, 1000.0),
            (3600.0, 1000.0),   # Same volume
        ]
        rate = consumption_rate_lph(readings)

        assert rate is None

    def test_refill_returns_none(self):
        """Tank refilled (volume increased)."""
        readings = [
            (0.0, 500.0),
            (3600.0, 1000.0),   # Volume increased
        ]
        rate = consumption_rate_lph(readings)

        assert rate is None

    def test_insufficient_readings_returns_none(self):
        """Less than 2 readings."""
        assert consumption_rate_lph([]) is None
        assert consumption_rate_lph([(0.0, 1000.0)]) is None

    def test_zero_time_delta_returns_none(self):
        """Same timestamp in both readings."""
        readings = [
            (3600.0, 1000.0),
            (3600.0, 900.0),    # Same timestamp
        ]
        rate = consumption_rate_lph(readings)

        assert rate is None

    def test_negative_time_delta_returns_none(self):
        """Second reading before first (not time-ordered)."""
        readings = [
            (3600.0, 1000.0),
            (1800.0, 900.0),    # Earlier timestamp
        ]
        rate = consumption_rate_lph(readings)

        assert rate is None

    def test_many_readings_uses_first_and_last(self):
        """With multiple readings, uses first and last only."""
        readings = [
            (0.0, 1000.0),
            (900.0, 999.0),     # Ignored
            (1800.0, 998.0),    # Ignored
            (3600.0, 900.0),    # Last
        ]
        rate = consumption_rate_lph(readings)

        assert rate == 100.0  # (1000-900) / 1h, ignoring middle readings

    def test_very_slow_drain(self):
        """Slow consumption (e.g., 0.5 L/h)."""
        readings = [
            (0.0, 1000.0),
            (7200.0, 999.0),    # 2 hours, 1L drain
        ]
        rate = consumption_rate_lph(readings)

        assert rate == 0.5

    def test_very_fast_drain(self):
        """Fast consumption (e.g., 500 L/h)."""
        readings = [
            (0.0, 1000.0),
            (3600.0, 500.0),    # 1 hour, 500L drain
        ]
        rate = consumption_rate_lph(readings)

        assert rate == 500.0

    def test_rounding_to_two_decimals(self):
        """Result is rounded to 2 decimal places."""
        readings = [
            (0.0, 1000.0),
            (3600.0, 899.123),
        ]
        rate = consumption_rate_lph(readings)

        assert rate == 100.88  # (1000 - 899.123) / 1h, rounded to 2 decimals


# ------------------------------------------------------------------
# Test days_remaining()
# ------------------------------------------------------------------


class TestDaysRemaining:
    """Tests for projected days until empty."""

    def test_days_remaining_basic(self):
        """At 4.167 L/h drain rate, 1000L tank lasts ~10 days."""
        # 1000 / (4.167 * 24) ≈ 10 days
        days = days_remaining(1000.0, 4.167)

        assert abs(days - 10.0) < 0.1

    def test_days_remaining_fractional(self):
        """0.5 days at 50 L/h drain and 600L volume.

        600 / (50 * 24) = 600 / 1200 = 0.5 days
        """
        days = days_remaining(600.0, 50.0)

        assert days == 0.5

    def test_days_remaining_slow_drain(self):
        """Very slow drain: 0.01 L/h, 1000L tank.

        1000 / (0.01 * 24) = 1000 / 0.24 ≈ 4166.67 days
        """
        days = days_remaining(1000.0, 0.01)

        assert abs(days - 4166.67) < 0.1

    def test_zero_rate_returns_none(self):
        """Cannot calculate with zero drain rate."""
        assert days_remaining(1000.0, 0.0) is None

    def test_negative_rate_returns_none(self):
        """Negative drain rate (refilling) returns None."""
        assert days_remaining(1000.0, -50.0) is None

    def test_none_rate_returns_none(self):
        """None rate (e.g., from consumption_rate_lph) returns None."""
        assert days_remaining(1000.0, None) is None

    def test_zero_volume_returns_zero(self):
        """Empty tank returns 0 days."""
        days = days_remaining(0.0, 100.0)

        assert days == 0.0

    def test_very_small_volume(self):
        """Tiny remaining volume."""
        days = days_remaining(0.1, 100.0)

        assert days == 0.0  # Rounding: 0.1 / (100*24) = 0.00004 → 0.0

    def test_rounding_to_two_decimals(self):
        """Result is rounded to 2 decimal places."""
        # 1000L / (33.33 L/h * 24 h/day) = 1000 / 799.92 ≈ 1.25 days
        days = days_remaining(1000.0, 33.33)

        assert days == 1.25


# ------------------------------------------------------------------
# Integration Tests (multiple functions together)
# ------------------------------------------------------------------


class TestIntegration:
    """Tests combining multiple calculator functions."""

    def test_full_workflow_tank_depletion(self):
        """Full workflow: distance → reading → consumption rate → days left."""
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}

        # Initial reading: 50cm distance → 500L
        reading1 = compute_reading(cfg, 50.0)
        assert reading1.volume_liters == 500.0

        # Later reading: 55cm distance → 450L (50L consumed in 12 hours)
        reading2 = compute_reading(cfg, 55.0)
        assert reading2.volume_liters == 450.0

        # Calculate consumption rate: 50L over 12 hours = 4.17 L/h
        t1, t2 = 0.0, 43200.0  # 12 hours in seconds
        rate = consumption_rate_lph([(t1, reading1.volume_liters), (t2, reading2.volume_liters)])
        assert abs(rate - 4.17) < 0.01

        # Projected days remaining: 450L / (4.17 L/h * 24 h/day) ≈ 4.5 days
        remaining = days_remaining(reading2.volume_liters, rate)
        assert abs(remaining - 4.5) < 0.1

    def test_workflow_with_sensor_offset(self):
        """Tank with offset sensor through full workflow."""
        cfg = {
            "id": "tank1",
            "depth_cm": 200,
            "sensor_offset_cm": 20,
            "capacity_liters": 5000,
        }

        reading = compute_reading(cfg, 90.0)  # Sensor reading
        assert reading.usable_depth_cm == 180.0
        assert reading.level_cm == 90.0  # 180 - 90
        assert abs(reading.level_pct - 50.0) < 0.1

    def test_workflow_normalise_then_compute(self):
        """Normalise distance first, then compute reading."""
        cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}

        # Sensor reports 500mm
        distance_cm = normalise_distance(500.0, "mm")
        assert distance_cm == 50.0

        reading = compute_reading(cfg, distance_cm)
        assert reading.level_pct == 50.0
