#!/usr/bin/env python
import logging
from main import create_app
from startup.services import create_app_services

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

if __name__ == "__main__":
    app = create_app()
    create_app_services(app)
    app.run(
        host=app.config["FLASK_DOMAIN"],
        port=app.config["FLASK_PORT"],
        debug=False,
        use_reloader=False,
        threaded=True,
    )