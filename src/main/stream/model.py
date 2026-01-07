
import json
import time
import os
import cv2
import traceback
from datetime import datetime, timezone
from flask import request, current_app as app

from main import tools
from main.stream.validation import StreamSchema, stream_schema
from main.stream.services import HazardService, PatrolService, StreamService, PTZService
from utils.logging_config import get_logger, log_event
from events import emit_event, EventType
from main.shared import streams 

logger = get_logger(__name__)

class Stream:

    # Helper Methods
    def _parse_request_data(self):
        """Parse and return JSON data from request."""
        try:
            return json.loads(request.data)
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON data format.")

    def _validate_stream_id_only(self, data):
        """Validate data containing only stream_id field."""
        stream_id_only = StreamSchema(only=("stream_id",))
        validation_errors = stream_id_only.validate(data)
        if validation_errors:
            raise ValueError(f"Validation failed: {validation_errors}")
        return data["stream_id"]

    def _create_error_response(self, message, error_code=None, status_code=400):
        """Create standardized error response."""
        response_data = {"message": message}
        if error_code:
            response_data["error"] = error_code
        log_event(logger, "error", message, event_type="error")
        return tools.JsonResp(response_data, status_code)

    def _create_success_response(self, message, data=None, status_code=200):
        """Create standardized success response."""
        response_data = {"message": message}
        if data:
            response_data["data"] = data
        return tools.JsonResp(response_data, status_code)

    def create_stream(self):
        try:
            payload = self._parse_request_data()
            data = payload.get("stream")
            start_stream = payload.get("start_stream", False)

            validation_errors = stream_schema.validate(data)
            if validation_errors:
                return self._create_error_response("Validation failed!", validation_errors)

            data = stream_schema.load(data)
            
            result = StreamService.create_stream(data, start_stream)
            
            if result["status"] == "error":
                return self._create_error_response(result["message"], result.get("error_code"))
            
            return self._create_success_response(result["message"], result["data"])

        except ValueError as e:
            return self._create_error_response(str(e))
        except Exception as e:
            log_event(logger, "error", f"Error creating stream: {e}", event_type="error")
            return self._create_error_response("Stream could not be created", "creating_stream_failed")

    def delete_stream(self):
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")

            if not stream_id:
                return self._create_error_response("Missing stream_id in request data")

            result = StreamService.delete_stream(stream_id)
            
            if result["status"] == "error":
                return self._create_error_response(result["message"]) 
                
            return self._create_success_response(result["message"], "ok")

        except ValueError as e:
            return self._create_error_response(str(e))
        except Exception as e:
            log_event(logger, "error", f"Error deleting stream: {e}", event_type="error")
            return self._create_error_response("Deletion failed!", "stream_deletion_failed")

    def stop(self):
        try:
            data = self._parse_request_data()
            stream_id = self._validate_stream_id_only(data)
            
            StreamService.stop_stream(stream_id)
            
            return self._create_success_response("Stream stopped successfully.", "ok")

        except ValueError as e:
            return self._create_error_response(str(e))
        except Exception as e:
            log_event(logger, "error", f"Unexpected error in stop: {e}", event_type="error")
            return self._create_error_response("Something went wrong", "internal_error", 500)

    def restart(self):
        try:
            data = self._parse_request_data()
            stream_id = self._validate_stream_id_only(data)

            result = StreamService.restart_stream(stream_id)
            
            if result["status"] == "error":
                return self._create_error_response(result["message"], result.get("error_code"), 500)

            return self._create_success_response(result["message"], result["data"])

        except ValueError as e:
            return self._create_error_response(str(e))
        except Exception as e:
            log_event(logger, "error", f"Unexpected error in restart: {e}", event_type="error")
            return self._create_error_response(f"An unexpected error occurred: {str(e)}", "internal_error", 500)

    def start(self):
        try:
            data = self._parse_request_data()
            stream_id = self._validate_stream_id_only(data)
            
            result = StreamService.get_stream(stream_id)
            if result["status"] == "error":
                 return self._create_error_response(result["message"])
            
            stream_data = result["data"]
            StreamService.start_stream(**stream_data)

            return self._create_success_response("Stream started successfully.", "ok")

        except ValueError as e:
            return self._create_error_response(str(e))
        except Exception as e:
            log_event(logger, "error", f"Unexpected error in start: {e}", event_type="error")
            return self._create_error_response("Something went wrong", "internal_error", 500)

    def update_stream(self):
        try:
            payload = self._parse_request_data()
            data = payload
            validation_errors = stream_schema.validate(data)

            if validation_errors:
                return self._create_error_response("Validation failed!", validation_errors)

            stream_id = data.get("stream_id")
            
            try:
                _stream = stream_schema.load(data)
                result = StreamService.update_stream(stream_id, _stream) 
                
                if result["status"] == "error":
                     return self._create_error_response(result["message"], result.get("error_code"))

                return self._create_success_response(result["message"], result["data"])

            except Exception as e:
                 raise e

        except ValueError as e:
            return self._create_error_response(str(e), status_code=404 if "not found" in str(e) else 400)
        except Exception as e:
            log_event(logger, "error", f"Unexpected error in update_stream: {e}", event_type="error")
            return self._create_error_response("Stream could not be updated", "updating_stream_failed")

    def get(self, stream_id):
        result = StreamService.get_stream(stream_id)
        if result["status"] == "error":
             return tools.JsonResp({"message": "Stream(s) not found!"}, 404)
        
        return tools.JsonResp(result["data"], 200)

    def save_patrol_area(self):
        """Save patrol area to database and update active stream."""
        data = self._parse_request_data()
        stream_id = data.get("stream_id")
        patrol_area = data.get("patrol_area")

        if not stream_id:
            return tools.JsonResp({"status": "error", "message": "Missing stream_id in request data"}, 400)

        if not patrol_area:
            return tools.JsonResp({"status": "error", "message": "Missing patrol_area in request data"}, 400)

        result = PatrolService.save_patrol_area(stream_id=stream_id, patrol_area=patrol_area)
        status_code = 200 if result["status"] == "success" else 400
        if result["status"] == "error" and "not found" in result.get("message", ""):
            status_code = 404
        return tools.JsonResp(result, status_code)

    def get_patrol_area(self):
        data = self._parse_request_data()
        stream_id = data.get("stream_id")
        if not stream_id:
            return tools.JsonResp({"status": "error", "message": "Missing stream_id in request data"}, 400)
        
        result = PatrolService.get_patrol_area(stream_id=stream_id)
        status_code = 200 if result["status"] == "success" else 400
        if result["status"] == "error" and "not found" in result.get("message", ""):
            status_code = 404
        return tools.JsonResp(result, status_code)

    def save_patrol_pattern(self):
        data = self._parse_request_data()
        stream_id = data.get("stream_id")
        patrol_pattern = data.get("patrol_pattern")

        if not stream_id:
             return tools.JsonResp({"status": "error", "message": "Missing stream_id in request data"}, 400)
        if not patrol_pattern:
             return tools.JsonResp({"status": "error", "message": "Missing patrol_pattern in request data"}, 400)

        result = PatrolService.save_patrol_pattern(stream_id=stream_id, patrol_pattern=patrol_pattern)
        status_code = 200 if result["status"] == "success" else 400
        if result["status"] == "error" and "not found" in result.get("message", ""):
            status_code = 404
        return tools.JsonResp(result, status_code)

    def preview_patrol_pattern(self):
        data = self._parse_request_data()
        stream_id = data.get("stream_id")
        patrol_pattern = data.get("patrol_pattern")
        if not stream_id:
             return tools.JsonResp({"status": "error", "message": "Missing stream_id in request data"}, 400)
        if not patrol_pattern:
             return tools.JsonResp({"status": "error", "message": "Missing patrol_pattern in request data"}, 400)
        
        result = PatrolService.preview_patrol_pattern(stream_id=stream_id, patrol_pattern=patrol_pattern)
        status_code = 200 if result["status"] == "success" else 400
        return tools.JsonResp(result, status_code)

    def get_patrol_pattern(self):
        data = self._parse_request_data()
        stream_id = data.get("stream_id")
        if not stream_id:
             return tools.JsonResp({"status": "error", "message": "Missing stream_id in request data"}, 400)
        
        result = PatrolService.get_patrol_pattern(stream_id=stream_id)
        status_code = 200 if result["status"] == "success" else 400
        if result["status"] == "error" and "not found" in result.get("message", ""):
            status_code = 404
        return tools.JsonResp(result, status_code)

    def save_safe_area(self):
        data = self._parse_request_data()
        stream_id = data.get("streamId") or data.get("stream_id")
        coords = data.get("coords")
        static_mode = data.get("static", True)
        reference_image = data.get("image")

        if not stream_id:
             return tools.JsonResp({"status": "error", "message": "Missing streamId in request data"}, 400)
        if not coords:
             return tools.JsonResp({"status": "error", "message": "Missing coords in request data"}, 400)

        result = HazardService.save_safe_area(stream_id=stream_id, coords=coords, static_mode=static_mode, reference_image=reference_image)
        status_code = 200 if result["status"] == "success" else 400
        if result["status"] == "error" and "not found" in result.get("message", ""):
            status_code = 404
        return tools.JsonResp(result, status_code)

    def get_safe_area(self):
        data = self._parse_request_data()
        stream_id = data.get("streamId") or data.get("stream_id")
        if not stream_id:
             return tools.JsonResp({"status": "error", "message": "Missing streamId in request data"}, 400)
        
        result = HazardService.get_safe_area(stream_id=stream_id)
        status_code = 200 if result["status"] == "success" else 400
        if result["status"] == "error" and "not found" in result.get("message", ""):
            status_code = 404
        return tools.JsonResp(result, status_code)

    @staticmethod
    def start_stream(*args, **kwargs):
        return StreamService.start_stream(*args, **kwargs)

    @staticmethod
    def stop_stream(stream_id):
        return StreamService.stop_stream(stream_id)

    @staticmethod
    def start_active_streams():
        return StreamService.start_active_streams()

    @staticmethod
    def handle_patrol_toggle(stream_id, mode, stream_doc):
        return PatrolService.handle_patrol_toggle(stream_id, mode, stream_doc)
    
    @staticmethod
    def start_patrol_if_enabled(stream_id, video_streaming, stream_doc):
        return PatrolService.start_patrol_if_enabled(stream_id, video_streaming, stream_doc)

    @staticmethod
    def initialize_camera_controller(*args, **kwargs):
        return StreamService.initialize_camera_controller(*args, **kwargs)
        
    def bulk_start_streams(self, stream_ids):
        result = StreamService.bulk_start_streams(stream_ids)
        if result["failed_streams"]:
             return tools.JsonResp({"message": f"Bulk start completed with {len(result['failed_streams'])} failures", "data": result}, 207)
        return tools.JsonResp({"message": "All streams started successfully", "data": result}, 200)

    def bulk_stop_streams(self, stream_ids):
        result = StreamService.bulk_stop_streams(stream_ids)
        if result["failed_streams"]:
             return tools.JsonResp({"message": f"Bulk stop completed with {len(result['failed_streams'])} failures", "data": result}, 207)
        return tools.JsonResp({"message": "All streams stopped successfully", "data": result}, 200)

    @staticmethod
    def update_rtsp_link(stream_id, rtsp_link):
        return StreamService.update_rtsp_link(stream_id, rtsp_link)

    def toggle_intrusion_detection(self):
        data = self._parse_request_data()
        stream_id = data.get("stream_id")
        if not stream_id:
             return self._create_error_response("Missing stream_id in request data")
        
        result = HazardService.toggle_intrusion_detection(stream_id=stream_id)
        if result["status"] == "success":
             return self._create_success_response(result["message"], result.get("data"))
        else:
             status_code = 404 if "not found" in result.get("message", "") else 400
             return self._create_error_response(result["message"], status_code=status_code)

    def toggle_patrol(self):
        try:
            data = self._parse_request_data()
            stream_id = data.get("stream_id")
            mode = data.get("mode")

            if not stream_id or not mode:
                return self._create_error_response("Missing stream_id or mode")
            
            result = PatrolService.toggle_patrol(stream_id, mode)
            
            if result["status"] == "success":
                return self._create_success_response(result["message"], result.get("data"))
            else:
                 status_code = 404 if "not_found" == result.get("error_code") else 400
                 if result.get("error_code") == "toggle_failed": status_code=500
                 return self._create_error_response(result["message"], status_code=status_code)

        except Exception as e:
            log_event(logger, "error", f"Error toggling patrol: {e}")
            return self._create_error_response("Failed to toggle patrol", "toggle_failed", 500)
    
    def toggle_patrol_focus(self):
        data = self._parse_request_data()
        stream_id = data.get("stream_id")
        if not stream_id: return self._create_error_response("Missing stream_id")
        result = PatrolService.toggle_patrol_focus(stream_id=stream_id)
        if result["status"] == "success":
             return self._create_success_response(result["message"], result.get("data"))
        return self._create_error_response(result["message"], status_code=404 if "not found" in result.get("message") else 400)

    def toggle_saving_video(self):
        try:
             data = self._parse_request_data()
             stream_id = data.get("stream_id")
             if not stream_id: return self._create_error_response("Missing stream_id")
             
             result = StreamService.toggle_saving_video(stream_id)
             if result["status"] == "success":
                 return self._create_success_response(result["message"], result["data"])
             
             return self._create_error_response(result["message"], status_code=404 if "not found" in result.get("message") else 400)
        except Exception as e:
             log_event(logger, "error", f"Error toggling saving: {e}")
             return self._create_error_response("Failed to toggle saving video")

    def change_autotrack(self):
        try:
             data = self._parse_request_data()
             stream_id = data.get("stream_id")
             if not stream_id: return self._create_error_response("Missing stream_id")
             
             result = PatrolService.change_autotrack(stream_id)
             if result["status"] == "success":
                 return self._create_success_response(result["message"], result["data"])
             return self._create_error_response(result["message"], status_code=400)
        except Exception as e:
             log_event(logger, "error", f"Error toggling autotrack: {e}")
             return self._create_error_response(str(e))

    def get_current_ptz_values(self):
        try:
             data = self._parse_request_data()
             stream_id = data.get("stream_id")
             result = PTZService.get_current_ptz_values(stream_id)
             if result["status"] == "success":
                  return tools.JsonResp(result, 200)
             
             status_code = 404 if "not found" in result.get("message") else 400 # Or 500 based on message
             return tools.JsonResp(result, status_code)
        except Exception:
             return tools.JsonResp({"status": "error", "message": "Invalid format"}, 400)

    def ptz_controls(self):
        try:
             data = self._parse_request_data()
             stream_id = data.get("stream_id")
             command = data.get("command")
             speed = data.get("speed", 0.5)
             
             if not stream_id or not command: return self._create_error_response("Missing stream_id or command")
             
             result = PTZService.ptz_controls(stream_id, command, speed)
             if result["status"] == "success":
                  return tools.JsonResp(result, 200)
             return tools.JsonResp(result, 400 if result.get("error_code") == "not_found" else 500)
        except Exception as e:
             return tools.JsonResp({"status": "error", "message": str(e)}, 500)


    def set_danger_zone(self):
        data = json.loads(request.data)
        image = data.get("image")
        coords = data.get("coords")
        stream_id = data.get("streamId") or data.get("stream_id")
        static_mode = data.get("static", True)

        result = HazardService.set_danger_zone(
            stream_id=stream_id,
            coords=coords,
            image=image,
            static_mode=static_mode
        )
        status_code = 200 if result["status"] == "success" else 400
        if result["status"] == "error" and "not found" in result.get("message", ""):
            status_code = 404
        return tools.JsonResp(result, status_code)

    def set_camera_mode(self):
        data = json.loads(request.data)
        stream_id = data.get("streamId") or data.get("stream_id")
        static_mode = data.get("static", True)
        if not stream_id: return tools.JsonResp({"status":"error", "message":"Missing streamId"}, 400)

        result = HazardService.set_camera_mode(stream_id=stream_id, static_mode=static_mode)
        status_code = 200 if result["status"] == "success" else 400
        if result["status"] == "error" and "not found" in result.get("message", ""):
            status_code = 404
        return tools.JsonResp(result, status_code)

    def get_camera_mode(self):
        data = json.loads(request.data)
        stream_id = data.get("streamId") or data.get("stream_id")
        if not stream_id: return tools.JsonResp({"status":"error", "message":"Missing streamId"}, 400)

        result = HazardService.get_camera_mode(stream_id=stream_id)
        status_code = 200 if result["status"] == "success" else 400
        if result["status"] == "error" and "not found" in result.get("message", ""):
            status_code = 404
        return tools.JsonResp(result, status_code)

    def get_current_frame(self):
        try:
             data = json.loads(request.data)
             stream_id = data.get("stream_id")
             if not stream_id: return tools.JsonResp({"status":"error", "message":"Missing stream_id"}, 400)
             
             result = StreamService.get_current_frame(stream_id)
             if result["status"] == "success":
                  return tools.JsonResp(result, 200)
             return tools.JsonResp(result, 400)
        except Exception:
             return tools.JsonResp({"status":"error", "message":"Invalid request"}, 400)

