import pytest
from unittest.mock import Mock, call
from collector.calculator import TankReading
from collector.writer import WaterWriter


@pytest.fixture
def mock_writer(monkeypatch):
    """Create a WaterWriter with mocked InfluxDB client."""
    monkeypatch.setenv("INFLUXDB_URL", "http://localhost:8086")
    monkeypatch.setenv("INFLUXDB_TOKEN", "test_token")
    monkeypatch.setenv("INFLUXDB_ORG", "test_org")
    monkeypatch.setenv("INFLUXDB_BUCKET", "test_bucket")

    writer = WaterWriter()
    writer._write = Mock()
    return writer


@pytest.fixture
def sample_reading():
    """Create a sample tank reading."""
    return TankReading(
        tank_id="tank1",
        distance_raw_cm=50.0,
        level_cm=45.0,
        level_pct=50.0,
        volume_liters=2500.0,
        usable_depth_cm=180.0,
        capacity_liters=5000.0,
    )


class TestWaterWriter:
    """Tests for WaterWriter with overflow metadata support."""

    def test_write_reading_normal_no_overflow(self, mock_writer, sample_reading):
        """Normal reading without overflow should write basic data."""
        mock_writer.write_reading(sample_reading, source="mains")

        mock_writer._write.assert_called_once()
        points = mock_writer._write.call_args[0][0]
        assert len(points) == 1

        point = points[0]
        # Verify tags
        assert point._tags["tank_id"] == "tank1"
        assert point._tags["source"] == "mains"
        assert point._tags["overflow_detected"] == "false"

        # Verify fields
        assert point._fields["distance_raw_cm"] == 50.0
        assert point._fields["level_cm"] == 45.0
        assert point._fields["level_pct"] == 50.0
        assert point._fields["volume_liters"] == 2500.0
        # overflow_magnitude_liters should not be present
        assert "overflow_magnitude_liters" not in point._fields

    def test_write_reading_with_overflow(self, mock_writer, sample_reading):
        """Reading with overflow should include overflow metadata."""
        mock_writer.write_reading(
            sample_reading,
            source="mains",
            overflow_detected=True,
            overflow_magnitude=150.0,
            overflow_handling="no_outlet",
        )

        mock_writer._write.assert_called_once()
        points = mock_writer._write.call_args[0][0]
        point = points[0]

        # Verify overflow tags
        assert point._tags["overflow_detected"] == "true"
        assert point._tags["overflow_handling"] == "no_outlet"

        # Verify overflow_magnitude field
        assert point._fields["overflow_magnitude_liters"] == 150.0

    def test_write_reading_overflow_open_outlet(self, mock_writer, sample_reading):
        """Open outlet overflow should be tagged correctly."""
        mock_writer.write_reading(
            sample_reading,
            source="rain",
            overflow_detected=True,
            overflow_magnitude=500.5,
            overflow_handling="open_outlet",
        )

        mock_writer._write.assert_called_once()
        points = mock_writer._write.call_args[0][0]
        point = points[0]

        assert point._tags["overflow_detected"] == "true"
        assert point._tags["overflow_handling"] == "open_outlet"
        assert point._fields["overflow_magnitude_liters"] == 500.5

    def test_write_reading_overflow_without_magnitude(self, mock_writer, sample_reading):
        """Overflow detection without magnitude should still work."""
        mock_writer.write_reading(
            sample_reading,
            source="mains",
            overflow_detected=True,
            overflow_handling="no_outlet",
        )

        mock_writer._write.assert_called_once()
        points = mock_writer._write.call_args[0][0]
        point = points[0]

        assert point._tags["overflow_detected"] == "true"
        assert point._tags["overflow_handling"] == "no_outlet"
        # magnitude field should not be present if None
        assert "overflow_magnitude_liters" not in point._fields

    def test_write_reading_overflow_without_handling(self, mock_writer, sample_reading):
        """Overflow without handling specified should still be detected."""
        mock_writer.write_reading(
            sample_reading,
            source="mains",
            overflow_detected=True,
            overflow_magnitude=100.0,
        )

        mock_writer._write.assert_called_once()
        points = mock_writer._write.call_args[0][0]
        point = points[0]

        assert point._tags["overflow_detected"] == "true"
        assert point._fields["overflow_magnitude_liters"] == 100.0
        # overflow_handling tag should not be present if not provided
        assert "overflow_handling" not in point._tags

    def test_write_reading_backwards_compatible_no_overflow_params(
        self, mock_writer, sample_reading
    ):
        """Old calls without overflow params should still work."""
        mock_writer.write_reading(sample_reading, source="mains")

        mock_writer._write.assert_called_once()
        points = mock_writer._write.call_args[0][0]
        point = points[0]

        assert point._tags["overflow_detected"] == "false"
        # Verify basic fields still present
        assert point._fields["volume_liters"] == 2500.0

    def test_write_reading_default_source(self, mock_writer, sample_reading):
        """Reading without source should default to 'unknown'."""
        mock_writer.write_reading(sample_reading)

        mock_writer._write.assert_called_once()
        points = mock_writer._write.call_args[0][0]
        point = points[0]

        assert point._tags["source"] == "unknown"

    def test_write_reading_with_critical_flag(self, mock_writer, sample_reading):
        """Critical flag should be passed but not directly affect InfluxDB point."""
        mock_writer.write_reading(
            sample_reading,
            source="mains",
            overflow_detected=False,
            is_critical=True,
        )

        mock_writer._write.assert_called_once()
        points = mock_writer._write.call_args[0][0]
        point = points[0]

        # is_critical doesn't directly tag the point (it's for higher-level alerting logic)
        assert "is_critical" not in point._tags
        assert "is_critical" not in point._fields

    def test_write_reading_overflow_magnitude_rounding(self, mock_writer, sample_reading):
        """Overflow magnitude should be rounded to 1 decimal place."""
        mock_writer.write_reading(
            sample_reading,
            source="mains",
            overflow_detected=True,
            overflow_magnitude=123.456789,
            overflow_handling="no_outlet",
        )

        mock_writer._write.assert_called_once()
        points = mock_writer._write.call_args[0][0]
        point = points[0]

        assert point._fields["overflow_magnitude_liters"] == 123.5

    def test_write_reading_zero_overflow_magnitude(self, mock_writer, sample_reading):
        """Zero overflow magnitude should be handled correctly."""
        mock_writer.write_reading(
            sample_reading,
            source="mains",
            overflow_detected=True,
            overflow_magnitude=0.0,
            overflow_handling="no_outlet",
        )

        mock_writer._write.assert_called_once()
        points = mock_writer._write.call_args[0][0]
        point = points[0]

        assert point._fields["overflow_magnitude_liters"] == 0.0
