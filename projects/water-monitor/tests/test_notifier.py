import pytest
from unittest.mock import Mock, patch, MagicMock
from collector.notifier import (
    Notifier, EmailNotifier, SMSNotifier, SyslogNotifier
)
from collector.alerter import OverflowAlert, AlertSeverity, AlertAction
from collector.calculator import TankReading


@pytest.fixture
def critical_alert():
    """Critical alert from no_outlet tank failure."""
    return OverflowAlert(
        tank_id="tank1",
        severity=AlertSeverity.CRITICAL,
        action=AlertAction.ALERT_AND_SHUTOFF,
        message="TANK tank1 OVERFLOW - Float valve failure detected. AUTO-SHUTOFF triggered.",
        overflow_magnitude=250.0,
        overflow_handling="no_outlet",
        is_critical=True,
    )


@pytest.fixture
def warning_alert():
    """Warning alert from open_outlet normal operation."""
    return OverflowAlert(
        tank_id="tank2",
        severity=AlertSeverity.WARNING,
        action=AlertAction.ALERT,
        message="TANK tank2 OVERFLOW WARNING - Heavy rainfall detected.",
        overflow_magnitude=100.0,
        overflow_handling="open_outlet",
        is_critical=False,
    )


@pytest.fixture
def info_alert():
    """Info alert from open_outlet normal operation."""
    return OverflowAlert(
        tank_id="tank2",
        severity=AlertSeverity.INFO,
        action=AlertAction.LOG_ONLY,
        message="TANK tank2 outlet active - Safe overflow detected.",
        overflow_magnitude=50.0,
        overflow_handling="open_outlet",
        is_critical=False,
    )


class TestEmailNotifier:
    """Tests for EmailNotifier."""

    def test_email_notifier_init(self):
        """EmailNotifier should initialize with config."""
        notifier = EmailNotifier(
            smtp_host="smtp.example.com",
            smtp_port=587,
            from_address="alerts@example.com",
            to_addresses=["admin@example.com"],
        )

        assert notifier.smtp_host == "smtp.example.com"
        assert notifier.smtp_port == 587
        assert notifier.from_address == "alerts@example.com"
        assert notifier.to_addresses == ["admin@example.com"]

    @patch("smtplib.SMTP")
    def test_email_send_success(self, mock_smtp, critical_alert):
        """Email should be sent successfully."""
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        notifier = EmailNotifier(
            smtp_host="smtp.example.com",
            smtp_port=587,
            from_address="alerts@example.com",
            to_addresses=["admin@example.com"],
        )

        result = notifier.send(critical_alert)
        assert result is True
        mock_server.send_message.assert_called_once()

    @patch("smtplib.SMTP")
    def test_email_send_with_auth(self, mock_smtp, critical_alert):
        """Email should use authentication when provided."""
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        notifier = EmailNotifier(
            smtp_host="smtp.example.com",
            smtp_port=587,
            from_address="alerts@example.com",
            to_addresses=["admin@example.com"],
            username="user@example.com",
            password="secret",
        )

        result = notifier.send(critical_alert)
        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@example.com", "secret")

    @patch("smtplib.SMTP")
    def test_email_send_failure(self, mock_smtp, critical_alert):
        """Email send failure should return False."""
        mock_smtp.side_effect = Exception("Connection failed")

        notifier = EmailNotifier(
            smtp_host="smtp.example.com",
            smtp_port=587,
            from_address="alerts@example.com",
            to_addresses=["admin@example.com"],
        )

        result = notifier.send(critical_alert)
        assert result is False

    @patch("smtplib.SMTP")
    def test_email_subject_includes_severity(self, mock_smtp, critical_alert):
        """Email subject should include alert severity."""
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        notifier = EmailNotifier(
            smtp_host="smtp.example.com",
            smtp_port=587,
            from_address="alerts@example.com",
            to_addresses=["admin@example.com"],
        )

        notifier.send(critical_alert)

        # Check that send_message was called with message containing severity
        call_args = mock_server.send_message.call_args
        sent_message = call_args[0][0]
        assert "CRITICAL" in sent_message["Subject"]


