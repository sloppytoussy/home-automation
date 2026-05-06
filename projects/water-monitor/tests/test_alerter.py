import pytest
from collector.alerter import (
    OverflowAlerter, OverflowAlert, AlertSeverity, AlertAction
)
from collector.calculator import TankReading


@pytest.fixture
def alerter():
    """Create an alerter instance."""
    return OverflowAlerter()


@pytest.fixture
def tank_cfg_no_outlet():
    """Tank configuration with no_outlet (float valve controlled)."""
    return {
        "id": "tank1",
        "depth_cm": 180,
        "capacity_liters": 5000,
        "overflow_handling": "no_outlet",
        "inlet_shutoff": "float_valve",
        "num_sources": "single",
        "is_critical": True,
        "alerting_enabled": True,
    }


@pytest.fixture
def tank_cfg_open_outlet():
    """Tank configuration with open_outlet (safe outlet)."""
    return {
        "id": "tank2",
        "depth_cm": 350,
        "capacity_liters": 14700,
        "overflow_handling": "open_outlet",
        "inlet_shutoff": "float_valve",
        "num_sources": "multiple",
        "is_critical": False,
        "alerting_enabled": True,
    }


@pytest.fixture
def overflow_reading():
    """Tank reading with overflow condition."""
    return TankReading(
        tank_id="tank1",
        distance_raw_cm=-5.0,
        level_cm=190.0,
        level_pct=100.0,
        volume_liters=5250.0,
        usable_depth_cm=180.0,
        capacity_liters=5000.0,
    )


@pytest.fixture
def normal_reading():
    """Tank reading without overflow."""
    return TankReading(
        tank_id="tank1",
        distance_raw_cm=50.0,
        level_cm=45.0,
        level_pct=50.0,
        volume_liters=2500.0,
        usable_depth_cm=180.0,
        capacity_liters=5000.0,
    )


