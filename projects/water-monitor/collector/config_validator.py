import logging
from typing import Any

log = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when tank configuration is invalid."""
    pass


class ConfigValidator:
    """Validates tank configuration for Phase 2+ requirements."""

    # Required for all tanks
    REQUIRED_FIELDS = ["id", "depth_cm", "capacity_liters", "overflow_handling"]

    # Fields with specific enum values
    ENUM_FIELDS = {
        "overflow_handling": ["open_outlet", "no_outlet"],
        "inlet_shutoff": ["float_valve", "manual_valve"],
        "num_sources": ["single", "multiple"],
    }

    @staticmethod
    def validate_tank(tank_cfg: dict) -> None:
        """
        Validate a single tank configuration.

        Args:
            tank_cfg: Tank configuration dictionary

        Raises:
            ConfigValidationError: If validation fails
        """
        # Check required fields
        for field in ConfigValidator.REQUIRED_FIELDS:
            if field not in tank_cfg:
                raise ConfigValidationError(
                    f"Tank {tank_cfg.get('id', 'UNKNOWN')}: missing required field '{field}'"
                )

        # Validate enum fields
        for field, valid_values in ConfigValidator.ENUM_FIELDS.items():
            if field in tank_cfg:
                value = tank_cfg[field]
                if value not in valid_values:
                    raise ConfigValidationError(
                        f"Tank {tank_cfg['id']}: field '{field}' has invalid value '{value}'. "
                        f"Must be one of: {valid_values}"
                    )

        # Check that numeric fields are valid
        try:
            depth = float(tank_cfg["depth_cm"])
            capacity = float(tank_cfg["capacity_liters"])
            if depth <= 0 or capacity <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ConfigValidationError(
                f"Tank {tank_cfg['id']}: depth_cm and capacity_liters must be positive numbers"
            )

        # Validate numeric fields if present
        if "sensor_offset_cm" in tank_cfg:
            try:
                offset = float(tank_cfg["sensor_offset_cm"])
                if offset < 0 or offset >= depth:
                    raise ValueError
            except (ValueError, TypeError):
                raise ConfigValidationError(
                    f"Tank {tank_cfg['id']}: sensor_offset_cm must be non-negative "
                    f"and less than depth_cm"
                )

        # Validate threshold percentages if present
        if "low_threshold_pct" in tank_cfg:
            try:
                low = float(tank_cfg["low_threshold_pct"])
                if low < 0 or low > 100:
                    raise ValueError
            except (ValueError, TypeError):
                raise ConfigValidationError(
                    f"Tank {tank_cfg['id']}: low_threshold_pct must be 0-100"
                )

        if "full_threshold_pct" in tank_cfg:
            try:
                full = float(tank_cfg["full_threshold_pct"])
                if full < 0 or full > 100:
                    raise ValueError
            except (ValueError, TypeError):
                raise ConfigValidationError(
                    f"Tank {tank_cfg['id']}: full_threshold_pct must be 0-100"
                )

        # Validate threshold relationship (low < full)
        if "low_threshold_pct" in tank_cfg and "full_threshold_pct" in tank_cfg:
            low = float(tank_cfg["low_threshold_pct"])
            full = float(tank_cfg["full_threshold_pct"])
            if low >= full:
                raise ConfigValidationError(
                    f"Tank {tank_cfg['id']}: low_threshold_pct ({low}%) must be < "
                    f"full_threshold_pct ({full}%)"
                )

    @staticmethod
    def validate_config(config: dict) -> None:
        """
        Validate entire configuration.

        Args:
            config: Complete configuration dictionary from tanks.yaml

        Raises:
            ConfigValidationError: If any tank configuration is invalid
        """
        if "tanks" not in config:
            raise ConfigValidationError("Configuration missing 'tanks' key")

        tanks = config["tanks"]
        if not isinstance(tanks, list) or len(tanks) == 0:
            raise ConfigValidationError("Configuration must have at least one tank")

        tank_ids = set()
        for tank_cfg in tanks:
            # Check for duplicate IDs
            tank_id = tank_cfg.get("id")
            if not tank_id:
                raise ConfigValidationError("Tank configuration missing 'id' field")
            if tank_id in tank_ids:
                raise ConfigValidationError(f"Duplicate tank ID: {tank_id}")
            tank_ids.add(tank_id)

            # Validate this tank
            ConfigValidator.validate_tank(tank_cfg)

        log.info("Configuration validation passed: %d tanks", len(tanks))

    @staticmethod
    def log_summary(config: dict) -> None:
        """Log a summary of tank configuration."""
        tanks = config.get("tanks", [])
        for tank in tanks:
            log.info(
                "Tank: id=%s, capacity=%sL, overflow_handling=%s, is_critical=%s, alerting=%s",
                tank.get("id"),
                tank.get("capacity_liters"),
                tank.get("overflow_handling"),
                tank.get("is_critical", False),
                tank.get("alerting_enabled", True),
            )