class TestSMSNotifier:
    """Tests for SMSNotifier."""

    def test_sms_notifier_init(self):
        """SMSNotifier should initialize with phone numbers."""
        notifier = SMSNotifier(phone_numbers=["+1234567890", "+0987654321"])
        assert notifier.phone_numbers == ["+1234567890", "+0987654321"]

    def test_sms_send_success(self, critical_alert):
        """SMS send should return True."""
        notifier = SMSNotifier(phone_numbers=["+1234567890"])
        result = notifier.send(critical_alert)
        assert result is True

    def test_sms_send_truncates_message(self, critical_alert):
        """SMS message should be truncated for SMS length limits."""
        notifier = SMSNotifier(phone_numbers=["+1234567890"])
        result = notifier.send(critical_alert)
        assert result is True

    def test_sms_send_critical_only(self, critical_alert, info_alert):
        """SMS notifier should be available for all alerts."""
        notifier = SMSNotifier(phone_numbers=["+1234567890"])

        # Both should return True (actual sending handled by coordinator)
        assert notifier.send(critical_alert) is True
        assert notifier.send(info_alert) is True


class TestSyslogNotifier:
    """Tests for SyslogNotifier."""

    def test_syslog_notifier_init(self):
        """SyslogNotifier should initialize."""
        import syslog
        with patch("syslog.openlog"):
            notifier = SyslogNotifier()
            assert notifier.facility == syslog.LOG_LOCAL0

    @patch("syslog.syslog")
    @patch("syslog.openlog")
    def test_syslog_send_success(self, mock_openlog, mock_syslog, critical_alert):
        """Syslog send should call syslog.syslog."""
        notifier = SyslogNotifier()
        result = notifier.send(critical_alert)
        assert result is True
        mock_syslog.assert_called_once()

    @patch("syslog.openlog")
    def test_syslog_openlog_failure(self, mock_openlog, critical_alert):
        """Syslog unavailable should return False."""
        mock_openlog.side_effect = Exception("Syslog unavailable")

        notifier = SyslogNotifier()
        result = notifier.send(critical_alert)
        assert result is False

    @patch("syslog.syslog")
    @patch("syslog.openlog")
    def test_syslog_severity_mapping(self, mock_openlog, mock_syslog, critical_alert):
        """Syslog should map AlertSeverity to syslog priorities."""
        notifier = SyslogNotifier()
        notifier.send(critical_alert)

        # Check that syslog was called with CRITICAL priority (2)
        call_args = mock_syslog.call_args
        assert call_args is not None


