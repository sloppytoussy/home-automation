import logging
import os
import time

from dotenv import load_dotenv

from .pihole import PiHoleClient
from .writer import InfluxWriter

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

POLL_INTERVAL = int(os.environ.get("DNS_POLL_INTERVAL", 30))


def collect_once(pihole: PiHoleClient, writer: InfluxWriter) -> None:
    try:
        writer.write_summary(pihole.summary())
        log.debug("summary written")
    except Exception as e:
        log.warning("summary failed: %s", e)

    try:
        writer.write_top_domains(pihole.top_domains(10))
        log.debug("top_domains written")
    except Exception as e:
        log.warning("top_domains failed: %s", e)

    try:
        writer.write_top_blocked(pihole.top_blocked(10))
        log.debug("top_blocked written")
    except Exception as e:
        log.warning("top_blocked failed: %s", e)

    try:
        writer.write_top_clients(pihole.top_clients(10))
        log.debug("top_clients written")
    except Exception as e:
        log.warning("top_clients failed: %s", e)

    try:
        writer.write_query_types(pihole.query_types())
        log.debug("query_types written")
    except Exception as e:
        log.warning("query_types failed: %s", e)

    try:
        writer.write_upstreams(pihole.upstreams())
        log.debug("upstreams written")
    except Exception as e:
        log.warning("upstreams failed: %s", e)


def main() -> None:
    pihole = PiHoleClient(
        host=os.environ["PIHOLE_HOST"],
        password=os.environ["PIHOLE_PASSWORD"],
        port=int(os.environ.get("PIHOLE_PORT", 80)),
        tls=os.environ.get("PIHOLE_TLS", "false").lower() == "true",
    )
    writer = InfluxWriter()

    log.info("DNS collector started — polling every %ds", POLL_INTERVAL)
    try:
        while True:
            start = time.monotonic()
            try:
                collect_once(pihole, writer)
                log.info("poll complete (%.1fs)", time.monotonic() - start)
            except Exception as e:
                log.error("poll error: %s", e)
            time.sleep(max(0, POLL_INTERVAL - (time.monotonic() - start)))
    finally:
        writer.close()


if __name__ == "__main__":
    main()
