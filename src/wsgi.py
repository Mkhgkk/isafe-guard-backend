#!/usr/bin/env python
"""
Production WSGI entry point optimized for ML models.
Uses single process with threading to avoid model duplication.
"""
import os
import logging
from main import create_app
from startup.services import create_app_services
from utils.logging_config import setup_logging, get_logger, log_event

# Configure logging for production
log_level = os.getenv("LOG_LEVEL", "INFO")
enable_json_logging = os.getenv("JSON_LOGGING", "true").lower() == "true"
enable_file_logging = os.getenv("FILE_LOGGING", "true").lower() == "true"
enable_colored_logging = os.getenv("COLORED_LOGGING", "false").lower() == "true"  # Disable colors in production

setup_logging(
    level=log_level, 
    enable_json=enable_json_logging, 
    enable_file_logging=enable_file_logging,
    enable_colors=enable_colored_logging
)

logger = get_logger(__name__)

# Create Flask application
app = create_app()
create_app_services(app)

# Configure application for production
app.config.update(
    DEBUG=False,
    TESTING=False,
)

if __name__ == "__main__":
    # Production mode - single process with threading for ML models
    log_event(logger, "info", "🚀 Starting production server (single process, threaded)", event_type="server_start")
    log_event(logger, "info", "Thread-based model loading will prevent duplication", event_type="server_config")
    
    app.run(
        host=app.config["FLASK_DOMAIN"],
        port=app.config["FLASK_PORT"],
        debug=False,
        use_reloader=False,
        threaded=True,  # Enable threading for concurrent requests
        processes=1,     # Single process to avoid model duplication
    )