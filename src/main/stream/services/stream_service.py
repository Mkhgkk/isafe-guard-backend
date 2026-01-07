import cv2
import os
import shutil
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, Any
from urllib.parse import urlparse

from database import get_database
from config import STATIC_DIR
from events import emit_event, EventType
from main.shared import streams, safe_area_trackers
from ptz import CameraController, PTZAutoTracker
from streaming import StreamManager
from utils.logging_config import get_logger, log_event
from .patrol_service import PatrolService

logger = get_logger(__name__)


class StreamService:
    @staticmethod
    def _add_derived_fields(stream):
        """Add derived boolean fields to a stream object."""
        # Direct fields from database
        stream["saving_video"] = stream.get("saving_video", True)
        stream["intrusion_detection"] = stream.get("intrusion_detection", False)
        stream["patrol_mode"] = stream.get("patrol_mode", "off")

        # Focus enabled during patrol
        stream["focus_enabled"] = stream.get("enable_focus_during_patrol", False)

        # Hazard area configured (based on safe_area being set)
        stream["is_hazard_area_configured"] = stream.get("safe_area") is not None

        # PTZ support (based on having all required PTZ credentials)
        has_ptz = all(
            [
                stream.get("cam_ip"),
                stream.get("ptz_port"),
                stream.get("ptz_username"),
                stream.get("ptz_password"),
            ]
        )
        stream["has_ptz"] = has_ptz

        # Grid patrol configured (based on patrol_area being set)
        stream["is_grid_patrol_configured"] = stream.get("patrol_area") is not None

        # Pattern patrol configured (based on patrol_pattern being set and having coordinates)
        patrol_pattern = stream.get("patrol_pattern")
        stream["is_pattern_patrol_configured"] = (
            patrol_pattern is not None
            and patrol_pattern.get("coordinates") is not None
            and len(patrol_pattern.get("coordinates", [])) >= 2
        )

        return stream

    @staticmethod
    def get_stream(stream_id=None):
        """Get stream(s) with derived fields."""
        db = get_database()

        if stream_id:
            stream = db.streams.find_one({"stream_id": stream_id})
            if not stream:
                return {"status": "error", "message": "Stream not found"}

            # Add unresolved event count for single stream
            unresolved_count = db.events.count_documents(
                {"stream_id": stream_id, "is_resolved": {"$ne": True}}
            )
            stream["unresolved_events"] = unresolved_count
            stream["has_unresolved"] = unresolved_count > 0

            # Add derived fields
            stream = StreamService._add_derived_fields(stream)
            return {"status": "success", "data": stream}

        else:
            streams_list = list(db.streams.find())
            if not streams_list:
                return {"status": "success", "data": []}

            # Get unresolved event counts for all streams
            pipeline = [
                {"$match": {"is_resolved": {"$ne": True}}},
                {"$group": {"_id": "$stream_id", "unresolved_count": {"$sum": 1}}},
            ]
            event_counts = list(db.events.aggregate(pipeline))
            count_dict = {
                item["_id"]: item["unresolved_count"] for item in event_counts
            }

            # Add event counts and derived fields to each stream
            for stream in streams_list:
                unresolved_count = count_dict.get(stream["stream_id"], 0)
                stream["unresolved_events"] = unresolved_count
                stream["has_unresolved"] = unresolved_count > 0

                # Add derived fields
                stream = StreamService._add_derived_fields(stream)

            return {"status": "success", "data": streams_list}

    @staticmethod
    def create_stream(data, start_stream_flag=False):
        """Create a new stream."""
        db = get_database()
        stream_id = data["stream_id"]

        # Check if stream id is unique
        existing_stream_id = db.streams.find_one({"stream_id": stream_id})
        if existing_stream_id:
            return {
                "status": "error",
                "message": "There is already a stream with the stream ID.",
                "error_code": "stream_id_exists",
            }

        # Create the stream
        stream = db.streams.insert_one(data)
        inserted_id = str(stream.inserted_id)
        data["_id"] = inserted_id

        if start_stream_flag:
            # Start the stream immediately if requested
            StreamService.start_stream(**data)
            log_event(
                logger,
                "info",
                f"Stream {stream_id} started immediately after creation.",
                event_type="stream_start",
            )

        return {
            "status": "success",
            "message": "Stream has been successfully created.",
            "data": data,
        }

    @staticmethod
    def delete_stream(stream_id):
        """Delete a stream."""
        db = get_database()

        # STATIC_DIR is already absolute from config.py
        stream_dir = os.path.join(STATIC_DIR, stream_id)

        # Remove stream directory if it exists
        if os.path.exists(stream_dir):
            shutil.rmtree(stream_dir)

        # Check if stream is running and stop it
        stream_manager = streams.get(stream_id, None)
        is_stream_running = stream_manager and stream_manager.running

        if is_stream_running:
            StreamService.stop_stream(stream_id)

        # Delete event videos and stream from database
        db.events.delete_many({"stream_id": stream_id})
        result = db.streams.delete_one({"stream_id": stream_id})

        if result.deleted_count == 0:
            return {"status": "error", "message": "Stream not found"}

        return {"status": "success", "message": "Stream deleted successfully."}

    @staticmethod
    def update_stream(stream_id, data):
        """Update a stream."""
        db = get_database()

        # Check if stream exists
        existing_stream = db.streams.find_one({"stream_id": stream_id})
        if not existing_stream:
            return {
                "status": "error",
                "message": f"Stream with ID '{stream_id}' not found.",
            }

        # Check if stream is running and stop it
        stream_manager = streams.get(stream_id, None)
        is_stream_running = stream_manager and stream_manager.running

        if is_stream_running:
            StreamService.stop_stream(stream_id)

        try:
            db.streams.replace_one({"stream_id": stream_id}, data)
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error updating stream {stream_id}: {e}",
                event_type="error",
            )
            return {
                "status": "error",
                "message": "Stream could not be updated",
                "error_code": "updating_stream_failed",
            }

        # Restart if it was running
        if is_stream_running:
            StreamService.start_stream(**data)

        return {
            "status": "success",
            "message": "Stream has been successfully updated.",
            "data": data,
        }

    @staticmethod
    def restart_stream(stream_id):
        """Restart a stream."""
        db = get_database()

        # Check if stream exists in active streams (memory)
        video_streaming = streams.get(stream_id)

        log_event(
            logger,
            "info",
            f"Restarting stream: {stream_id}",
            event_type="stream_restart",
        )

        # Get stream configuration from database
        stream_config = db.streams.find_one({"stream_id": stream_id})
        if not stream_config:
            return {
                "status": "error",
                "message": f"Stream with ID '{stream_id}' not found.",
            }

        # Stop the stream first if stream is active
        if video_streaming and video_streaming.running:
            try:
                StreamService.stop_stream(stream_id)
                log_event(
                    logger,
                    "info",
                    f"Successfully stopped stream: {stream_id}",
                    event_type="stream_stop",
                )
            except Exception as e:
                log_event(
                    logger,
                    "error",
                    f"Error stopping stream {stream_id}: {e}",
                    event_type="error",
                )
                return {
                    "status": "error",
                    "message": f"Failed to stop stream: {str(e)}",
                    "error_code": "stop_failed",
                }

        # Start the stream with the configuration
        try:
            StreamService.start_stream(**stream_config)

            log_event(
                logger,
                "info",
                f"Successfully restarted stream: {stream_id}",
                event_type="stream_restart",
            )

            return {
                "status": "success",
                "message": f"Stream '{stream_id}' restarted successfully.",
                "data": {"stream_id": stream_id},
            }

        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error starting stream {stream_id}: {e}",
                event_type="error",
            )
            return {
                "status": "error",
                "message": f"Failed to start stream after stop: {str(e)}",
                "error_code": "start_failed",
            }

    @staticmethod
    def start_active_streams():
        """Start all streams marked as active in database."""
        db = get_database()
        streams_list = list(db.streams.find())

        for stream in streams_list:
            if stream.get("is_active"):
                log_event(
                    logger,
                    "info",
                    f"Starting active stream {stream.get('stream_id')}",
                    event_type="info",
                )
                try:
                    StreamService.start_stream(**stream)
                except Exception as e:
                    log_event(
                        logger,
                        "error",
                        f"Error starting stream {stream.get('stream_id')}: {e}",
                        event_type="error",
                    )

    @staticmethod
    def start_stream(
        rtsp_link: str,
        model_name: str,
        stream_id: str,
        cam_ip: Optional[str] = None,
        ptz_port: Optional[int] = None,
        ptz_username: Optional[str] = None,
        ptz_password: Optional[str] = None,
        profile_name: Optional[str] = None,
        home_pan: Optional[float] = None,
        home_tilt: Optional[float] = None,
        home_zoom: Optional[float] = None,
        patrol_area: Optional[dict] = None,
        patrol_pattern: Optional[dict] = None,
        safe_area: Optional[dict] = None,
        intrusion_detection: Optional[bool] = None,
        saving_video: Optional[bool] = None,
        **kwargs: Any,
    ) -> None:
        supports_ptz = all([cam_ip, ptz_port, ptz_username, ptz_password])
        ptz_autotrack = kwargs.get("ptz_autotrack", False)

        if intrusion_detection is None:
            intrusion_detection = False

        if saving_video is None:
            saving_video = True

        if stream_id in streams:
            log_event(
                logger,
                "info",
                f"Stream {stream_id} is already running!",
                event_type="info",
            )
            return

        video_streaming = StreamManager(
            rtsp_link,
            model_name,
            stream_id,
            ptz_autotrack,
            intrusion_detection,
            saving_video,
        )
        video_streaming.start_stream()
        streams[stream_id] = video_streaming

        log_event(
            logger,
            "info",
            f"Stream startup debug for {stream_id}: safe_area={'exists' if safe_area else 'None'}, tracker_in_dict={stream_id in safe_area_trackers}",
            event_type="info",
        )
        if safe_area:
            log_event(
                logger,
                "info",
                f"Safe area data: static_mode={safe_area.get('static_mode', 'missing')}, coords_count={len(safe_area.get('coords', []))}, ref_image={safe_area.get('reference_image', 'missing')}",
                event_type="info",
            )

        if safe_area and stream_id in safe_area_trackers:
            safe_area_tracker = safe_area_trackers[stream_id]
            try:
                static_mode = safe_area.get("static_mode", True)
                safe_area_tracker.set_static_mode(static_mode)

                coords = safe_area.get("coords")
                reference_image = safe_area.get("reference_image")

                if coords and len(coords) > 0:
                    if reference_image:
                        try:
                            parsed_url = urlparse(reference_image)
                            file_name = os.path.basename(parsed_url.path)
                            REFERENCE_FRAME_DIR = "../../static/frame_refs"
                            image_path = os.path.join(
                                os.path.dirname(__file__),
                                REFERENCE_FRAME_DIR,
                                file_name,
                            )

                            log_event(
                                logger,
                                "info",
                                f"Attempting to load reference image for {stream_id}: {image_path} (from {reference_image})",
                                event_type="info",
                            )

                            reference_frame = cv2.imread(image_path)
                            if reference_frame is not None:
                                safe_area_tracker.update_safe_area(
                                    reference_frame, coords
                                )
                                log_event(
                                    logger,
                                    "info",
                                    f"Loaded safe area with {len(coords)} zones and reference frame for stream {stream_id}",
                                    event_type="info",
                                )
                            else:
                                log_event(
                                    logger,
                                    "warning",
                                    f"Could not load reference frame for stream {stream_id}: {image_path}",
                                    event_type="warning",
                                )
                        except Exception as img_e:
                            log_event(
                                logger,
                                "warning",
                                f"Failed to load reference frame for stream {stream_id}: {img_e}",
                                event_type="warning",
                            )

                    log_event(
                        logger,
                        "info",
                        f"Loaded safe area static mode ({static_mode}) with {len(coords)} coordinate zones for stream {stream_id}",
                        event_type="info",
                    )
                else:
                    log_event(
                        logger,
                        "info",
                        f"Loaded safe area static mode ({static_mode}) for stream {stream_id} (no coordinates)",
                        event_type="info",
                    )

            except Exception as e:
                log_event(
                    logger,
                    "warning",
                    f"Failed to initialize safe area for stream {stream_id}: {e}",
                    event_type="warning",
                )
        elif safe_area:
            log_event(
                logger,
                "warning",
                f"Safe area data exists for stream {stream_id} but SafeAreaTracker not found in registry",
                event_type="warning",
            )
        elif stream_id in safe_area_trackers:
            log_event(
                logger,
                "info",
                f"SafeAreaTracker exists for stream {stream_id} but no safe area data in database",
                event_type="info",
            )
        else:
            log_event(
                logger,
                "info",
                f"No safe area configuration found for stream {stream_id} and no tracker registered",
                event_type="info",
            )

        try:
            db = get_database()
            db.streams.update_one(
                {"stream_id": stream_id}, {"$set": {"is_active": True}}
            )
            log_event(
                logger,
                "info",
                f"Updated stream {stream_id} status to active in database",
                event_type="info",
            )
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Failed to update stream {stream_id} active status in database: {e}",
                event_type="error",
            )

        if supports_ptz:
            ptz_thread = threading.Thread(
                target=StreamService.initialize_camera_controller,
                args=(
                    cam_ip,
                    ptz_port,
                    ptz_username,
                    ptz_password,
                    stream_id,
                    profile_name,
                    patrol_area,
                    patrol_pattern,
                ),
                daemon=True,
            )
            ptz_thread.start()

    @staticmethod
    def stop_stream(stream_id):
        """Stop a stream."""
        db = get_database()
        if stream_id not in streams:
            try:
                db.streams.update_one(
                    {"stream_id": stream_id}, {"$set": {"is_active": False}}
                )
                log_event(
                    logger,
                    "info",
                    f"Updated stream {stream_id} status to inactive in database (not in memory)",
                    event_type="info",
                )
            except Exception as e:
                log_event(
                    logger,
                    "error",
                    f"Failed to update stream {stream_id} inactive status in database: {e}",
                    event_type="error",
                )
            return

        try:
            video_streaming = streams.get(stream_id)
            if video_streaming:
                video_streaming.stop_streaming()
                video_streaming.camera_controller = None
            else:
                return

            del streams[stream_id]

            try:
                db.streams.update_one(
                    {"stream_id": stream_id}, {"$set": {"is_active": False}}
                )
                log_event(
                    logger,
                    "info",
                    f"Updated stream {stream_id} status to inactive in database",
                    event_type="info",
                )
            except Exception as e:
                log_event(
                    logger,
                    "error",
                    f"Failed to update stream {stream_id} inactive status in database: {e}",
                    event_type="error",
                )

        except Exception as e:
            try:
                db.streams.update_one(
                    {"stream_id": stream_id}, {"$set": {"is_active": False}}
                )
            except Exception:
                pass
            raise RuntimeError(f"Failed to stop stream {stream_id}: {e}")


    @staticmethod
    def initialize_camera_controller(
        cam_ip,
        ptz_port,
        ptz_username,
        ptz_password,
        stream_id,
        profile_name=None,
        patrol_area=None,
        patrol_pattern=None,
    ):
        """This function will be executed in a background thread to avoid blocking the loop."""
        try:
            stream = streams[stream_id]
            camera_controller = CameraController(
                cam_ip, ptz_port, ptz_username, ptz_password, profile_name
            )
            stream.camera_controller = camera_controller

            ptz_auto_tracker = PTZAutoTracker(
                cam_ip, ptz_port, ptz_username, ptz_password, profile_name
            )
            stream.ptz_auto_tracker = ptz_auto_tracker

            db = get_database()
            stream_doc = db.streams.find_one({"stream_id": stream_id})

            saved_home_position = (
                stream_doc.get("patrol_home_position") if stream_doc else None
            )

            if saved_home_position:
                try:
                    pan = saved_home_position.get("pan")
                    tilt = saved_home_position.get("tilt")
                    zoom = saved_home_position.get("zoom")

                    if pan is not None and tilt is not None and zoom is not None:
                        ptz_auto_tracker.update_default_position(pan, tilt, zoom)
                        log_event(
                            logger,
                            "info",
                            f"Updated autotracker with saved home position for stream {stream_id}: pan={pan:.3f}, tilt={tilt:.3f}, zoom={zoom:.3f}",
                            event_type="ptz_home_loaded",
                        )
                except Exception as e:
                    log_event(
                        logger,
                        "warning",
                        f"Failed to update autotracker with saved home position for stream {stream_id}: {e}",
                        event_type="warning",
                    )
            else:
                try:
                    pan, tilt, zoom = camera_controller.get_current_position()
                    default_home_position = {
                        "pan": pan,
                        "tilt": tilt,
                        "zoom": zoom,
                        "saved_at": datetime.now(timezone.utc),
                    }

                    db.streams.update_one(
                        {"stream_id": stream_id},
                        {"$set": {"patrol_home_position": default_home_position}},
                    )

                    ptz_auto_tracker.update_default_position(pan, tilt, zoom)

                    log_event(
                        logger,
                        "info",
                        f"Saved and set default home position for stream {stream_id}: pan={pan:.3f}, tilt={tilt:.3f}, zoom={zoom:.3f}",
                        event_type="ptz_default_home_saved",
                    )
                except Exception as e:
                    log_event(
                        logger,
                        "warning",
                        f"Failed to save default home position for stream {stream_id}: {e}",
                        event_type="warning",
                    )

            if patrol_area:
                try:
                    ptz_auto_tracker.set_patrol_area(patrol_area)
                    log_event(
                        logger,
                        "info",
                        f"Loaded saved patrol area for stream {stream_id}: {patrol_area}",
                        event_type="info",
                    )
                except Exception as e:
                    log_event(
                        logger,
                        "warning",
                        f"Failed to set patrol area for stream {stream_id}: {e}",
                        event_type="warning",
                    )

            if patrol_pattern and patrol_pattern.get("coordinates"):
                try:
                    coordinates = patrol_pattern.get("coordinates", [])
                    if len(coordinates) >= 2:
                        ptz_auto_tracker.set_custom_patrol_pattern(coordinates)
                        log_event(
                            logger,
                            "info",
                            f"Loaded saved patrol pattern for stream {stream_id} with {len(coordinates)} waypoints",
                            event_type="info",
                        )
                except Exception as e:
                    log_event(
                        logger,
                        "warning",
                        f"Failed to set patrol pattern for stream {stream_id}: {e}",
                        event_type="warning",
                    )

            enable_focus = (
                stream_doc.get("enable_focus_during_patrol", False)
                if stream_doc
                else False
            )
            try:
                ptz_auto_tracker.set_patrol_parameters(
                    focus_max_zoom=1.0, enable_focus_during_patrol=enable_focus
                )
                log_event(
                    logger,
                    "info",
                    f"Loaded focus setting for stream {stream_id}: enable_focus={enable_focus}",
                    event_type="ptz_focus_loaded",
                )
            except Exception as e:
                log_event(
                    logger,
                    "warning",
                    f"Failed to set focus parameters for stream {stream_id}: {e}",
                    event_type="warning",
                )

            log_event(
                logger,
                "info",
                f"PTZ configured for stream {stream_id}.",
                event_type="info",
            )

            result = PatrolService.start_patrol_if_enabled(
                stream_id, stream, stream_doc
            )
            if result["patrol_started"]:
                log_event(
                    logger,
                    "info",
                    f"Auto-started {result['patrol_mode']} patrol on system restart for stream {stream_id}",
                    event_type="patrol_auto_started",
                )

        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error initializing PTZ for stream {stream_id}: {e}",
                event_type="error",
            )

    @staticmethod
    def bulk_start_streams(stream_ids):
        """Start multiple streams by their IDs."""
        try:
            db = get_database()
            results = []
            failed_streams = []

            for stream_id in stream_ids:
                try:
                    stream_doc = db.streams.find_one({"stream_id": stream_id})
                    if not stream_doc:
                        failed_streams.append(
                            {"stream_id": stream_id, "error": "Stream not found"}
                        )
                        continue

                    StreamService.start_stream(**stream_doc)
                    results.append({"stream_id": stream_id, "status": "started"})

                except Exception as e:
                    failed_streams.append({"stream_id": stream_id, "error": str(e)})

            return {
                "started_streams": results,
                "failed_streams": failed_streams,
                "total_requested": len(stream_ids),
                "successful_starts": len(results),
            }

        except Exception as e:
            log_event(
                logger, "error", f"Error in bulk start streams: {e}", event_type="error"
            )
            # Raising is fine, caller handles 500
            raise RuntimeError(f"Failed to start streams: {e}")

    @staticmethod
    def bulk_stop_streams(stream_ids):
        """Stop multiple streams by their IDs."""
        try:
            db = get_database()
            results = []
            failed_streams = []

            for stream_id in stream_ids:
                try:
                    stream_doc = db.streams.find_one({"stream_id": stream_id})
                    if not stream_doc:
                        failed_streams.append(
                            {"stream_id": stream_id, "error": "Stream not found"}
                        )
                        continue

                    StreamService.stop_stream(stream_id)
                    results.append({"stream_id": stream_id, "status": "stopped"})

                except Exception as e:
                    failed_streams.append({"stream_id": stream_id, "error": str(e)})

            return {
                "stopped_streams": results,
                "failed_streams": failed_streams,
                "total_requested": len(stream_ids),
                "successful_stops": len(results),
            }

        except Exception as e:
            log_event(
                logger, "error", f"Error in bulk stop streams: {e}", event_type="error"
            )
            raise RuntimeError(f"Failed to stop streams: {e}")

    @staticmethod
    def update_rtsp_link(stream_id, rtsp_link):
        stream = streams.get(stream_id)
        if stream is None:
            raise ValueError(f"Stream ID {stream_id} does not exist.")

        if not rtsp_link:
            raise ValueError("Invalid RTSP link provided.")

        try:
            if stream.running:
                stream.stop_streaming()
                stream.rtsp_link = rtsp_link
            else:
                stream.rtsp_link = rtsp_link

        except Exception as e:
            raise RuntimeError(
                f"Failed to update RTSP link for stream {stream_id}: {e}"
            )

    @staticmethod
    def toggle_saving_video(stream_id):
        """Toggle saving video for a stream."""
        db = get_database()

        # Get current stream from database
        current_stream = db.streams.find_one({"stream_id": stream_id})
        if not current_stream:
            return {
                "status": "error",
                "message": f"Stream with ID '{stream_id}' not found.",
            }

        # Toggle saving video state
        current_saving_video = current_stream.get("saving_video", True)
        new_saving_video_value = not current_saving_video

        # Update in database
        result = db.streams.update_one(
            {"stream_id": stream_id},
            {"$set": {"saving_video": new_saving_video_value}},
        )

        if result.modified_count == 0:
            log_event(
                logger,
                "warning",
                f"No document was modified for stream_id: {stream_id}",
                event_type="warning",
            )

        # Update running stream if it exists
        stream_manager = streams.get(stream_id)
        if stream_manager and stream_manager.running:
            stream_manager.set_saving_video(new_saving_video_value)
            log_event(
                logger,
                "info",
                f"Updated running stream saving video for {stream_id}",
                event_type="info",
            )

        log_event(
            logger,
            "info",
            f"Saving video toggled for stream {stream_id}: {current_saving_video} -> {new_saving_video_value}",
            event_type="info",
        )

        return {
            "status": "success",
            "message": f"Saving video {'enabled' if new_saving_video_value else 'disabled'} for stream {stream_id}",
            "data": {"stream_id": stream_id, "saving_video": new_saving_video_value},
        }


    @staticmethod
    def get_current_frame(stream_id):
        """Get current frame from an active stream"""
        video_streaming = streams.get(stream_id)
        if video_streaming is None:
            return {
                "status": "error",
                "message": "Stream with the given ID is not active!",
            }

        try:
            frame = video_streaming.get_frame()
            if frame is None:
                return {"status": "error", "message": "Failed to get frame"}

            timestamp = int(time.time())
            filename = f"frame_{timestamp}_{stream_id}.jpg"

            # Using relative path logic again.
            REFERENCE_FRAME_DIR = "../../static/frame_refs"
            file_directory = os.path.abspath(
                os.path.join(os.path.dirname(__file__), REFERENCE_FRAME_DIR)
            )

            if not os.path.exists(file_directory):
                os.makedirs(file_directory)

            file_path = os.path.join(file_directory, filename)

            cv2.imwrite(file_path, frame)

            return {"status": "success", "message": "ok", "data": filename}

        except Exception as e:
            logger.error(f"Error getting frame for stream {stream_id}: {e}")
            traceback.print_exc()
            return {"status": "error", "message": f"Error getting frame: {str(e)}"}
