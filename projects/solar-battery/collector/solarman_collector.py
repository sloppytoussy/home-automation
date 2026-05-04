import logging
import threading
import time

from .writer import SolarReading, SolarWriter

log = logging.getLogger(__name__)


class SolarManCollector:
    """
    Polls a Deye/Shinewi inverter via the SolarMan local API (pysolarmanv5).
    The WiFi data logger (LSW-3 / LSE-3) must be on the same LAN.

    Setup:
      1. Find the dongle IP on your router's DHCP table
      2. Find the serial number on the dongle sticker
      3. Run: python -m pysolarmanv5.cli --host <ip> --serial <sn>
         to verify connectivity and view available parameters.
    """

    def __init__(self, solarman_cfg: dict, writer: SolarWriter):
        self._cfg = solarman_cfg
        self._writer = writer
        self._interval = solarman_cfg.get("poll_interval_s", 30)
        self._param_map: dict = solarman_cfg.get("param_map", {})
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _poll(self) -> SolarReading | None:
        try:
            from pysolarmanv5 import PySolarmanV5
        except ImportError:
            log.error("pysolarmanv5 not installed. Run: pip install pysolarmanv5")
            return None

        cfg = self._cfg
        try:
            client = PySolarmanV5(
                address=cfg["host"],
                serial=int(cfg["serial"]),
                port=int(cfg.get("port", 8899)),
                mb_slaveid=1,
                verbose=False,
            )
            params = client.get_all_parameter_names()
            data = {p: client.get_parameter_value(p) for p in params}

            def get(key: str) -> float | None:
                mapped = self._param_map.get(key)
                if not mapped:
                    return None
                val = data.get(mapped)
                return float(val) if val is not None else None

            return SolarReading(
                pv_power_w=get("pv_power_w") or 0.0,
                battery_soc_pct=get("battery_soc_pct") or 0.0,
                battery_power_w=get("battery_power_w") or 0.0,
                load_power_w=get("load_power_w") or 0.0,
                grid_power_w=get("grid_power_w") or 0.0,
                battery_voltage_v=get("battery_voltage_v"),
                inverter_temp_c=get("inverter_temp_c"),
                daily_yield_kwh=get("daily_yield_kwh"),
                source="solarman",
            )
        except Exception as e:
            log.warning("SolarMan poll error: %s", e)
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            start = time.monotonic()
            try:
                reading = self._poll()
                if reading:
                    self._writer.write_reading(reading)
                    log.info(
                        "pv=%.0fW soc=%.1f%% bat=%.0fW load=%.0fW",
                        reading.pv_power_w, reading.battery_soc_pct,
                        reading.battery_power_w, reading.load_power_w,
                    )
            except Exception as e:
                log.error("SolarMan run error: %s", e)
            time.sleep(max(0, self._interval - (time.monotonic() - start)))

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="solarman-collector")
        self._thread.start()
        log.info("SolarMan collector started — %s serial=%s", self._cfg["host"], self._cfg.get("serial"))

    def stop(self) -> None:
        self._stop.set()
