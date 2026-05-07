from __future__ import annotations

from .http_collector import LightingHTTPCollector
from .mqtt_collector import LightingMQTTCollector, load_config, run_until_stopped


def main() -> None:
    config = load_config()
    http_collector = LightingHTTPCollector(config)
    http_collector.start()
    try:
        run_until_stopped(LightingMQTTCollector(config))
    finally:
        http_collector.stop()


if __name__ == "__main__":
    main()
