"""
Generate dummy data files for solar-battery dashboard testing.
Hardware: 1x MPPT, hybrid topology, 2x12V 200Ah LifePO4, Kigali Rwanda
Run: python solar_dummy_data.py
Outputs: solar_readings.csv, energy_totals.csv, solar_readings.json
"""
from __future__ import annotations
import json
import csv
import math
import random
from datetime import datetime, timezone, timedelta

random.seed(42)

# ── Constants ────────────────────────────────────────────────────────────────
BATTERY_CAPACITY_WH = 2 * 12 * 200  # 4800 Wh total, ~80% usable = 3840 Wh
PANEL_PEAK_W = 1200                  # assumed 1200W PV array
GRID_BASE_LOAD_W = 320               # average household AC load
PORTAL_ID = "a1b2c3d4e5f6"          # placeholder
LATITUDE = -1.9441                   # Kigali

def solar_irradiance(hour: float, cloud_factor: float = 1.0) -> float:
    """Simulate solar irradiance for Kigali (sunrise ~6am, sunset ~6pm)."""
    if hour < 6 or hour > 18:
        return 0.0
    angle = math.pi * (hour - 6) / 12
    peak = math.sin(angle)
    return max(0.0, peak * cloud_factor)

def mppt_state(irradiance: float, soc: float) -> int:
    if irradiance < 0.05:
        return 0   # Off
    if soc < 0.85:
        return 3   # Bulk
    if soc < 0.97:
        return 4   # Absorption
    return 5       # Float

def simulate_day(base_date: datetime, soc_start: float, cloud_factor: float):
    records = []
    soc = soc_start
    yield_kwh = 0.0

    for minute in range(0, 24 * 60, 5):  # every 5 minutes
        ts = base_date + timedelta(minutes=minute)
        hour = minute / 60.0

        irr = solar_irradiance(hour, cloud_factor)
        pv_power = irr * PANEL_PEAK_W * random.uniform(0.88, 1.0)

        # Load varies by time of day
        if 6 <= hour < 8 or 18 <= hour < 22:
            load = GRID_BASE_LOAD_W * random.uniform(1.2, 1.8)
        elif 0 <= hour < 5:
            load = GRID_BASE_LOAD_W * random.uniform(0.2, 0.4)
        else:
            load = GRID_BASE_LOAD_W * random.uniform(0.7, 1.1)

        # Battery charging/discharging
        net = pv_power - load
        battery_power = 0.0
        grid_power = 0.0

        if net > 0:
            # Surplus — charge battery first, export rest
            charge_headroom = (1.0 - soc) * BATTERY_CAPACITY_WH
            charge = min(net, charge_headroom / (5/60))
            battery_power = charge
            grid_power = -(net - charge)  # negative = export
        else:
            # Deficit — discharge battery first, import rest
            deficit = abs(net)
            discharge_available = (soc - 0.10) * BATTERY_CAPACITY_WH
            discharge = min(deficit, discharge_available / (5/60))
            battery_power = -discharge
            grid_power = deficit - discharge  # positive = import

        # Update SOC
        soc_delta = battery_power * (5/60) / BATTERY_CAPACITY_WH
        soc = max(0.10, min(1.0, soc + soc_delta))

        # Yield accumulates during daylight
        yield_kwh += pv_power * (5/60) / 1000

        # Voltage approximation for LifePO4 (24V nominal)
        voltage = 24.0 + (soc - 0.5) * 2.8 + random.uniform(-0.1, 0.1)
        current = battery_power / voltage if voltage > 0 else 0.0

        state = mppt_state(irr, soc)

        records.append({
            "time": ts.isoformat(),
            "portal_id": PORTAL_ID,
            "device": "cerbo",
            "source": "victron_cerbo",
            "pv_power_w": round(pv_power, 1),
            "pv_yield_today_kwh": round(yield_kwh, 3),
            "battery_soc_pct": round(soc * 100, 1),
            "battery_power_w": round(battery_power, 1),
            "battery_voltage_v": round(voltage, 2),
            "battery_current_a": round(current, 2),
            "grid_power_w": round(grid_power, 1),
            "ac_load_w": round(load, 1),
            "inverter_output_w": round(load * random.uniform(0.97, 1.0), 1),
            "mppt_state": state,
        })

    return records, soc, yield_kwh

