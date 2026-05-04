import time
import requests


class PiHoleClient:
    """Pi-hole v6 REST API client with automatic session renewal."""

    def __init__(self, host: str, password: str, port: int = 80, tls: bool = False):
        scheme = "https" if tls else "http"
        self.base_url = f"{scheme}://{host}:{port}/api"
        self.password = password
        self._sid: str | None = None
        self._sid_expires: float = 0

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _authenticate(self) -> None:
        resp = requests.post(
            f"{self.base_url}/auth",
            json={"password": self.password},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        session = data.get("session", {})
        if not session.get("valid"):
            raise RuntimeError(f"Pi-hole auth failed: {session.get('message')}")
        self._sid = session["sid"]
        # validity is in seconds; subtract 60s buffer
        self._sid_expires = time.time() + session.get("validity", 1800) - 60

    def _ensure_auth(self) -> None:
        if not self._sid or time.time() >= self._sid_expires:
            self._authenticate()

    def _headers(self) -> dict:
        self._ensure_auth()
        return {"Authorization": f"Bearer {self._sid}"}

    def _get(self, endpoint: str, params: dict = None) -> dict:
        resp = requests.get(
            f"{self.base_url}/{endpoint}",
            headers=self._headers(),
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # API endpoints
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        """Overall stats: total queries, blocked, unique domains/clients."""
        return self._get("stats/summary")

    def top_domains(self, count: int = 10) -> dict:
        """Top permitted domains."""
        return self._get("stats/top_domains", {"count": count})

    def top_blocked(self, count: int = 10) -> dict:
        """Top blocked domains."""
        return self._get("stats/top_blocked", {"count": count})

    def top_clients(self, count: int = 10) -> dict:
        """Top clients by query count."""
        return self._get("stats/top_clients", {"count": count})

    def query_types(self) -> dict:
        """Breakdown of DNS query types (A, AAAA, CNAME, etc.)."""
        return self._get("stats/query_types")

    def upstreams(self) -> dict:
        """Upstream DNS server response stats."""
        return self._get("stats/upstreams")

    def history(self) -> dict:
        """Query count history over the last 24 hours (10-min buckets)."""
        return self._get("history")

    def recent_queries(self, limit: int = 50) -> dict:
        """Most recent DNS queries."""
        return self._get("queries", {"limit": limit})
