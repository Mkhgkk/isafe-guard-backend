from flask import Blueprint
from flask import current_app as app
from main.auth import token_required
from main.system.models import System

system_blueprint = Blueprint("system", __name__)


@system_blueprint.route("", methods=["GET"])
def get():
    """Get system information
    ---
    tags:
      - System
    responses:
      200:
        description: System information retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                cpu_usage:
                  type: number
                  example: 45.2
                memory_usage:
                  type: number
                  example: 62.5
                disk_usage:
                  type: number
                  example: 75.0
    """
    return System().get()


@system_blueprint.route("/disk", methods=["GET"])
def get_disk():
    """Get disk usage information
    ---
    tags:
      - System
    responses:
      200:
        description: Disk usage information retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                total:
                  type: number
                used:
                  type: number
                free:
                  type: number
                percent:
                  type: number
    """
    return System().get_disk()


@system_blueprint.route("/retention", methods=["GET"])
def get_retention():
    """Get data retention settings
    ---
    tags:
      - System
    responses:
      200:
        description: Retention settings retrieved successfully
        schema:
          type: object
          properties:
            status:
              type: string
              example: success
            data:
              type: object
              properties:
                retention_days:
                  type: integer
                  example: 30
    """
    return System().get_retention()


@system_blueprint.route("/retention", methods=["POST"])
def update_retention():
    """Update data retention settings
    ---
    tags:
      - System
    parameters:
      - in: body
        name: retention
        description: Retention settings
        required: true
        schema:
          type: object
          required:
            - retention_days
          properties:
            retention_days:
              type: integer
              example: 30
    responses:
      200:
        description: Retention settings updated successfully
      400:
        description: Invalid input
    """
    return System().update_retention()


@system_blueprint.route("/watch_notif", methods=["POST"])
def update_watch_notif():
    """Update watch notification settings
    ---
    tags:
      - System
    parameters:
      - in: body
        name: watch_settings
        description: Watch notification settings
        required: true
        schema:
          type: object
          properties:
            enabled:
              type: boolean
              example: true
            url:
              type: string
              example: https://webhook.example.com
    responses:
      200:
        description: Watch notification settings updated successfully
      400:
        description: Invalid input
    """
    return System().update_watch_notif()


@system_blueprint.route("/email_notif", methods=["POST"])
def update_email_notif():
    """Update email notification settings
    ---
    tags:
      - System
    parameters:
      - in: body
        name: email_settings
        description: Email notification settings
        required: true
        schema:
          type: object
          properties:
            enabled:
              type: boolean
              example: true
            recipients:
              type: array
              items:
                type: string
              example: ["admin@example.com", "security@example.com"]
    responses:
      200:
        description: Email notification settings updated successfully
      400:
        description: Invalid input
    """
    return System().update_email_notif()


@system_blueprint.route("/email", methods=["GET"])
def send_test_email():
    """Send a test email
    ---
    tags:
      - System
    responses:
      200:
        description: Test email sent successfully
      500:
        description: Failed to send test email
    """
    return System().send_test_email()
