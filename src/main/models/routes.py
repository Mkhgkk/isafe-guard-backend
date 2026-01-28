from flask import Blueprint
from main.models.models import ModelsConfig

models_blueprint = Blueprint("models", __name__)


@models_blueprint.route("/available", methods=["GET"])
def get_available_models():
    """Get list of available (enabled) AI models
    ---
    tags:
      - Models
    responses:
      200:
        description: Available models retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                models:
                  type: array
                  items:
                    type: object
                    properties:
                      value:
                        type: string
                        example: PPE
                      label:
                        type: string
                        example: PPE Detection
    """
    return ModelsConfig().get_available_models()


@models_blueprint.route("/all", methods=["GET"])
def get_all_models():
    """Get all AI models with their enabled status
    ---
    tags:
      - Models
    responses:
      200:
        description: All models retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                models:
                  type: array
                  items:
                    type: object
                    properties:
                      value:
                        type: string
                        example: PPE
                      label:
                        type: string
                        example: PPE Detection
                      enabled:
                        type: boolean
                        example: true
    """
    return ModelsConfig().get_all_models()
