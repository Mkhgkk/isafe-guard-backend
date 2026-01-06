"""
Common Swagger schema components for stream routes
"""

# Common response schemas
STANDARD_SUCCESS_RESPONSE = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "example": "success"},
        "message": {"type": "string"}
    }
}

STANDARD_ERROR_RESPONSE = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "example": "error"},
        "message": {"type": "string"}
    }
}

# Stream field schemas (reusable components)
STREAM_BASE_FIELDS = {
    "_id": {"type": "string", "description": "MongoDB ObjectId"},
    "stream_id": {"type": "string", "description": "Unique stream identifier"},
    "rtsp_link": {"type": "string", "description": "RTSP URL for the camera stream"},
    "model_name": {
        "type": "string",
        "description": "AI model name used for detection",
        "enum": ["PPE", "PPEAerial", "Ladder", "Scaffolding", "MobileScaffolding",
                 "CuttingWelding", "Fire", "HeavyEquipment", "Proximity", "Approtium", "NexilisProximity"]
    },
    "location": {"type": "string", "description": "Physical location of the camera"},
    "description": {"type": "string", "description": "Camera description"},
    "is_active": {"type": "boolean", "description": "Whether the stream is currently running"},
}

STREAM_PTZ_FIELDS = {
    "ptz_autotrack": {"type": "boolean", "description": "Whether PTZ auto tracking is enabled"},
    "cam_ip": {"type": "string", "description": "Camera IP address (for PTZ control)"},
    "ptz_password": {"type": "string", "description": "PTZ control password"},
    "profile_name": {"type": "string", "description": "ONVIF profile name"},
    "ptz_port": {"type": "integer", "description": "PTZ control port"},
    "ptz_username": {"type": "string", "description": "PTZ control username"},
}

STREAM_PATROL_FIELDS = {
    "patrol_area": {
        "type": "object",
        "nullable": True,
        "description": "Grid patrol area configuration",
        "properties": {
            "xMin": {"type": "number"},
            "xMax": {"type": "number"},
            "yMin": {"type": "number"},
            "yMax": {"type": "number"},
            "zoom_level": {"type": "number"}
        }
    },
    "patrol_pattern": {
        "type": "object",
        "nullable": True,
        "description": "Custom patrol pattern with waypoints",
        "properties": {
            "coordinates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"}
                    }
                }
            }
        }
    },
    "patrol_home_position": {
        "type": "object",
        "nullable": True,
        "description": "Home position for patrol return",
        "properties": {
            "pan": {"type": "number"},
            "tilt": {"type": "number"},
            "zoom": {"type": "number"},
            "saved_at": {"type": "string", "format": "date-time"}
        }
    },
    "patrol_enabled": {"type": "boolean", "description": "Whether patrol is enabled"},
    "patrol_mode": {
        "type": "string",
        "enum": ["pattern", "grid", "off"],
        "description": "Current patrol mode"
    },
    "enable_focus_during_patrol": {"type": "boolean", "description": "Whether auto-focus is enabled during patrol"},
}

STREAM_HAZARD_FIELDS = {
    "safe_area": {
        "type": "object",
        "nullable": True,
        "description": "Hazard/safe area configuration for intrusion detection",
        "properties": {
            "coords": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}}
            },
            "static_mode": {"type": "boolean"},
            "reference_image": {"type": "string"},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"}
        }
    },
    "intrusion_detection": {"type": "boolean", "description": "Whether intrusion detection is enabled"},
}

STREAM_DERIVED_FIELDS = {
    "unresolved_events": {"type": "integer", "description": "Count of unresolved events for this stream (added by backend)"},
    "has_unresolved": {"type": "boolean", "description": "Whether stream has unresolved events (added by backend)"},
    "focus_enabled": {"type": "boolean", "description": "Whether focus is enabled (derived field)"},
    "is_hazard_area_configured": {"type": "boolean", "description": "Whether hazard area is configured (derived field)"},
    "has_ptz": {"type": "boolean", "description": "Whether stream has PTZ support (derived field)"},
    "is_grid_patrol_configured": {"type": "boolean", "description": "Whether grid patrol is configured (derived field)"},
    "is_pattern_patrol_configured": {"type": "boolean", "description": "Whether pattern patrol is configured (derived field)"},
}

STREAM_OTHER_FIELDS = {
    "saving_video": {"type": "boolean", "description": "Whether video recording is enabled"},
}

# Complete stream object schema
STREAM_FULL_SCHEMA = {
    "type": "object",
    "properties": {
        **STREAM_BASE_FIELDS,
        **STREAM_PTZ_FIELDS,
        **STREAM_PATROL_FIELDS,
        **STREAM_HAZARD_FIELDS,
        **STREAM_OTHER_FIELDS,
        **STREAM_DERIVED_FIELDS,
    }
}

# Stream list item schema (summary version)
STREAM_LIST_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        **STREAM_BASE_FIELDS,
        "ptz_autotrack": STREAM_PTZ_FIELDS["ptz_autotrack"],
        "unresolved_events": STREAM_DERIVED_FIELDS["unresolved_events"],
        "has_unresolved": STREAM_DERIVED_FIELDS["has_unresolved"],
        "has_ptz": STREAM_DERIVED_FIELDS["has_ptz"],
    }
}

# Common parameter schemas
STREAM_ID_PARAM = {
    "in": "body",
    "name": "body",
    "required": True,
    "schema": {
        "type": "object",
        "required": ["stream_id"],
        "properties": {
            "stream_id": {
                "type": "string",
                "example": "camera_001",
                "description": "ID of the stream"
            }
        }
    }
}

STREAM_ID_PATH_PARAM = {
    "in": "path",
    "name": "stream_id",
    "type": "string",
    "required": True,
    "description": "ID of the stream",
    "example": "camera_001"
}

STREAM_ID_QUERY_PARAM = {
    "in": "query",
    "name": "stream_id",
    "type": "string",
    "required": True,
    "description": "ID of the stream",
    "example": "camera_001"
}

# Common responses
RESPONSES_404_NOT_FOUND = {
    "404": {
        "description": "Stream not found",
        "schema": STANDARD_ERROR_RESPONSE
    }
}

RESPONSES_400_BAD_REQUEST = {
    "400": {
        "description": "Invalid input",
        "schema": STANDARD_ERROR_RESPONSE
    }
}

RESPONSES_STANDARD = {
    **RESPONSES_400_BAD_REQUEST,
    **RESPONSES_404_NOT_FOUND
}
