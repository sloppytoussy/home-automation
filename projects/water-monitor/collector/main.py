import logging
import signal
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .config_validator import ConfigValidator, ConfigValidationError
from .mqtt_collector import MQTTWaterCollector
from .tuya_collector import TuyaWaterCollector
from .writer import WaterWriter

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "tanks.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def main() -> None:
    cfg = load_config()

    try:
        ConfigValidator.validate_config(cfg)
        ConfigValidator.log_summary(cfg)
    except ConfigValidationError as e:
        log.error("Configuration validation failed: %s", e)
        sys.exit(1)

    tanks = cfg["tanks"]
    tuya_devices = cfg.get("tuya_devices", [])

    writer = WaterWriter()
    mqtt_collector = MQTTWaterCollector(tanks, writer)
    tuya_collector = TuyaWaterCollector(tanks, tuya_devices, writer)

    mqtt_collector.start()
    tuya_collector.start()

    log.info("Water monitor running. Tanks: %s", [t["id"] for t in tanks])

    def _shutdown(sig, frame):
        log.info("Shutting down…")
        mqtt_collector.stop()
        tuya_collector.stop()
        writer.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
