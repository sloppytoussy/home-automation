import logging
import smtplib
import syslog
import time
from abc import ABC, abstractmethod
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from .alerter import OverflowAlert, AlertSeverity

log = logging.getLogger(__name__)


class NotificationChannel(ABC):
    """Abstract base for notification channels."""

    @abstractmethod
    def send(self, alert: OverflowAlert) -> bool:
        """Send alert notification. Returns True if successful."""
        pass


class EmailNotifier(NotificationChannel):
    """Send alerts via SMTP email."""

    SMTP_TIMEOUT_S = 10

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        from_address: str,
        to_addresses: list[str],
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_address = from_address
        self.to_addresses = to_addresses
        self.username = username
        self.password = password

    def send(self, alert: OverflowAlert, max_retries: int = 2) -> bool:
        """Send alert via email with exponential backoff retry."""
        msg = MIMEMultipart()
        msg["From"] = self.from_address
        msg["To"] = ", ".join(self.to_addresses)

        # Safe subject line: extract first line, limit length
        first_line = alert.message.split('\n')[0].split(':')[0][:60]
        msg["Subject"] = f"[{alert.severity.value}] {alert.tank_id}: {first_line}"

        body = f"""
Alert Severity: {alert.severity.value}
Tank ID: {alert.tank_id}
Overflow Handling: {alert.overflow_handling}
Overflow Magnitude: {alert.overflow_magnitude:.1f}L
Action: {alert.action.value}

Message:
{alert.message}
"""
        msg.attach(MIMEText(body, "plain"))

        for attempt in range(max_retries + 1):
            try:
                with smtplib.SMTP(
                    self.smtp_host, self.smtp_port, timeout=self.SMTP_TIMEOUT_S
                ) as server:
                    if self.username and self.password:
                        server.starttls(timeout=self.SMTP_TIMEOUT_S)
                        server.login(self.username, self.password)
                    server.send_message(msg)

                log.info("[%s] Email alert sent (recipients=%d)", alert.tank_id, len(self.to_addresses))
                return True

            except (smtplib.SMTPServerDisconnected, TimeoutError, OSError) as e:
                if attempt < max_retries:
                    backoff_s = 2 ** attempt
                    log.warning(
                        "[%s] Transient SMTP error (attempt %d/%d): %s, "
                        "retrying in %ds",
                        alert.tank_id, attempt + 1, max_retries + 1, e, backoff_s
                    )
                    time.sleep(backoff_s)
                    continue
                else:
                    log.error(
                        "[%s] Failed to send email after %d attempts: %s",
                        alert.tank_id, max_retries + 1, e
                    )
                    return False

            except smtplib.SMTPException as e:
                log.error("[%s] Non-retryable SMTP error: %s", alert.tank_id, e)
                return False
            except Exception as e:
                log.error("[%s] Failed to send email: %s", alert.tank_id, e)
                return False

        return False


class SMSNotifier(NotificationChannel):
    """Send alerts via SMS (placeholder for actual SMS provider integration)."""

    def __init__(self, phone_numbers: list[str], sms_provider_config: Optional[dict] = None):
        self.phone_numbers = phone_numbers
        self.config = sms_provider_config or {}

    def send(self, alert: OverflowAlert) -> bool:
        """Send alert via SMS."""
        try:
            message = (
                f"[{alert.severity.value}] {alert.tank_id}: "
                f"{alert.message[:100]}... "
                f"Magnitude: {alert.overflow_magnitude:.1f}L"
            )

            log.info(
                "[%s] SMS alert queued (recipients=%d, message_len=%d)",
                alert.tank_id, len(self.phone_numbers), len(message)
            )

            # TODO: Integrate with actual SMS provider (Twilio, AWS SNS, etc.)
            # For now, this is a stub that logs the intent
            return True

        except Exception as e:
            log.error("[%s] Failed to queue SMS: %s", alert.tank_id, e)
            return False


