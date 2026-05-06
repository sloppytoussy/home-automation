import logging
from enum import Enum
from typing import Optional

from .calculator import TankReading

log = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels (RFC 5424 compatible)."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    NOTICE = "NOTICE"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AlertAction(Enum):
    """Actions to take when overflow is detected."""
    LOG_ONLY = "log_only"
    ALERT = "alert"
    ALERT_AND_SHUTOFF = "alert_and_shutoff"


class OverflowAlert:
    """Represents an overflow alert event."""

    def __init__(
        self,
        tank_id: str,
        severity: AlertSeverity,
        action: AlertAction,
        message: str,
        overflow_magnitude: float,
        overflow_handling: str,
        is_critical: bool,
    ):
        self.tank_id = tank_id
        self.severity = severity
        self.action = action
        self.message = message
        self.overflow_magnitude = overflow_magnitude
        self.overflow_handling = overflow_handling
        self.is_critical = is_critical


class OverflowAlerter:
    """
    Interprets overflow conditions and generates alerts based on tank configuration.

    Decision Logic:
    - no_outlet (float valve controlled): Overflow = inlet failure → CRITICAL alert
    - open_outlet (safe outlet): Overflow = outlet working/heavy rain → INFO alert
    """

    # Default severity mapping based on overflow_handling
    DEFAULT_SEVERITY_MAP = {
        "no_outlet": AlertSeverity.CRITICAL,
        "open_outlet": AlertSeverity.INFO,
    }

    # Default action mapping based on overflow_handling
    DEFAULT_ACTION_MAP = {
        "no_outlet": AlertAction.ALERT_AND_SHUTOFF,
        "open_outlet": AlertAction.LOG_ONLY,
    }

    def __init__(self):
        self._alert_queue: list[OverflowAlert] = []

    def check_overflow(
        self,
        tank_cfg: dict,
        reading: TankReading,
        overflow_detected: bool,
        overflow_magnitude: Optional[float] = None,
    ) -> Optional[OverflowAlert]:
        """
        Evaluate overflow condition and generate alert if needed.

        Args:
            tank_cfg: Tank configuration dictionary
            reading: TankReading object with volume and capacity
            overflow_detected: Whether overflow was detected
            overflow_magnitude: Magnitude of overflow in liters (auto-calculated if None)

        Returns:
            OverflowAlert if alert should be generated, None otherwise
        """
        tank_id = tank_cfg["id"]

        if not overflow_detected:
            return None

        # Calculate overflow magnitude if not provided
        if overflow_magnitude is None:
            overflow_magnitude = reading.volume_liters - reading.capacity_liters

        overflow_handling = tank_cfg.get("overflow_handling", "unknown")
        is_critical = tank_cfg.get("is_critical", False)
        alerting_enabled = tank_cfg.get("alerting_enabled", True)

        # Determine severity: use custom override if provided, else use default
        if "alert_severity" in tank_cfg:
            try:
                severity = AlertSeverity[tank_cfg["alert_severity"]]
            except KeyError:
                log.error(
                    "[%s] Invalid alert_severity '%s', using default",
                    tank_id, tank_cfg["alert_severity"]
                )
                severity = self.DEFAULT_SEVERITY_MAP.get(overflow_handling, AlertSeverity.WARNING)
        else:
            severity = self.DEFAULT_SEVERITY_MAP.get(overflow_handling, AlertSeverity.WARNING)

        # Determine action based on overflow_handling
        action = self.DEFAULT_ACTION_MAP.get(overflow_handling, AlertAction.LOG_ONLY)

        # Build alert message
        if overflow_handling == "no_outlet":
            message = (
                f"TANK {tank_id} OVERFLOW - Float valve failure detected. "
                f"Volume exceeded capacity by {overflow_magnitude:.1f}L. "
                f"AUTO-SHUTOFF valve triggered."
            )
        elif overflow_handling == "open_outlet":
            message = (
                f"TANK {tank_id} outlet active - Safe overflow detected. "
                f"Volume exceeded capacity by {overflow_magnitude:.1f}L. "
                f"(Normal operation during heavy rain)"
            )
        else:
            message = (
                f"TANK {tank_id} overflow: volume={reading.volume_liters:.1f}L "
                f"(capacity={reading.capacity_liters:.1f}L, "
                f"magnitude={overflow_magnitude:.1f}L)"
            )

        alert = OverflowAlert(
            tank_id=tank_id,
            severity=severity,
            action=action,
            message=message,
            overflow_magnitude=overflow_magnitude,
            overflow_handling=overflow_handling,
            is_critical=is_critical,
        )

        # Log the alert decision
        # Map AlertSeverity to logging levels (NOTICE → INFO since it's not in stdlib)
        log_level_map = {
            AlertSeverity.DEBUG: logging.DEBUG,
            AlertSeverity.INFO: logging.INFO,
            AlertSeverity.NOTICE: logging.INFO,
            AlertSeverity.WARNING: logging.WARNING,
            AlertSeverity.ERROR: logging.ERROR,
            AlertSeverity.CRITICAL: logging.CRITICAL,
        }
        log_level = log_level_map.get(severity, logging.WARNING)

        log.log(
            log_level,
            "[%s] %s (severity=%s, action=%s, alerting=%s)",
            tank_id, message, severity.value, action.value, alerting_enabled,
        )

        # Check if alerting is enabled for this tank
        if not alerting_enabled:
            log.info("[%s] Alerting disabled (test mode) — alert suppressed", tank_id)
            return None

        return alert

    def queue_alert(self, alert: OverflowAlert) -> None:
        """Queue an alert for the notifier service."""
        self._alert_queue.append(alert)
        log.debug(
            "[%s] Alert queued (queue_size=%d)",
            alert.tank_id, len(self._alert_queue)
        )

    def get_queued_alerts(self) -> list[OverflowAlert]:
        """Get all queued alerts and clear the queue."""
        alerts = self._alert_queue
        self._alert_queue = []
        return alerts

    def has_queued_alerts(self) -> bool:
        """Check if there are queued alerts."""
        return len(self._alert_queue) > 0
