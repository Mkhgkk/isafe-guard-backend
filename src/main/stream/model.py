import json
import os
import shutil
import logging
import threading
from typing import Optional, Any

from flask import current_app as app  # pyright: ignore[reportMissingImports]
from flask import request  # pyright: ignore[reportMissingImports]
from marshmallow import Schema, ValidationError, fields, validate  # pyright: ignore[reportMissingImports]

from config import STATIC_DIR
from main import tools
from main.shared import streams  # pyright: ignore[reportMissingImports]
from ptz import CameraController, PTZAutoTracker
from streaming import StreamManager


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
    ptz_port = fields.Integer()
    ptz_username = fields.String()

    # class Meta:
    #     unknown = INCLUDE


stream_schema = StreamSchema()


class Stream:

    def create_stream(self):
        data = json.loads(request.data)
        validation_errors = stream_schema.validate(data)

        # Validate data
        if validation_errors:
            return tools.JsonResp(
                {"message": "Validation failed!", "data": validation_errors}, 400
            )

        # Check if stream id is unique
        stream_id = data["stream_id"]
        existing_stream_id = app.db.streams.find_one({"stream_id": stream_id})
        if existing_stream_id:
            return tools.JsonResp(
                {
                    "message": "There is already a stream with the stream ID.",
                    "error": "stream_id_exists",
                },
                400,
            )

        try:
            data = stream_schema.load(data)
            stream = app.db.streams.insert_one(data)
            inserted_id = str(stream.inserted_id)
            data["_id"] = inserted_id

            return tools.JsonResp(
                {"message": "Stream has been successfully created.", "data": data}, 200
            )
        except Exception as e:
            print(e)
            return tools.JsonResp(
                {
                    "message": "Stream could not be created",
                    "error": "creating_stream_failed",
                },
                400,
            )

    def delete_stream(self):
        # # TODO:
        # # delete all related events

        # # stop stream (if running)
        # # delete the stream
        # pass

        data = json.loads(request.data)
        stream_id = data.get("stream_id")
        stream_dir = os.path.join(STATIC_DIR, stream_id)

        try:
            if os.path.exists(stream_dir):
                shutil.rmtree(
                    stream_dir,
                )
            else:
                print(f"Directory does not exist: {stream_dir}")

            # check if stream is running and stop it
            stream_manager = streams.get(stream_id, None)
            is_stream_running = stream_manager and stream_manager.running

            if is_stream_running:
                Stream.stop_stream(stream_id)

            # delete event videos
            app.db.events.delete_many({"stream_id": stream_id})
            app.db.streams.delete_one({"stream_id": stream_id})

            return tools.JsonResp(
                {"message": "Stream deleted successfully.", "data": "ok"}, 200
            )

        except Exception as e:
            return tools.JsonResp(
                {"message": "Deletion failed!", "error": "stream_deletion_failed"}, 400
            )

    def stop(self):
        data = json.loads(request.data)
        stream_id_only = StreamSchema(only=("stream_id",))
        validation_errors = stream_id_only.validate(data)

        if validation_errors:
            print(validation_errors)
            return tools.JsonResp(
                {"message": "Validation failed!", "error": validation_errors}, 400
            )

        stream_id = data["stream_id"]

        try:
            # Find the stream in the database
            stream = app.db.streams.find_one({"stream_id": stream_id}, {"_id": 0})
            if not stream:
                return tools.JsonResp(
                    {
                        "message": "Stream with the given ID not found.",
                        "error": "stream_not_found",
                    },
                    404,
                )

            # asyncio.run(Stream.start_stream(**stream))
            Stream.stop_stream(stream_id)

            # Update the `is_active` status
            app.db.streams.update_one(
                {"stream_id": stream_id}, {"$set": {"is_active": False}}
            )

            return tools.JsonResp(
                {"message": "Stream stopped successfully.", "data": "ok"}, 200
            )

        except Exception as e:
            print(e)
            return tools.JsonResp(
                {"message": "Something went wrong", "error": "internal_error"}, 500
            )

    def start(self):
        data = json.loads(request.data)
        stream_id_only = StreamSchema(only=("stream_id",))
        validation_errors = stream_id_only.validate(data)

        if validation_errors:
            print(validation_errors)
            return tools.JsonResp(
                {"message": "Validation failed!", "error": validation_errors}, 400
            )

        stream_id = data["stream_id"]

        try:
            # Find the stream in the database
            stream = app.db.streams.find_one({"stream_id": stream_id}, {"_id": 0})
            if not stream:
                return tools.JsonResp(
                    {
                        "message": "Stream with the given ID not found.",
                        "error": "stream_not_found",
                    },
                    404,
                )

            Stream.start_stream(**stream)

            # Update the `is_active` status
            app.db.streams.update_one(
                {"stream_id": stream_id}, {"$set": {"is_active": True}}
            )

            return tools.JsonResp(
                {"message": "Stream started successfully.", "data": "ok"}, 200
            )

        except Exception as e:
            print(e)
            return tools.JsonResp(
                {"message": "Something went wrong", "error": "internal_error"}, 500
            )

    def update_stream(self):
        data = json.loads(request.data)
        validation_errors = stream_schema.validate(data)

        if validation_errors:
            return tools.JsonResp(
                {"message": "Validation failed!", "data": validation_errors}, 400
            )

        stream_id = data["stream_id"]
        current_stream = app.db.streams.find_one({"stream_id": stream_id})

        if not current_stream:
            return tools.JsonResp(
                {
                    "message": "Stream with the given ID doesn't exist.",
                    "error": "stream_not_found",
                },
                404,
            )

        # check if stream is running and stop it
        stream_manager = streams.get(stream_id, None)
        is_stream_running = stream_manager and stream_manager.running

        if is_stream_running:
            Stream.stop_stream(stream_id)

        try:
            _stream = stream_schema.load(data)
            _stream = app.db.streams.replace_one({"stream_id": stream_id}, _stream)

            return tools.JsonResp(
                {"message": "Stream has been successfully updated.", "data": data}, 200
            )
        except Exception as e:
            print(e)
            return tools.JsonResp(
                {
                    "message": "Stream could not be updated",
                    "error": "updating_stream_failed",
                },
                400,
            )
        finally:
            if is_stream_running:
                Stream.start_stream(**data)
                # Update the `is_active` status
                app.db.streams.update_one(
                    {"stream_id": stream_id}, {"$set": {"is_active": True}}
                )

    def get(self, stream_id):
        resp = tools.JsonResp({"message": "Stream(s) not found!"}, 404)

        if stream_id:
            stream = app.db.streams.find_one({"stream_id": stream_id})
            if stream:
                resp = tools.JsonResp(stream, 200)

        else:
            streams = list(app.db.streams.find())
            if streams:
                resp = tools.JsonResp(streams, 200)

        return resp

    @staticmethod
    def start_stream(
        rtsp_link: str,
        model_name: str,
        stream_id: str,
        cam_ip: Optional[str] = None,
        ptz_port: Optional[int] = None,
        ptz_username: Optional[str] = None,
        ptz_password: Optional[str] = None,
        home_pan: Optional[float] = None,
        home_tilt: Optional[float] = None,
        home_zoom: Optional[float] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        supports_ptz = all([cam_ip, ptz_port, ptz_username, ptz_password])
        ptz_autotrack = all([home_pan, home_tilt, home_zoom])

        if stream_id in streams:
            logging.info(f"Stream {stream_id} is already running!")
            return

        # Start the video stream immediately
        video_streaming = StreamManager(rtsp_link, model_name, stream_id, ptz_autotrack)
        video_streaming.start_stream()
        streams[stream_id] = video_streaming

        # Schedule stop stream
        # stop_time = datetime.datetime.fromtimestamp(end_timestamp)
        # scheduler.add_job(Stream.stop_stream, 'date', run_date=stop_time, args=[stream_id])
        # print(f"Stream {stream_id} scheduled to stop at {stop_time}.")

        if supports_ptz:
            ptz_thread = threading.Thread(
                target=Stream.initialize_camera_controller, 
                args=(cam_ip, ptz_port, ptz_username, ptz_password, stream_id), 
                daemon=True 
            )
            ptz_thread.start()

    @staticmethod
    def initialize_camera_controller(
        cam_ip, ptz_port, ptz_username, ptz_password, stream_id
    ):
        """This function will be executed in a background thread to avoid blocking the loop."""
        try:
            stream = streams[stream_id]
            camera_controller = CameraController(
                cam_ip, ptz_port, ptz_username, ptz_password
            )
            stream.camera_controller = camera_controller

            # if camera controller is initialized successfully, then we initialize auto tracker
            ptz_auto_tracker = PTZAutoTracker(cam_ip, ptz_port, ptz_username, ptz_password)
            stream.ptz_auto_tracker = ptz_auto_tracker

            logging.info(f"PTZ configured for stream {stream_id}.")
        except Exception as e:
                # Send notification when this fails
                logging.info(f"Error initializing PTZ for stream {stream_id}: {e}")


    @staticmethod
    def stop_stream(stream_id):
        if stream_id not in streams:
            # raise ValueError(f"Stream ID {stream_id} does not exist in streams.")
            return

        try:
            video_streaming = streams.get(stream_id)
            if video_streaming:
                video_streaming.stop_streaming()
                video_streaming.camera_controller = None
            else:
                # raise ValueError(f"Stream ID {stream_id} is not active.")
                return

            del streams[stream_id]

            # if stream_id in camera_controllers:
            #     del camera_controllers[stream_id]
        except Exception as e:
            raise RuntimeError(f"Failed to stop stream {stream_id}: {e}")

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
                # stream.start_stream()
            else:
                stream.rtsp_link = rtsp_link

        except Exception as e:
            raise RuntimeError(
                f"Failed to update RTSP link for stream {stream_id}: {e}"
            )

    @staticmethod
    def start_active_streams():
        streams = list(app.db.streams.find())

        for stream in streams:
            if stream["is_active"]:
                logging.info(stream)
                try:
                    Stream.start_stream(**stream)
                except Exception as e:
                    logging.error(f"Error starting stream {stream.stream_id}")
