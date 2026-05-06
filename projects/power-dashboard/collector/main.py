from __future__ import annotations

from .mqtt_collector import PowerMQTTCollector, load_config, run_until_stopped


def main() -> None:
    collector = PowerMQTTCollector(load_config())
    run_until_stopped(collector)


if __name__ == "__main__":
    main()
