"""
Stream routes initialization
Registers all stream-related sub-blueprints into a single stream_blueprint
"""
from flask import Blueprint
from .crud import crud_blueprint
from .control import control_blueprint
from .ptz import ptz_blueprint
from .patrol import patrol_blueprint
from .config import config_blueprint

# Create the main stream blueprint
stream_blueprint = Blueprint('stream', __name__)

# Register all sub-blueprints
# Note: We register them without url_prefix since they're all under /stream already
stream_blueprint.register_blueprint(crud_blueprint)
stream_blueprint.register_blueprint(control_blueprint)
stream_blueprint.register_blueprint(ptz_blueprint)
stream_blueprint.register_blueprint(patrol_blueprint)
stream_blueprint.register_blueprint(config_blueprint)

# Export the main blueprint
__all__ = ['stream_blueprint']
