import logging
import os
import signal
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .alerter import OverflowAlerter
from .config_validator import ConfigValidator, ConfigValidationError
from .mqtt_collector import MQTTWaterCollector
from .notifier import Notifier, EmailNotifier, SMSNotifier, SyslogNotifier
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


def _init_notifier() -> Notifier:
    """Initialize notifier service from environment variables."""
    email_notifier = None
    sms_notifier = None
    syslog_notifier = None

    # Email configuration
    if os.environ.get("SMTP_HOST"):
        email_notifier = EmailNotifier(
            smtp_host=os.environ["SMTP_HOST"],
            smtp_port=int(os.environ.get("SMTP_PORT", 587)),
            from_address=os.environ.get("SMTP_FROM", "water-monitor@example.com"),
            to_addresses=os.environ.get("ALERT_EMAILS", "admin@example.com").split(","),
            username=os.environ.get("SMTP_USERNAME"),
            password=os.environ.get("SMTP_PASSWORD"),
        )
        log.info(
            "Email notifier enabled (to: %s)",
            os.environ.get("ALERT_EMAILS", "admin@example.com")
        )

    # SMS configuration (placeholder)
    if os.environ.get("ALERT_PHONE_NUMBERS"):
        sms_notifier = SMSNotifier(
            phone_numbers=os.environ["ALERT_PHONE_NUMBERS"].split(",")
        )
        log.info("SMS notifier enabled (requires provider configuration)")

    # Syslog is always available
    syslog_notifier = SyslogNotifier()
    log.info("Syslog notifier enabled")

    return Notifier(
        email_notifier=email_notifier,
        sms_notifier=sms_notifier,
        syslog_notifier=syslog_notifier,
    )


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
    alerter = OverflowAlerter()
    notifier = _init_notifier()

    mqtt_collector = MQTTWaterCollector(tanks, writer, alerter=alerter, notifier=notifier)
    tuya_collector = TuyaWaterCollector(tanks, tuya_devices, writer, alerter=alerter, notifier=notifier)

    mqtt_collector.start()
    tuya_collector.start()

    log.info("Water monitor running. Tanks: %s", [t["id"] for t in tanks])
    log.info("Phase 2 alerting enabled (alerter + notifier)")

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
