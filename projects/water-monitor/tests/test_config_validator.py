import pytest
from collector.config_validator import ConfigValidator, ConfigValidationError


class TestConfigValidator:
    """Tests for tank configuration validation."""

    def test_validate_valid_tank_config(self):
        """Valid tank configuration should pass validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
            "inlet_shutoff": "float_valve",
            "num_sources": "single",
            "is_critical": True,
            "alerting_enabled": True,
        }
        ConfigValidator.validate_tank(tank_cfg)  # Should not raise

    def test_missing_required_field_id(self):
        """Tank without id should fail validation."""
        tank_cfg = {
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
        }
        with pytest.raises(ConfigValidationError, match="missing required field 'id'"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_missing_required_field_depth_cm(self):
        """Tank without depth_cm should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
        }
        with pytest.raises(ConfigValidationError, match="missing required field 'depth_cm'"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_missing_required_field_capacity_liters(self):
        """Tank without capacity_liters should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "overflow_handling": "no_outlet",
        }
        with pytest.raises(ConfigValidationError, match="missing required field 'capacity_liters'"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_missing_required_field_overflow_handling(self):
        """Tank without overflow_handling should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
        }
        with pytest.raises(ConfigValidationError, match="missing required field 'overflow_handling'"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_invalid_overflow_handling_value(self):
        """Invalid overflow_handling value should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "invalid_value",
        }
        with pytest.raises(ConfigValidationError, match="invalid value 'invalid_value'"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_invalid_inlet_shutoff_value(self):
        """Invalid inlet_shutoff value should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
            "inlet_shutoff": "automatic",
        }
        with pytest.raises(ConfigValidationError, match="invalid value 'automatic'"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_invalid_num_sources_value(self):
        """Invalid num_sources value should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
            "num_sources": "dual",
        }
        with pytest.raises(ConfigValidationError, match="invalid value 'dual'"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_negative_depth_cm(self):
        """Negative depth_cm should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": -100,
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
        }
        with pytest.raises(ConfigValidationError, match="positive numbers"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_zero_capacity_liters(self):
        """Zero capacity_liters should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 0,
            "overflow_handling": "no_outlet",
        }
        with pytest.raises(ConfigValidationError, match="positive numbers"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_invalid_sensor_offset_negative(self):
        """Negative sensor_offset_cm should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
            "sensor_offset_cm": -5,
        }
        with pytest.raises(ConfigValidationError, match="sensor_offset_cm must be non-negative"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_invalid_sensor_offset_exceeds_depth(self):
        """sensor_offset_cm >= depth_cm should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
            "sensor_offset_cm": 180,
        }
        with pytest.raises(ConfigValidationError, match="less than depth_cm"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_invalid_low_threshold_pct_negative(self):
        """Negative low_threshold_pct should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
            "low_threshold_pct": -10,
        }
        with pytest.raises(ConfigValidationError, match="low_threshold_pct must be 0-100"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_invalid_low_threshold_pct_exceeds_100(self):
        """low_threshold_pct > 100 should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
            "low_threshold_pct": 150,
        }
        with pytest.raises(ConfigValidationError, match="low_threshold_pct must be 0-100"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_invalid_full_threshold_pct_exceeds_100(self):
        """full_threshold_pct > 100 should fail validation."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
            "full_threshold_pct": 105,
        }
        with pytest.raises(ConfigValidationError, match="full_threshold_pct must be 0-100"):
            ConfigValidator.validate_tank(tank_cfg)

    def test_validate_full_config_single_tank(self):
        """Valid complete configuration with single tank should pass."""
        config = {
            "tanks": [
                {
                    "id": "tank1",
                    "name": "Test Tank",
                    "depth_cm": 180,
                    "capacity_liters": 5000,
                    "overflow_handling": "no_outlet",
                }
            ]
        }
        ConfigValidator.validate_config(config)  # Should not raise

    def test_validate_full_config_multiple_tanks(self):
        """Valid configuration with multiple tanks should pass."""
        config = {
            "tanks": [
                {
                    "id": "tank1",
                    "depth_cm": 180,
                    "capacity_liters": 5000,
                    "overflow_handling": "no_outlet",
                },
                {
                    "id": "tank2",
                    "depth_cm": 350,
                    "capacity_liters": 14700,
                    "overflow_handling": "open_outlet",
                },
            ]
        }
        ConfigValidator.validate_config(config)  # Should not raise

    def test_missing_tanks_key(self):
        """Configuration without 'tanks' key should fail."""
        config = {}
        with pytest.raises(ConfigValidationError, match="missing 'tanks' key"):
            ConfigValidator.validate_config(config)

    def test_empty_tanks_list(self):
        """Configuration with empty tanks list should fail."""
        config = {"tanks": []}
        with pytest.raises(ConfigValidationError, match="at least one tank"):
            ConfigValidator.validate_config(config)

    def test_duplicate_tank_ids(self):
        """Configuration with duplicate tank IDs should fail."""
        config = {
            "tanks": [
                {
                    "id": "tank1",
                    "depth_cm": 180,
                    "capacity_liters": 5000,
                    "overflow_handling": "no_outlet",
                },
                {
                    "id": "tank1",
                    "depth_cm": 350,
                    "capacity_liters": 14700,
                    "overflow_handling": "open_outlet",
                },
            ]
        }
        with pytest.raises(ConfigValidationError, match="Duplicate tank ID: tank1"):
            ConfigValidator.validate_config(config)

    def test_tank_missing_id_in_list(self):
        """Tank in list without id should fail."""
        config = {
            "tanks": [
                {
                    "depth_cm": 180,
                    "capacity_liters": 5000,
                    "overflow_handling": "no_outlet",
                }
            ]
        }
        with pytest.raises(ConfigValidationError, match="missing 'id' field"):
            ConfigValidator.validate_config(config)

    def test_valid_overflow_handling_open_outlet(self):
        """open_outlet should be valid."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "open_outlet",
        }
        ConfigValidator.validate_tank(tank_cfg)  # Should not raise

    def test_valid_inlet_shutoff_manual_valve(self):
        """manual_valve should be valid."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "no_outlet",
            "inlet_shutoff": "manual_valve",
        }
        ConfigValidator.validate_tank(tank_cfg)  # Should not raise

    def test_valid_num_sources_multiple(self):
        """multiple should be valid."""
        tank_cfg = {
            "id": "tank1",
            "depth_cm": 180,
            "capacity_liters": 5000,
            "overflow_handling": "open_outlet",
            "num_sources": "multiple",
        }
        ConfigValidator.validate_tank(tank_cfg)  # Should not raise
