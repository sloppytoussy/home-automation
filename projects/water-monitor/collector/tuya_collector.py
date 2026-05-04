import logging
import time
import threading

from .calculator import compute_reading, normalise_distance
from .writer import WaterWriter

log = logging.getLogger(__name__)


class TuyaWaterCollector:
    """
    Polls Tuya local-API water level sensors for tanks configured with type=tuya.
    Requires tinytuya and device credentials from the Tuya IoT Platform.

    Setup guide:
      1. pip install tinytuya
      2. python -m tinytuya wizard   (discovers devices on your LAN)
      3. Copy device_id, ip, local_key into tanks.yaml
    """

    def __init__(self, tank_cfgs: list[dict], tuya_device_cfgs: list[dict], writer: WaterWriter):
        self._tank_map = {t["id"]: t for t in tank_cfgs if t.get("sensor", {}).get("type") == "tuya"}
        self._devices = {d["tank_id"]: d for d in tuya_device_cfgs}
        self._writer = writer
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _poll_device(self, tank_id: str) -> None:
        try:
            import tinytuya  # lazy import — optional dependency
        except ImportError:
            log.error("tinytuya not installed. Run: pip install tinytuya")
            return

        tank_cfg = self._tank_map[tank_id]
        dev_cfg = self._devices[tank_id]

        if not dev_cfg.get("device_id") or not dev_cfg.get("ip") or not dev_cfg.get("local_key"):
            log.warning("[%s] Tuya device not configured (device_id/ip/local_key missing)", tank_id)
            return

        try:
            device = tinytuya.Device(
                dev_id=dev_cfg["device_id"],
                address=dev_cfg["ip"],
                local_key=dev_cfg["local_key"],
                version=float(dev_cfg.get("version", 3.3)),
            )
            device.set_socketPersistent(False)
            data = device.status()

            dps = data.get("dps", {})
            dp_dist = str(dev_cfg.get("dp_distance", 1))
            dp_bat = str(dev_cfg.get("dp_battery", 2))

            raw_distance = dps.get(dp_dist)
            if raw_distance is None:
                log.warning("[%s] DP %s not found in response: %s", tank_id, dp_dist, dps)
                return

            unit = tank_cfg.get("sensor", {}).get("unit", "cm")
            distance_cm = normalise_distance(float(raw_distance), unit)
            reading = compute_reading(tank_cfg, distance_cm)

            source = tank_cfg.get("active_source", tank_cfg["sources"][0])
            self._writer.write_reading(reading, source=source)
            log.info("[%s] dist=%.1fcm level=%.1f%% vol=%.0fL", tank_id, distance_cm, reading.level_pct, reading.volume_liters)

            # Battery (optional)
            if dp_bat in dps and dev_cfg.get("dp_battery", 0):
                self._writer.write_battery(tank_id, float(dps[dp_bat]))

        except Exception as e:
            log.warning("[%s] Tuya poll error: %s", tank_id, e)

    def _run(self) -> None:
        intervals = {
            tank_id: self._devices.get(tank_id, {}).get("poll_interval_s", 60)
            for tank_id in self._tank_map
        }
        last_poll = {tank_id: 0.0 for tank_id in self._tank_map}

        while not self._stop_event.is_set():
            now = time.monotonic()
            for tank_id, interval in intervals.items():
                if now - last_poll[tank_id] >= interval:
                    self._poll_device(tank_id)
                    last_poll[tank_id] = now
            time.sleep(5)

    def start(self) -> None:
        if not self._tank_map:
            log.info("No Tuya tanks configured — skipping Tuya collector")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="tuya-collector")
        self._thread.start()
        log.info("Tuya collector started for tanks: %s", list(self._tank_map.keys()))

    def stop(self) -> None:
        self._stop_event.set()
