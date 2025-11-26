from flask import Blueprint
from main.models.models import ModelsConfig

models_blueprint = Blueprint("models", __name__)


@models_blueprint.route("/available", methods=["GET"])
def get_available_models():
    """
    Get list of available (enabled) models for the current deployment.
    Models are determined by the MODELS_TO_LOAD environment variable.
    Returns: {"models": [{"value": "PPE", "label": "PPE"}, ...]}
    """
    return ModelsConfig().get_available_models()


@models_blueprint.route("/all", methods=["GET"])
def get_all_models():
    """
    Get all models with their enabled status based on MODELS_TO_LOAD env var.
    Returns: {"models": [{"value": "PPE", "label": "PPE", "enabled": true}, ...]}
    """
    return ModelsConfig().get_all_models()