class SyslogNotifier(NotificationChannel):
    """Send alerts via syslog."""

    def __init__(self, facility: int = syslog.LOG_LOCAL0):
        self.facility = facility
        try:
            syslog.openlog(
                ident="water-monitor",
                logoption=syslog.LOG_PID,
                facility=facility,
            )
            self._syslog_available = True
        except Exception as e:
            log.warning("Syslog not available: %s", e)
            self._syslog_available = False

    def send(self, alert: OverflowAlert) -> bool:
        """Send alert to syslog."""
        try:
            if not self._syslog_available:
                log.warning("[%s] Syslog not available, skipping", alert.tank_id)
                return False

            # Map AlertSeverity to syslog priorities
            severity_map = {
                AlertSeverity.DEBUG: syslog.LOG_DEBUG,
                AlertSeverity.INFO: syslog.LOG_INFO,
                AlertSeverity.NOTICE: syslog.LOG_NOTICE,
                AlertSeverity.WARNING: syslog.LOG_WARNING,
                AlertSeverity.ERROR: syslog.LOG_ERR,
                AlertSeverity.CRITICAL: syslog.LOG_CRIT,
            }
            priority = severity_map.get(alert.severity, syslog.LOG_WARNING)

            syslog.syslog(
                priority,
                f"[{alert.tank_id}] {alert.message} "
                f"(action={alert.action.value}, magnitude={alert.overflow_magnitude:.1f}L)",
            )

            log.debug("[%s] Syslog alert sent (priority=%d)", alert.tank_id, priority)
            return True

        except Exception as e:
            log.error("[%s] Failed to send syslog: %s", alert.tank_id, e)
            return False


class Notifier:
    """
    Coordinates notification delivery across multiple channels.

    Sends alerts based on severity:
    - CRITICAL/ERROR/WARNING: Email + Syslog
    - CRITICAL only: SMS
    - All: Syslog
    """

    def __init__(
        self,
        email_notifier: Optional[EmailNotifier] = None,
        sms_notifier: Optional[SMSNotifier] = None,
        syslog_notifier: Optional[SyslogNotifier] = None,
    ):
        self.email = email_notifier
        self.sms = sms_notifier
        self.syslog = syslog_notifier
        self._sent_count = 0
        self._failed_count = 0

    def send_alert(self, alert: OverflowAlert) -> bool:
        """
        Send alert via configured channels based on severity.

        Returns True if at least one channel succeeded, False if all failed.
        """
        results = []
        alert_sent = False

        # Email for CRITICAL/ERROR/WARNING
        if alert.severity in [AlertSeverity.CRITICAL, AlertSeverity.ERROR, AlertSeverity.WARNING]:
            if self.email:
                if self.email.send(alert):
                    results.append(("email", True))
                    alert_sent = True
                else:
                    results.append(("email", False))

        # SMS for CRITICAL only
        if alert.severity == AlertSeverity.CRITICAL:
            if self.sms:
                if self.sms.send(alert):
                    results.append(("sms", True))
                    alert_sent = True
                else:
                    results.append(("sms", False))

        # Syslog for all severities
        if self.syslog:
            if self.syslog.send(alert):
                results.append(("syslog", True))
                alert_sent = True
            else:
                results.append(("syslog", False))

        # Track metrics
        successful_channels = [r[0] for r in results if r[1]]
        failed_channels = [r[0] for r in results if not r[1]]

        if alert_sent:
            self._sent_count += 1
            log.info(
                "[%s] Alert sent via: %s (failed: %s)",
                alert.tank_id, successful_channels, failed_channels if failed_channels else "none"
            )
        else:
            self._failed_count += 1
            log.error(
                "[%s] Alert failed on all channels: %s",
                alert.tank_id, failed_channels
            )

        return alert_sent

    def get_stats(self) -> dict:
        """Return notifier statistics."""
        return {
            "sent_count": self._sent_count,
            "failed_count": self._failed_count,
        }

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._sent_count = 0
        self._failed_count = 0
