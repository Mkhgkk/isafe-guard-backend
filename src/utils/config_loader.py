"""
Centralized configuration loader for iSafe Guard Backend.

This module loads configuration from:
1. Default YAML config file (config.yaml)
2. Local override file (config.local.yaml) - optional, for local development
3. Environment variables (highest priority)

Configuration Priority (highest to lowest):
1. Environment variables
2. config.local.yaml
3. config.yaml

Usage:
    from utils.config_loader import config

    # Access configuration
    db_host = config.get('database.host')
    frame_width = config.get('processing.frame_width')

    # Access with default value
    debug = config.get('app.debug', default=False)

    # Access nested dict
    email_config = config.get('notifications.email')
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Add src to path if not already there
current_file = Path(__file__).resolve()
src_dir = current_file.parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# Lazy import yaml to avoid issues
try:
    import yaml
except ImportError:
    # Provide helpful error message
    raise ImportError(
        "PyYAML is required for configuration. Install it with: poetry add pyyaml"
    )


class ConfigLoader:
    """Centralized configuration management with YAML + environment variable support."""

    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize configuration loader.

        Args:
            config_dir: Directory containing config.yaml. If None, uses src/ directory.
        """
        if config_dir is None:
            # Auto-detect src directory
            current_file = Path(__file__).resolve()
            config_dir = current_file.parent.parent  # Go up to src/

        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "config.yaml"
        self.local_config_file = self.config_dir / "config.local.yaml"

        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_yaml_file(self, file_path: Path) -> Dict[str, Any]:
        """Load YAML configuration file."""
        try:
            if file_path.exists():
                with open(file_path, 'r') as f:
                    return yaml.safe_load(f) or {}
            return {}
        except Exception as e:
            # Use print instead of logger to avoid circular imports
            print(f"Warning: Failed to load config file {file_path}: {e}", file=sys.stderr)
            return {}

    def _merge_dicts(self, base: Dict, override: Dict) -> Dict:
        """Recursively merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_dicts(result[key], value)
            else:
                result[key] = value
        return result

    def _apply_env_overrides(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply environment variable overrides to configuration.

        Environment variable naming convention:
        - Nested keys separated by double underscore: SECTION__KEY
        - Example: DATABASE__HOST -> database.host
        - Example: DETECTION__NPU__ENABLED -> detection.npu.enabled
        """
        env_mappings = {
            # App settings
            'SECRET_KEY': 'app.secret_key',
            'DEBUG': 'app.debug',
            'ENVIRONMENT': 'app.environment',
            'TIMEZONE': 'app.timezone',

            # Server settings
            'FLASK_DOMAIN': 'server.host',
            'FLASK_PORT': 'server.port',
            'PROTOCOL': 'server.protocol',
            'DOMAIN': 'server.domain',
            'FRONTEND_DOMAIN': 'server.frontend_domain',

            # Database settings
            'DB_HOST': 'database.uri',
            'MONGO_URI': 'database.uri',
            'MONGO_HOSTNAME': 'database.host',
            'MONGO_PORT': 'database.port',
            'MONGO_APP_DATABASE': 'database.name',
            'MONGO_AUTH_DATABASE': 'database.auth_database',
            'MONGO_AUTH_USERNAME': 'database.username',
            'MONGO_AUTH_PASSWORD': 'database.password',

            # Logging settings
            'LOG_LEVEL': 'logging.level',
            'JSON_LOGGING': 'logging.json_format',
            'FILE_LOGGING': 'logging.file_logging',
            'COLORED_LOGGING': 'logging.colored_logging',

            # Processing settings
            'FRAME_WIDTH': 'processing.frame_width',
            'FRAME_HEIGHT': 'processing.frame_height',
            'INFERENCE_INTERVAL': 'processing.inference_interval',

            # GStreamer settings
            'GST_DEBUG': 'gstreamer.debug_level',

            # Streaming settings
            'RTMP_MEDIA_SERVER': 'streaming.rtmp_server',
            'RTMP_BITRATE': 'streaming.bitrate',

            # Detection settings
            'USE_NPU': 'detection.npu.enabled',
            'NPU_MODEL_PATH': 'detection.npu.model_path',
            'CONF_THRESHOLD': 'detection.npu.conf_threshold',
            'IOU_THRESHOLD': 'detection.npu.iou_threshold',
            'TRITON_SERVER_URL': 'detection.triton.server_url',
            'MODELS_TO_LOAD': 'detection.models_to_load',
            'DEFAULT_PRECISION': 'detection.default_precision',

            # Event processing
            'UNSAFE_RATIO_THRESHOLD': 'events.unsafe_ratio_threshold',
            'EVENT_COOLDOWN': 'events.event_cooldown',

            # Notifications
            'SENDER_EMAIL': 'notifications.email.sender',
            'EMAIL_PASSWORD': 'notifications.email.password',
            'RECEIVER_EMAILS': 'notifications.email.receivers',
            'WATCH_NOTIFICATION_URL': 'notifications.watch.url',
            'PHONE_ID': 'notifications.watch.phone_id',

            # Gunicorn settings
            'GUNICORN_WORKER_CONNECTIONS': 'gunicorn.worker_connections',
            'GUNICORN_TIMEOUT': 'gunicorn.timeout',
            'GUNICORN_KEEPALIVE': 'gunicorn.keepalive',
            'GUNICORN_GRACEFUL_TIMEOUT': 'gunicorn.graceful_timeout',
            'GUNICORN_LOG_LEVEL': 'gunicorn.log_level',
            'GUNICORN_MAX_REQUESTS': 'gunicorn.max_requests',
            'GUNICORN_MAX_REQUESTS_JITTER': 'gunicorn.max_requests_jitter',
        }

        result = config.copy()

        # Apply explicit mappings
        for env_var, config_path in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                self._set_nested_value(result, config_path, self._parse_env_value(value))

        # Apply generic double-underscore mappings (e.g., DATABASE__HOST)
        for env_var, value in os.environ.items():
            if '__' in env_var:
                # Convert SECTION__KEY to section.key
                config_path = env_var.lower().replace('__', '.')
                self._set_nested_value(result, config_path, self._parse_env_value(value))

        return result

    def _parse_env_value(self, value: str) -> Any:
        """
        Parse environment variable value to appropriate type.

        Handles:
        - Boolean: "true", "false", "yes", "no", "1", "0"
        - Integer: "123"
        - Float: "1.5"
        - List: "item1,item2,item3"
        - String: everything else
        """
        # Boolean conversion
        if value.lower() in ('true', 'yes', '1'):
            return True
        if value.lower() in ('false', 'no', '0'):
            return False

        # Try integer
        try:
            if '.' not in value:
                return int(value)
        except ValueError:
            pass

        # Try float
        try:
            return float(value)
        except ValueError:
            pass

        # Check for comma-separated list
        if ',' in value:
            return [item.strip() for item in value.split(',') if item.strip()]

        # Return as string
        return value

    def _set_nested_value(self, config: Dict, path: str, value: Any) -> None:
        """Set a nested dictionary value using dot notation path."""
        keys = path.split('.')
        current = config

        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        current[keys[-1]] = value

    def _get_nested_value(self, config: Dict, path: str, default: Any = None) -> Any:
        """Get a nested dictionary value using dot notation path."""
        keys = path.split('.')
        current = config

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default

        return current

    def _load_config(self) -> None:
        """Load configuration from YAML files and environment variables."""
        # Load base config
        base_config = self._load_yaml_file(self.config_file)

        # Load local overrides (optional)
        local_config = self._load_yaml_file(self.local_config_file)

        # Merge configurations (local overrides base)
        merged_config = self._merge_dicts(base_config, local_config)

        # Apply environment variable overrides (highest priority)
        self._config = self._apply_env_overrides(merged_config)

        # Use print instead of logger to avoid circular imports during initialization
        # Actual logging will be set up after config is loaded
        if os.getenv('DEBUG') or os.getenv('LOG_LEVEL') == 'DEBUG':
            print(f"Configuration loaded from {self.config_file}")
            if self.local_config_file.exists():
                print(f"Local overrides applied from {self.local_config_file}")

    def get(self, path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation path.

        Args:
            path: Dot-separated path to config value (e.g., 'database.host')
            default: Default value if path not found

        Returns:
            Configuration value or default

        Examples:
            >>> config.get('database.host')
            'localhost'
            >>> config.get('app.debug', default=False)
            False
            >>> config.get('notifications.email')
            {'sender': '...', 'password': '...'}
        """
        return self._get_nested_value(self._config, path, default)

    def get_all(self) -> Dict[str, Any]:
        """Get entire configuration dictionary."""
        return self._config.copy()

    def reload(self) -> None:
        """Reload configuration from files and environment."""
        self._load_config()


# Global configuration instance
config = ConfigLoader()


# Convenience functions for common configuration access
def get_database_config() -> Dict[str, Any]:
    """Get database configuration."""
    return config.get('database', {})


def get_logging_config() -> Dict[str, Any]:
    """Get logging configuration."""
    return config.get('logging', {})


def get_detection_config() -> Dict[str, Any]:
    """Get detection configuration."""
    return config.get('detection', {})


def get_streaming_config() -> Dict[str, Any]:
    """Get streaming configuration."""
    return config.get('streaming', {})


def get_notification_config() -> Dict[str, Any]:
    """Get notification configuration."""
    return config.get('notifications', {})


def is_debug_mode() -> bool:
    """Check if debug mode is enabled."""
    return config.get('app.debug', False)


def is_npu_enabled() -> bool:
    """Check if NPU inference is enabled."""
    return config.get('detection.npu.enabled', False)