# ── Generate 30 days of data ─────────────────────────────────────────────────
now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
all_records = []
daily_totals = []
soc = 0.75

cloud_patterns = [
    0.95, 0.85, 1.0, 0.70, 0.90, 0.60, 1.0,
    0.95, 0.80, 1.0, 0.88, 0.75, 0.92, 0.65,
    1.0,  0.85, 0.78, 0.95, 0.70, 0.88, 1.0,
    0.82, 0.91, 0.68, 1.0,  0.85, 0.75, 0.93,
    0.88, 0.72,
]

for day_offset in range(30):
    base = now - timedelta(days=29 - day_offset)
    cloud = cloud_patterns[day_offset % len(cloud_patterns)]
    day_records, soc, yield_kwh = simulate_day(base, soc, cloud)
    all_records.extend(day_records)

    grid_import = sum(r["grid_power_w"] for r in day_records if r["grid_power_w"] > 0) * (5/60) / 1000
    grid_export = sum(abs(r["grid_power_w"]) for r in day_records if r["grid_power_w"] < 0) * (5/60) / 1000
    avg_soc = sum(r["battery_soc_pct"] for r in day_records) / len(day_records)
    peak_pv = max(r["pv_power_w"] for r in day_records)

    daily_totals.append({
        "date": base.strftime("%Y-%m-%d"),
        "pv_yield_kwh": round(yield_kwh, 3),
        "grid_import_kwh": round(grid_import, 3),
        "grid_export_kwh": round(grid_export, 3),
        "avg_battery_soc_pct": round(avg_soc, 1),
        "peak_pv_power_w": round(peak_pv, 1),
        "solar_export_kwh": round(grid_export, 3),
    })

# ── Write outputs ─────────────────────────────────────────────────────────────
# 1. Full CSV — all 5-min readings (30 days)
csv_fields = list(all_records[0].keys())
with open("/mnt/user-data/outputs/solar_readings.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=csv_fields)
    writer.writeheader()
    writer.writerows(all_records)

# 2. Daily totals CSV
daily_fields = list(daily_totals[0].keys())
with open("/mnt/user-data/outputs/energy_totals.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=daily_fields)
    writer.writeheader()
    writer.writerows(daily_totals)

# 3. Latest reading JSON (what /api/solar/summary returns)
latest = all_records[-1].copy()
latest["mppt_state_label"] = {0:"Off",2:"Fault",3:"Bulk",4:"Absorption",5:"Float"}.get(latest["mppt_state"],"Unknown")
latest["data_available"] = True
latest["last_updated"] = latest["time"]
with open("/mnt/user-data/outputs/solar_summary_latest.json", "w") as f:
    json.dump(latest, f, indent=2)

# 4. Battery history JSON — last 24h at 5-min intervals
last_24h = all_records[-288:]
battery_history = [
    {"time": r["time"], "soc_pct": r["battery_soc_pct"],
     "power_w": r["battery_power_w"], "voltage_v": r["battery_voltage_v"],
     "current_a": r["battery_current_a"]}
    for r in last_24h
]
with open("/mnt/user-data/outputs/battery_history.json", "w") as f:
    json.dump(battery_history, f, indent=2)

# 5. Summary stats
total_pv = sum(d["pv_yield_kwh"] for d in daily_totals)
total_import = sum(d["grid_import_kwh"] for d in daily_totals)
total_export = sum(d["grid_export_kwh"] for d in daily_totals)
print(f"Generated {len(all_records)} records across 30 days")
print(f"Total PV yield:    {total_pv:.1f} kWh")
print(f"Total grid import: {total_import:.1f} kWh")
print(f"Total grid export: {total_export:.1f} kWh")
print(f"Self-sufficiency:  {(1 - total_import/(total_pv + total_import))*100:.1f}%")
print(f"Final battery SOC: {soc*100:.1f}%")
