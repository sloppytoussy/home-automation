from __future__ import annotations

from .mqtt_collector import LightingMQTTCollector, load_config, run_until_stopped


def main() -> None:
    run_until_stopped(LightingMQTTCollector(load_config()))


if __name__ == "__main__":
    main()
