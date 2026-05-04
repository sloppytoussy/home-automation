from unittest.mock import MagicMock, patch

import pytest

from collector.pihole import PiHoleClient


@pytest.fixture
def client():
    return PiHoleClient(host="192.168.1.1", password="testpass")


def _mock_auth(requests_mock):
    requests_mock.post(
        "http://192.168.1.1:80/api/auth",
        json={"session": {"valid": True, "sid": "abc123", "validity": 1800, "message": ""}},
    )


def test_summary(requests_mock, client):
    _mock_auth(requests_mock)
    requests_mock.get(
        "http://192.168.1.1:80/api/stats/summary",
        json={"queries": {"total": 1000, "blocked": 100, "percent_blocked": 10.0}},
    )
    result = client.summary()
    assert result["queries"]["total"] == 1000


def test_top_domains(requests_mock, client):
    _mock_auth(requests_mock)
    requests_mock.get(
        "http://192.168.1.1:80/api/stats/top_domains",
        json={"domains": {"example.com": 50, "google.com": 30}},
    )
    result = client.top_domains(10)
    assert "example.com" in result["domains"]


def test_auth_failure_raises(requests_mock, client):
    requests_mock.post(
        "http://192.168.1.1:80/api/auth",
        json={"session": {"valid": False, "sid": "", "validity": 0, "message": "Wrong password"}},
    )
    with pytest.raises(RuntimeError, match="Wrong password"):
        client.summary()