class TestOverflowAlerter:
    """Tests for OverflowAlerter decision logic."""

    def test_no_alert_when_no_overflow(self, alerter, tank_cfg_no_outlet, normal_reading):
        """No overflow condition should return None."""
        alert = alerter.check_overflow(
            tank_cfg_no_outlet, normal_reading, overflow_detected=False
        )
        assert alert is None

    def test_critical_alert_no_outlet_overflow(
        self, alerter, tank_cfg_no_outlet, overflow_reading
    ):
        """no_outlet overflow should generate CRITICAL alert with shutoff action."""
        alert = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True
        )

        assert alert is not None
        assert alert.tank_id == "tank1"
        assert alert.severity == AlertSeverity.CRITICAL
        assert alert.action == AlertAction.ALERT_AND_SHUTOFF
        assert alert.is_critical is True
        assert "Float valve failure" in alert.message
        assert "manual shutoff required" in alert.message

    def test_info_alert_open_outlet_overflow(
        self, alerter, tank_cfg_open_outlet, overflow_reading
    ):
        """open_outlet overflow should generate INFO alert (normal operation)."""
        # Update reading for tank2
        overflow_reading.tank_id = "tank2"
        overflow_reading.capacity_liters = 14700

        alert = alerter.check_overflow(
            tank_cfg_open_outlet, overflow_reading, overflow_detected=True
        )

        assert alert is not None
        assert alert.tank_id == "tank2"
        assert alert.severity == AlertSeverity.INFO
        assert alert.action == AlertAction.LOG_ONLY
        assert alert.is_critical is False
        assert "outlet active" in alert.message

    def test_overflow_magnitude_calculation(
        self, alerter, tank_cfg_no_outlet, overflow_reading
    ):
        """Overflow magnitude should be calculated correctly."""
        alert = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True
        )

        assert alert is not None
        assert alert.overflow_magnitude == 250.0  # 5250 - 5000

    def test_overflow_magnitude_provided(
        self, alerter, tank_cfg_no_outlet, overflow_reading
    ):
        """Provided overflow magnitude should be used."""
        alert = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True,
            overflow_magnitude=123.45
        )

        assert alert is not None
        assert alert.overflow_magnitude == 123.45

    def test_custom_severity_override(self, alerter, tank_cfg_no_outlet, overflow_reading):
        """Custom alert_severity should override default."""
        tank_cfg_no_outlet["alert_severity"] = "WARNING"

        alert = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True
        )

        assert alert is not None
        assert alert.severity == AlertSeverity.WARNING

    def test_custom_severity_all_levels(
        self, alerter, tank_cfg_no_outlet, overflow_reading
    ):
        """Custom severity should support all AlertSeverity levels."""
        for severity_str in ["DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL"]:
            tank_cfg_no_outlet["alert_severity"] = severity_str

            alert = alerter.check_overflow(
                tank_cfg_no_outlet, overflow_reading, overflow_detected=True
            )

            assert alert is not None
            assert alert.severity == AlertSeverity[severity_str]

    def test_invalid_custom_severity_fallback(
        self, alerter, tank_cfg_no_outlet, overflow_reading
    ):
        """Invalid custom severity should fallback to default."""
        tank_cfg_no_outlet["alert_severity"] = "INVALID_LEVEL"

        alert = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True
        )

        assert alert is not None
        # Should fallback to no_outlet default: CRITICAL
        assert alert.severity == AlertSeverity.CRITICAL

    def test_alerting_disabled_test_mode(
        self, alerter, tank_cfg_no_outlet, overflow_reading
    ):
        """When alerting_enabled=False, alert should be suppressed."""
        tank_cfg_no_outlet["alerting_enabled"] = False

        alert = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True
        )

        # Alert suppressed in test mode
        assert alert is None

    def test_queue_and_retrieve_alerts(self, alerter, tank_cfg_no_outlet, overflow_reading):
        """Alerts should be queued and retrievable."""
        alert1 = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True
        )
        assert alert1 is not None

        alerter.queue_alert(alert1)
        assert alerter.has_queued_alerts() is True

        alerts = alerter.get_queued_alerts()
        assert len(alerts) == 1
        assert alerts[0].tank_id == "tank1"

        # Queue should be empty after retrieval
        assert alerter.has_queued_alerts() is False

    def test_queue_multiple_alerts(self, alerter, tank_cfg_no_outlet, tank_cfg_open_outlet, overflow_reading):
        """Multiple alerts should be queued in order."""
        # Create two alerts from different tanks
        alert1 = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True
        )
        assert alert1 is not None

        overflow_reading.tank_id = "tank2"
        overflow_reading.capacity_liters = 14700
        alert2 = alerter.check_overflow(
            tank_cfg_open_outlet, overflow_reading, overflow_detected=True
        )
        assert alert2 is not None

        alerter.queue_alert(alert1)
        alerter.queue_alert(alert2)

        alerts = alerter.get_queued_alerts()
        assert len(alerts) == 2
        assert alerts[0].tank_id == "tank1"
        assert alerts[1].tank_id == "tank2"

    def test_critical_tank_flag_preserved(
        self, alerter, tank_cfg_no_outlet, overflow_reading
    ):
        """Critical tank flag should be preserved in alert."""
        tank_cfg_no_outlet["is_critical"] = True
        alert = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True
        )

        assert alert is not None
        assert alert.is_critical is True

        tank_cfg_no_outlet["is_critical"] = False
        alert = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True
        )

        assert alert is not None
        assert alert.is_critical is False

    def test_alert_properties(self, alerter, tank_cfg_no_outlet, overflow_reading):
        """Alert should have all expected properties."""
        alert = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True,
            overflow_magnitude=250.0
        )

        assert alert is not None
        assert hasattr(alert, "tank_id")
        assert hasattr(alert, "severity")
        assert hasattr(alert, "action")
        assert hasattr(alert, "message")
        assert hasattr(alert, "overflow_magnitude")
        assert hasattr(alert, "overflow_handling")
        assert hasattr(alert, "is_critical")

    def test_no_outlet_message_format(
        self, alerter, tank_cfg_no_outlet, overflow_reading
    ):
        """no_outlet alert message should follow expected format."""
        alert = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True,
            overflow_magnitude=100.0
        )

        assert alert is not None
        assert "tank1" in alert.message.lower()
        assert "overflow" in alert.message.lower()
        assert "float valve failure" in alert.message.lower()
        assert "100.0l" in alert.message.lower()
        assert "manual shutoff required" in alert.message.lower()

    def test_open_outlet_message_format(
        self, alerter, tank_cfg_open_outlet, overflow_reading
    ):
        """open_outlet alert message should follow expected format."""
        overflow_reading.tank_id = "tank2"
        overflow_reading.capacity_liters = 14700

        alert = alerter.check_overflow(
            tank_cfg_open_outlet, overflow_reading, overflow_detected=True,
            overflow_magnitude=100.0
        )

        assert alert is not None
        assert "tank2" in alert.message.lower()
        assert "outlet" in alert.message.lower()
        assert "heavy rain" in alert.message.lower()

    def test_unknown_overflow_handling(self, alerter):
        """Unknown overflow_handling should use WARNING default."""
        tank_cfg = {
            "id": "tank_unknown",
            "overflow_handling": "unknown_type",
            "is_critical": False,
            "alerting_enabled": True,
        }
        reading = TankReading(
            tank_id="tank_unknown",
            distance_raw_cm=-5.0,
            level_cm=190.0,
            level_pct=100.0,
            volume_liters=5250.0,
            usable_depth_cm=180.0,
            capacity_liters=5000.0,
        )

        alert = alerter.check_overflow(
            tank_cfg, reading, overflow_detected=True
        )

        assert alert is not None
        # Should default to WARNING when unknown
        assert alert.severity == AlertSeverity.WARNING
        assert alert.action == AlertAction.LOG_ONLY

    def test_alerting_enabled_default_true(self, alerter, tank_cfg_no_outlet, overflow_reading):
        """alerting_enabled should default to True."""
        # Remove alerting_enabled from config
        del tank_cfg_no_outlet["alerting_enabled"]

        alert = alerter.check_overflow(
            tank_cfg_no_outlet, overflow_reading, overflow_detected=True
        )

        # Should generate alert by default
        assert alert is not None
