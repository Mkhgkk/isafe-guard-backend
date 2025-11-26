import os
from main import tools

# All available models in the system
ALL_MODELS = [
    {"value": "PPE", "label": "PPE"},
    {"value": "PPEAerial", "label": "PPEAerial"},
    {"value": "Scaffolding", "label": "Scaffolding"},
    {"value": "Ladder", "label": "Ladder"},
    {"value": "MobileScaffolding", "label": "Mobile Scaffolding"},
    {"value": "CuttingWelding", "label": "Cutting Welding"},
    {"value": "Fire", "label": "Fire"},
    {"value": "HeavyEquipment", "label": "Hamyang"},
    {"value": "Proximity", "label": "Proximity"},
    {"value": "Approtium", "label": "Intrusion"},
    {"value": "NexilisProximity", "label": "Nexilis Proximity"},
]


class ModelsConfig:
    """
    Manages the configuration of available models for the system.
    Models are configured via the MODELS_TO_LOAD environment variable.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ModelsConfig, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "initialized"):
            self.initialized = True

    def _get_enabled_models_from_env(self):
        """
        Get list of enabled model values from MODELS_TO_LOAD environment variable.
        Format: "PPE,Scaffolding,Fire" or empty for all models.
        """
        models_to_load = os.getenv("MODELS_TO_LOAD", "").strip()

        if not models_to_load:
            # If not set, return all models
            return [model["value"] for model in ALL_MODELS]

        # Split and clean up the model names
        enabled_models = []
        _ = [m.strip() for m in models_to_load.split(",") if m.strip()]
        for model_value in _:
            if model_value.startswith("hamyang"):
                enabled_models.append("HeavyEquipment")
        return list(set(enabled_models))

    def get_available_models(self):
        """
        Get list of available models based on MODELS_TO_LOAD environment variable.
        Returns only enabled models.
        """
        try:
            enabled_model_values = self._get_enabled_models_from_env()

            # Filter ALL_MODELS to only include enabled ones
            available_models = [
                {"value": model["value"], "label": model["label"]}
                for model in ALL_MODELS
                if model["value"] in enabled_model_values
            ]

            return tools.JsonResp({"models": available_models}, 200)
        except Exception as e:
            print(f"Error getting available models: {e}")
            return tools.JsonResp({"error": str(e)}, 500)

    def get_all_models(self):
        """
        Get all models with their enabled status based on MODELS_TO_LOAD env var.
        Used for admin/configuration purposes.
        """
        try:
            enabled_model_values = self._get_enabled_models_from_env()

            # Add enabled flag to all models
            all_models_with_status = [
                {
                    "value": model["value"],
                    "label": model["label"],
                    "enabled": model["value"] in enabled_model_values,
                }
                for model in ALL_MODELS
            ]

            return tools.JsonResp({"models": all_models_with_status}, 200)
        except Exception as e:
            print(f"Error getting all models: {e}")
            return tools.JsonResp({"error": str(e)}, 500)
