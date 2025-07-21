#!/usr/bin/env python
import os
import logging
from main import create_app
from startup.services import create_app_services
from utils.logging_config import setup_logging

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO")
enable_json_logging = os.getenv("JSON_LOGGING", "true").lower() == "true"
enable_file_logging = os.getenv("FILE_LOGGING", "true").lower() == "true"
enable_colored_logging = os.getenv("COLORED_LOGGING", "true").lower() == "true"
setup_logging(
    level=log_level, 
    enable_json=enable_json_logging, 
    enable_file_logging=enable_file_logging,
    enable_colors=enable_colored_logging
)

if __name__ == "__main__":
    app = create_app()
    create_app_services(app)
    
    # Configure Werkzeug logging to use our logging setup
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(getattr(logging, log_level.upper()))
    
    app.run(
        host=app.config["FLASK_DOMAIN"],
        port=app.config["FLASK_PORT"],
        debug=False,
        use_reloader=False,
        threaded=True,
    )