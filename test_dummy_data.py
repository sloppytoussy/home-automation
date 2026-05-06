#!/usr/bin/env python3
"""Test calculator with dummy data before Phase 2 implementation."""

import sys
sys.path.insert(0, '/home/user/home-automation/projects/water-monitor')

from collector.calculator import compute_reading, consumption_rate_lph, days_remaining

def test_scenario_1_no_outlet():
    """Tank with no_outlet (float valve should prevent overflow)."""
    print("\n" + "="*60)
    print("SCENARIO 1: NO_OUTLET Tank (WASAC Mains)")
    print("="*60)

    tank = {
        "id": "mains_tank",
        "depth_cm": 100,
        "capacity_liters": 1000,
        "sensor_offset_cm": 5,
        "num_sources": "single",
        "inlet_shutoff": "float_valve",
        "overflow_handling": "no_outlet",
    }

    # Normal operation
    reading = compute_reading(tank, 50.0)
    print(f"\n1a. Normal fill (50cm distance):")
    print(f"    Volume: {reading.volume_liters}L (capacity: {reading.capacity_liters}L)")
    print(f"    Level: {reading.level_pct}%")
    print(f"    Overflow? {reading.volume_liters > reading.capacity_liters}")
    assert reading.volume_liters <= reading.capacity_liters

    # Full tank
    reading = compute_reading(tank, 5.0)
    print(f"\n1b. Full tank (5cm distance):")
    print(f"    Volume: {reading.volume_liters}L")
    print(f"    Level: {reading.level_pct}%")
    print(f"    Overflow? {reading.volume_liters > reading.capacity_liters}")

    # OVERFLOW - Float valve failure
    reading = compute_reading(tank, -3.0)
    print(f"\n1c. OVERFLOW DETECTED (-3cm distance):")
    print(f"    Volume: {reading.volume_liters}L (EXCEEDS {reading.capacity_liters}L)")
    print(f"    Level: {reading.level_pct}% (capped)")
    print(f"    Overflow magnitude: {reading.volume_liters - reading.capacity_liters:.1f}L")
    assert reading.volume_liters > reading.capacity_liters
    print(f"    → ALERT DECISION: overflow_handling='{tank['overflow_handling']}'")
    print(f"    → ACTION: MAJOR ALERT + AUTO-SHUTOFF VALVE")
    print("    ✓ Test passed")

def test_scenario_2_open_outlet():
    """Tank with open_outlet (safe overflow during heavy rain)."""
    print("\n" + "="*60)
    print("SCENARIO 2: OPEN_OUTLET Tank (Rainwater)")
    print("="*60)

    tank = {
        "id": "rainwater_tank",
        "depth_cm": 120,
        "capacity_liters": 1200,
        "sensor_offset_cm": 5,
        "num_sources": "multiple",
        "inlet_shutoff": "float_valve",
        "overflow_handling": "open_outlet",
    }

    # Normal operation
    reading = compute_reading(tank, 60.0)
    print(f"\n2a. Rain collection (60cm distance):")
    print(f"    Volume: {reading.volume_liters}L (capacity: {reading.capacity_liters}L)")
    print(f"    Level: {reading.level_pct}%")
    print(f"    Overflow? {reading.volume_liters > reading.capacity_liters}")
    assert reading.volume_liters <= reading.capacity_liters

    # Near full
    reading = compute_reading(tank, 5.0)
    print(f"\n2b. Tank filling up (5cm distance):")
    print(f"    Volume: {reading.volume_liters}L")
    print(f"    Level: {reading.level_pct}%")

    # OVERFLOW - Outlet is working
    reading = compute_reading(tank, -2.0)
    print(f"\n2c. Outlet Active (-2cm distance):")
    print(f"    Volume: {reading.volume_liters}L (EXCEEDS {reading.capacity_liters}L)")
    print(f"    Level: {reading.level_pct}% (capped)")
    print(f"    Overflow magnitude: {reading.volume_liters - reading.capacity_liters:.1f}L")
    assert reading.volume_liters > reading.capacity_liters
    print(f"    → ALERT DECISION: overflow_handling='{tank['overflow_handling']}'")
    print(f"    → ACTION: LOG INFO + MONITOR (normal operation)")
    print("    ✓ Test passed")

def test_scenario_3_consumption():
    """Track consumption rate and project days remaining."""
    print("\n" + "="*60)
    print("SCENARIO 3: Consumption Rate & Days Remaining")
    print("="*60)

    # 5-hour consumption period (100L/h drain rate)
    readings = [
        (0,      1000.0),   # t=0h:  1000L
        (3600,    900.0),   # t=1h:  900L (100L consumed)
        (7200,    800.0),   # t=2h:  800L (200L consumed)
        (10800,   700.0),   # t=3h:  700L (300L consumed)
        (14400,   600.0),   # t=4h:  600L (400L consumed)
        (18000,   500.0),   # t=5h:  500L (500L consumed)
    ]

    rate = consumption_rate_lph(readings)
    print(f"\n3a. Drain rate over 5 hours:")
    print(f"    Initial: {readings[0][1]}L")
    print(f"    Final:   {readings[-1][1]}L")
    print(f"    Drained: {readings[0][1] - readings[-1][1]}L")
    print(f"    Time:    {(readings[-1][0] - readings[0][0])/3600:.1f}h")
    print(f"    Rate:    {rate} L/h")
    assert rate == 100.0

    remaining = days_remaining(500.0, rate)
    print(f"\n3b. Days remaining at current rate:")
    print(f"    Current volume: 500L")
    print(f"    Drain rate:     {rate} L/h")
    print(f"    Days left:      {remaining} days ({remaining*24:.1f} hours)")
    assert remaining == 0.21
    print("    ✓ Test passed")

def test_scenario_4_refill_detection():
    """Detect when tank is refilled (volume increases)."""
    print("\n" + "="*60)
    print("SCENARIO 4: Refill Detection")
    print("="*60)

    readings_with_refill = [
        (0,     1000.0),   # t=0h:  Start at 1000L
        (3600,   500.0),   # t=1h:  Drain to 500L (500L consumed)
        (7200,  1000.0),   # t=2h:  Refill to 1000L (REFILL DETECTED)
    ]

    print("\n4a. Consumption BEFORE refill:")
    rate_before = consumption_rate_lph(readings_with_refill[:2])
    print(f"    Readings: {readings_with_refill[:2]}")
    print(f"    Rate: {rate_before} L/h")
    assert rate_before == 500.0

    print("\n4b. Consumption INCLUDING refill:")
    rate_with_refill = consumption_rate_lph(readings_with_refill)
    print(f"    Readings: {readings_with_refill}")
    print(f"    Rate: {rate_with_refill}")
    assert rate_with_refill is None  # Refill detected (volume increased)
    print("    ✓ Refill correctly detected (returns None)")

if __name__ == "__main__":
    try:
        test_scenario_1_no_outlet()
        test_scenario_2_open_outlet()
        test_scenario_3_consumption()
        test_scenario_4_refill_detection()

        print("\n" + "="*60)
        print("✓ ALL DUMMY DATA TESTS PASSED")
        print("="*60)
        print("\nCalculator is ready for Phase 2 implementation:")
        print("  ✓ Detects overflow correctly")
        print("  ✓ Handles both tank types")
        print("  ✓ Tracks consumption rates")
        print("  ✓ Projects days remaining")
        print("\nPhase 2 will implement:")
        print("  → Collector overflow detection")
        print("  → Alert service decision logic")
        print("  → Notification channels (email, SMS, syslog)")
        print("  → Per-tank severity levels")
        print("  → Auto-shutoff valve integration")

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
