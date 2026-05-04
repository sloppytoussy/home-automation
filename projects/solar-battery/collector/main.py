import logging
import signal
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .writer import SolarWriter

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "inverter.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def main() -> None:
    cfg = load_config()
    collector_type = cfg["collector"]["type"]
    writer = SolarWriter()
    collector = None

    if collector_type == "mqtt":
        from .mqtt_collector import MQTTSolarCollector
        collector = MQTTSolarCollector(cfg["mqtt"]["topics"], writer)

    elif collector_type == "modbus":
        from .modbus_collector import ModbusSolarCollector
        modbus_cfg = cfg["modbus"]
        modbus_cfg["poll_interval_s"] = cfg["collector"].get("poll_interval_s", 10)
        collector = ModbusSolarCollector(modbus_cfg, writer)

    elif collector_type == "solarman":
        from .solarman_collector import SolarManCollector
        sm_cfg = cfg["solarman"]
        sm_cfg["poll_interval_s"] = cfg["collector"].get("poll_interval_s", 30)
        collector = SolarManCollector(sm_cfg, writer)

    else:
        log.error("Unknown collector type: %s", collector_type)
        sys.exit(1)

    collector.start()
    log.info("Solar collector running — type=%s", collector_type)

    def _shutdown(sig, frame):
        log.info("Shutting down…")
        collector.stop()
        writer.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
