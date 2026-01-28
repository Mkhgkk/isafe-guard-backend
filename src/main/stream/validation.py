"""Marshmallow schemas for stream data validation."""

from marshmallow import (
    Schema,
    fields,
    validate,
)


class PatrolAreaSchema(Schema):
    """Schema for patrol area coordinates."""

    xMin = fields.Float(required=True)
    xMax = fields.Float(required=True)
    yMin = fields.Float(required=True)
    yMax = fields.Float(required=True)
    zoom_level = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))


class PatrolCoordinateSchema(Schema):
    """Schema for a single patrol coordinate."""

    x = fields.Float(required=True)
    y = fields.Float(required=True)
    z = fields.Float(required=True, validate=validate.Range(min=0.0, max=1.0))


class PatrolPatternSchema(Schema):
    """Schema for patrol pattern with multiple coordinates."""

    coordinates = fields.List(
        fields.Nested(PatrolCoordinateSchema),
        required=True,
        validate=validate.Length(min=2),  # At least 2 points for a pattern
    )


class SafeAreaSchema(Schema):
    """Schema for safe/hazard area configuration."""

    coords = fields.List(
        fields.List(fields.Float(), validate=validate.Length(equal=2)),
        required=True,
        validate=validate.Length(min=3),  # At least 3 points for a polygon
    )
    static_mode = fields.Boolean(load_default=True)
    reference_image = fields.String()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()


class StreamSchema(Schema):
    stream_id = fields.String(required=True)
    rtsp_link = fields.String(required=True)
    model_name = fields.String(
        required=True,
        validate=validate.OneOf(
            [
                "PPE",
                "PPEAerial",
                "Ladder",
                "Scaffolding",
                "MobileScaffolding",
                "CuttingWelding",
                "Fire",
                "HeavyEquipment",
                "Proximity",
                "Approtium",
                "NexilisProximity",
            ]
        ),
    )
    location = fields.String(required=True)
    description = fields.String(required=True)
    is_active = fields.Boolean(load_default=False)
    ptz_autotrack = fields.Boolean(load_default=False)
    supports_ptz = fields.Boolean()
    cam_ip = fields.String()
    ptz_password = fields.String()
    profile_name = fields.String()
    ptz_port = fields.Integer()
    ptz_username = fields.String()
    patrol_area = fields.Nested(PatrolAreaSchema, missing=None, allow_none=True)
    safe_area = fields.Nested(SafeAreaSchema, missing=None, allow_none=True)
    intrusion_detection = fields.Boolean(load_default=False)
    saving_video = fields.Boolean(load_default=True)

    # class Meta:
    #     unknown = INCLUDE


stream_schema = StreamSchema()
