import logging
import time
import threading
from dataclasses import dataclass

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

from .writer import SolarReading, SolarWriter

log = logging.getLogger(__name__)


def _read_register(client: ModbusTcpClient, reg_cfg: dict, unit: int) -> float | None:
    reg = reg_cfg["reg"]
    scale = reg_cfg.get("scale", 1)
    signed = reg_cfg.get("signed", False)
    try:
        result = client.read_holding_registers(reg, count=1, slave=unit)
        if result.isError():
            return None
        raw = result.registers[0]
        if signed and raw > 32767:
            raw -= 65536
        return raw / scale
    except (ModbusException, AttributeError):
        return None


class ModbusSolarCollector:
    """Polls a Modbus TCP inverter (Deye/Sunsynk default registers)."""

    def __init__(self, modbus_cfg: dict, writer: SolarWriter):
        self._cfg = modbus_cfg
        self._writer = writer
        self._interval = modbus_cfg.get("poll_interval_s", 10)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _poll(self) -> SolarReading | None:
        regs = self._cfg.get("registers", {})
        client = ModbusTcpClient(
            host=self._cfg["host"],
            port=int(self._cfg.get("port", 502)),
            timeout=5,
        )
        if not client.connect():
            log.warning("Modbus connect failed: %s:%s", self._cfg["host"], self._cfg.get("port", 502))
            return None

        unit = int(self._cfg.get("unit_id", 1))
        try:
            def rd(key: str) -> float | None:
                return _read_register(client, regs[key], unit) if key in regs else None

            pv1 = rd("pv1_power_w") or 0.0
            pv2 = rd("pv2_power_w") or 0.0

            return SolarReading(
                pv_power_w=pv1 + pv2,
                battery_soc_pct=rd("battery_soc_pct") or 0.0,
                battery_power_w=rd("battery_power_w") or 0.0,
                load_power_w=rd("load_power_w") or 0.0,
                grid_power_w=rd("grid_power_w") or 0.0,
                battery_voltage_v=rd("battery_voltage_v"),
                inverter_temp_c=rd("inverter_temp_c"),
                daily_yield_kwh=rd("daily_yield_kwh"),
                source="modbus",
            )
        finally:
            client.close()

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
                log.error("Modbus poll error: %s", e)
            elapsed = time.monotonic() - start
            time.sleep(max(0, self._interval - elapsed))

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="modbus-solar")
        self._thread.start()
        log.info("Modbus solar collector started — %s:%s", self._cfg["host"], self._cfg.get("port", 502))

    def stop(self) -> None:
        self._stop.set()