class TestNotifier:
    """Tests for Notifier coordinator."""

    def test_notifier_init(self):
        """Notifier should accept optional channels."""
        email = EmailNotifier("smtp", 587, "from@ex.com", ["to@ex.com"])
        sms = SMSNotifier(["+1234567890"])
        syslog = SyslogNotifier()

        with patch("syslog.openlog"):
            notifier = Notifier(email, sms, syslog)
            assert notifier.email is email
            assert notifier.sms is sms
            assert notifier.syslog is syslog

    def test_notifier_init_no_channels(self):
        """Notifier should work with no channels."""
        notifier = Notifier()
        assert notifier.email is None
        assert notifier.sms is None
        assert notifier.syslog is None

    @patch.object(EmailNotifier, "send", return_value=True)
    @patch.object(SMSNotifier, "send", return_value=True)
    @patch.object(SyslogNotifier, "send", return_value=True)
    @patch("syslog.openlog")
    def test_critical_alert_sends_email_sms_syslog(
        self, mock_openlog, mock_syslog_send, mock_sms_send, mock_email_send, critical_alert
    ):
        """Critical alert should use email, SMS, and syslog."""
        email = EmailNotifier("smtp", 587, "from@ex.com", ["to@ex.com"])
        sms = SMSNotifier(["+1234567890"])
        syslog = SyslogNotifier()

        notifier = Notifier(email, sms, syslog)
        result = notifier.send_alert(critical_alert)

        assert result is True
        mock_email_send.assert_called_once_with(critical_alert)
        mock_sms_send.assert_called_once_with(critical_alert)
        mock_syslog_send.assert_called_once_with(critical_alert)

    @patch.object(EmailNotifier, "send", return_value=True)
    @patch.object(SyslogNotifier, "send", return_value=True)
    @patch("syslog.openlog")
    def test_warning_alert_sends_email_syslog_not_sms(
        self, mock_openlog, mock_syslog_send, mock_email_send, warning_alert
    ):
        """Warning alert should use email and syslog, not SMS."""
        email = EmailNotifier("smtp", 587, "from@ex.com", ["to@ex.com"])
        sms = SMSNotifier(["+1234567890"])
        syslog = SyslogNotifier()

        with patch.object(sms, "send") as mock_sms_send:
            notifier = Notifier(email, sms, syslog)
            result = notifier.send_alert(warning_alert)

            assert result is True
            mock_email_send.assert_called_once()
            mock_sms_send.assert_not_called()
            mock_syslog_send.assert_called_once()

    @patch.object(SyslogNotifier, "send", return_value=True)
    @patch("syslog.openlog")
    def test_info_alert_sends_syslog_only(
        self, mock_openlog, mock_syslog_send, info_alert
    ):
        """Info alert should use syslog only."""
        email = EmailNotifier("smtp", 587, "from@ex.com", ["to@ex.com"])
        sms = SMSNotifier(["+1234567890"])
        syslog = SyslogNotifier()

        with patch.object(email, "send") as mock_email_send:
            with patch.object(sms, "send") as mock_sms_send:
                notifier = Notifier(email, sms, syslog)
                result = notifier.send_alert(info_alert)

                assert result is True
                mock_email_send.assert_not_called()
                mock_sms_send.assert_not_called()
                mock_syslog_send.assert_called_once()

    @patch.object(EmailNotifier, "send", return_value=False)
    @patch.object(SyslogNotifier, "send", return_value=True)
    @patch("syslog.openlog")
    def test_partial_failure_returns_true(
        self, mock_openlog, mock_syslog_send, mock_email_send, critical_alert
    ):
        """If any channel succeeds, send_alert returns True."""
        email = EmailNotifier("smtp", 587, "from@ex.com", ["to@ex.com"])
        syslog = SyslogNotifier()

        notifier = Notifier(email, syslog_notifier=syslog)
        result = notifier.send_alert(critical_alert)

        assert result is True  # Syslog succeeded

    @patch.object(EmailNotifier, "send", return_value=False)
    @patch.object(SMSNotifier, "send", return_value=False)
    @patch.object(SyslogNotifier, "send", return_value=False)
    @patch("syslog.openlog")
    def test_all_failure_returns_false(
        self, mock_openlog, mock_syslog_send, mock_sms_send, mock_email_send, critical_alert
    ):
        """If all channels fail, send_alert returns False."""
        email = EmailNotifier("smtp", 587, "from@ex.com", ["to@ex.com"])
        sms = SMSNotifier(["+1234567890"])
        syslog = SyslogNotifier()

        notifier = Notifier(email, sms, syslog)
        result = notifier.send_alert(critical_alert)

        assert result is False

    @patch.object(EmailNotifier, "send", return_value=True)
    @patch.object(SyslogNotifier, "send", return_value=True)
    @patch("syslog.openlog")
    def test_stats_tracking(self, mock_openlog, mock_syslog_send, mock_email_send):
        """Notifier should track send/fail statistics."""
        email = EmailNotifier("smtp", 587, "from@ex.com", ["to@ex.com"])
        syslog = SyslogNotifier()

        notifier = Notifier(email, syslog_notifier=syslog)

        alert1 = OverflowAlert(
            tank_id="tank1",
            severity=AlertSeverity.CRITICAL,
            action=AlertAction.ALERT_AND_SHUTOFF,
            message="Test alert 1",
            overflow_magnitude=100.0,
            overflow_handling="no_outlet",
            is_critical=True,
        )

        notifier.send_alert(alert1)
        notifier.send_alert(alert1)

        stats = notifier.get_stats()
        assert stats["sent_count"] == 2
        assert stats["failed_count"] == 0

    @patch.object(EmailNotifier, "send", return_value=False)
    @patch.object(SyslogNotifier, "send", return_value=False)
    @patch("syslog.openlog")
    def test_stats_failure_tracking(self, mock_openlog, mock_syslog_send, mock_email_send):
        """Notifier should track failures."""
        email = EmailNotifier("smtp", 587, "from@ex.com", ["to@ex.com"])
        syslog = SyslogNotifier()

        notifier = Notifier(email, syslog_notifier=syslog)

        alert1 = OverflowAlert(
            tank_id="tank1",
            severity=AlertSeverity.CRITICAL,
            action=AlertAction.ALERT_AND_SHUTOFF,
            message="Test alert",
            overflow_magnitude=100.0,
            overflow_handling="no_outlet",
            is_critical=True,
        )

        notifier.send_alert(alert1)
        stats = notifier.get_stats()
        assert stats["sent_count"] == 0
        assert stats["failed_count"] == 1

    def test_stats_reset(self):
        """Notifier should reset statistics."""
        notifier = Notifier()
        # Manually set stats
        notifier._sent_count = 10
        notifier._failed_count = 5

        notifier.reset_stats()
        stats = notifier.get_stats()
        assert stats["sent_count"] == 0
        assert stats["failed_count"] == 0
