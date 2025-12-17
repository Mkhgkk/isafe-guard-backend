import os
import subprocess
import threading
import re
from typing import Tuple
from utils.logging_config import get_logger, log_event
from utils.config_loader import config
from config import STATIC_DIR
import numpy as np

logger = get_logger(__name__)

FRAME_HEIGHT = config.get("processing.frame_height")
FRAME_WIDTH = config.get("processing.frame_width")
RTMP_MEDIA_SERVER = config.get("streaming.rtmp_server")


def _log_gstreamer_output(stream, log_level: str, stream_id: str, output_type: str):
    """Log GStreamer output line by line."""
    try:
        for line in iter(stream.readline, b""):
            if line.strip():
                decoded_line = line.decode("utf-8", errors="replace").strip()
                log_event(
                    logger,
                    log_level,
                    f"GStreamer {output_type}: {decoded_line}",
                    event_type="gstreamer_output",
                    stream_id=stream_id,
                    extra={"output_type": output_type, "raw_message": decoded_line},
                )
    except Exception as e:
        log_event(
            logger,
            "error",
            f"Error reading GStreamer {output_type} for stream {stream_id}: {str(e)}",
            event_type="gstreamer_logging_error",
            stream_id=stream_id,
            extra={"output_type": output_type, "error": str(e)},
        )
    finally:
        stream.close()


def _log_ffmpeg_output(
    stream, stream_id: str, output_type: str, process_type: str = "ffmpeg"
):
    """Log FFmpeg output line by line, filtering for important information."""
    try:
        for line in iter(stream.readline, b""):
            if line.strip():
                decoded_line = line.decode("utf-8", errors="replace").strip()

                # Skip verbose/unimportant lines
                if any(
                    skip_pattern in decoded_line
                    for skip_pattern in [
                        "configuration:",  # Long build config
                        "libav",  # Library version lines
                        "built with",  # Build info
                        "[lib",  # Encoder details like [libx264 @ 0x...]
                        "i16 v,h,dc,p:",  # Detailed encoding stats
                        "i8 v,h,dc,ddl",  # Detailed encoding stats
                        "i4 v,h,dc,ddl",  # Detailed encoding stats
                        "mb I  I16",  # Macroblock stats
                        "mb P  I16",  # Macroblock stats
                        "mb B  I16",  # Macroblock stats
                        "ref P L0:",  # Reference frame stats
                        "ref B L0:",  # Reference frame stats
                        "8x8 transform",  # Transform stats
                        "coded y,uvDC",  # Color component stats
                        "Weighted P-Frames",  # Weighted frame stats
                    ]
                ):
                    continue

                # Determine importance and log level
                should_log = False
                log_level = "info"

                if any(
                    keyword in decoded_line.lower()
                    for keyword in ["error", "failed", "invalid"]
                ):
                    log_level = "error"
                    should_log = True
                elif any(
                    keyword in decoded_line.lower()
                    for keyword in ["warning", "deprecated"]
                ):
                    log_level = "warning"
                    should_log = True
                elif decoded_line.startswith("ffmpeg version"):
                    log_level = "info"
                    should_log = True
                elif any(
                    pattern in decoded_line
                    for pattern in [
                        "Input #",
                        "Output #",
                        "Stream #",
                        "Stream mapping:",
                        "Duration:",
                        "encoder :",
                        "video:",
                        "audio:",
                    ]
                ):
                    # Stream/input/output info
                    log_level = "info"
                    should_log = True
                elif "frame=" in decoded_line and "fps=" in decoded_line:
                    # Progress updates - log occasionally
                    frame_match = re.search(r"frame=\s*(\d+)", decoded_line)
                    if frame_match:
                        frame_num = int(frame_match.group(1))
                        # Log every 100 frames or final frame
                        if frame_num % 100 == 0 or "Lsize=" in decoded_line:
                            log_level = "info"
                            should_log = True
                elif decoded_line.startswith("video:") and "audio:" in decoded_line:
                    # Final summary
                    log_level = "info"
                    should_log = True
                elif "kb/s:" in decoded_line and decoded_line.count(" ") < 5:
                    # Final bitrate summary
                    log_level = "info"
                    should_log = True

                if should_log:
                    # Extract key information for structured logging
                    extra_info = {
                        "output_type": output_type,
                        "process_type": process_type,
                    }

                    # Parse progress information
                    if "frame=" in decoded_line:
                        frame_match = re.search(r"frame=\s*(\d+)", decoded_line)
                        fps_match = re.search(r"fps=\s*([\d.]+)", decoded_line)
                        time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", decoded_line)
                        bitrate_match = re.search(
                            r"bitrate=\s*([\d.]+\w+)", decoded_line
                        )

                        if frame_match:
                            extra_info["frame_count"] = str(frame_match.group(1))
                        if fps_match:
                            extra_info["fps"] = fps_match.group(1)
                        if time_match:
                            extra_info["duration"] = time_match.group(1)
                        if bitrate_match:
                            extra_info["bitrate"] = bitrate_match.group(1)

                    log_event(
                        logger,
                        log_level,
                        f"FFmpeg {output_type}: {decoded_line}",
                        event_type="ffmpeg_output",
                        stream_id=stream_id,
                        extra=extra_info,
                    )
    except Exception as e:
        log_event(
            logger,
            "error",
            f"Error reading FFmpeg {output_type} for stream {stream_id}: {str(e)}",
            event_type="ffmpeg_logging_error",
            stream_id=stream_id,
            extra={
                "output_type": output_type,
                "process_type": process_type,
                "error": str(e),
            },
        )
    finally:
        stream.close()


def create_video_writer(
    stream_id: str,
    frame: np.ndarray,
    timestamp: str,
    model_name: str,
    output_fps: float,
) -> Tuple[subprocess.Popen, str]:
    """Create FFmpeg video writer process with logging."""
    # STATIC_DIR is already absolute from config.py
    video_directory = os.path.join(STATIC_DIR, stream_id, "videos")
    os.makedirs(video_directory, exist_ok=True)

    video_name = f"video_{stream_id}_{model_name}_{timestamp}.mp4"
    video_path = os.path.join(video_directory, video_name)
    height, width, _ = frame.shape

    command = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(output_fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        video_path,
    ]

    log_event(
        logger,
        "info",
        f"Starting FFmpeg video writer for stream {stream_id}",
        event_type="ffmpeg_start",
        stream_id=stream_id,
        extra={"process_type": "video_writer", "output_path": video_path},
    )

    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    # Start threads to capture and log stdout/stderr
    stdout_thread = threading.Thread(
        target=_log_ffmpeg_output,
        args=(process.stdout, stream_id, "stdout", "video_writer"),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_log_ffmpeg_output,
        args=(process.stderr, stream_id, "stderr", "video_writer"),
        daemon=True,
    )

    stdout_thread.start()
    stderr_thread.start()

    return process, video_name


def start_ffmpeg_process(stream_id: str) -> subprocess.Popen:
    """Start FFmpeg streaming process with logging."""
    ffmpeg_command = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{FRAME_WIDTH}x{FRAME_HEIGHT}",
        "-r",
        "20",
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-f",
        "flv",
        f"{RTMP_MEDIA_SERVER}/live/{stream_id}",
    ]

    log_event(
        logger,
        "info",
        f"Starting FFmpeg streaming process for stream {stream_id}",
        event_type="ffmpeg_start",
        stream_id=stream_id,
        extra={"process_type": "streamer", "rtmp_server": RTMP_MEDIA_SERVER},
    )

    process = subprocess.Popen(
        ffmpeg_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Start threads to capture and log stdout/stderr
    stdout_thread = threading.Thread(
        target=_log_ffmpeg_output,
        args=(process.stdout, stream_id, "stdout", "streamer"),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_log_ffmpeg_output,
        args=(process.stderr, stream_id, "stderr", "streamer"),
        daemon=True,
    )

    stdout_thread.start()
    stderr_thread.start()

    return process


def start_gstreamer_process(stream_id: str) -> subprocess.Popen:
    """Start GStreamer process with logging."""
    gst_command = [
        "gst-launch-1.0",
        "fdsrc",
        "!",
        "videoparse",
        f"width={FRAME_WIDTH}",
        f"height={FRAME_HEIGHT}",
        "framerate=30/1",
        "format=bgr",  # matches bgr24 input
        "!",
        "videoconvert",
        "!",
        "x264enc",
        "bitrate=2500",  # 2.5 Mbps for 720p
        "speed-preset=veryfast",  # Better quality than ultrafast
        "tune=zerolatency",
        "key-int-max=60",  # Keyframe every 2 seconds
        "qp-min=18",  # Minimum quantization (higher quality)
        "qp-max=28",  # Maximum quantization (prevent too low quality)
        "!",
        "flvmux",
        "streamable=true",
        "!",
        "rtmpsink",
        f"location={RTMP_MEDIA_SERVER}/live/{stream_id}",
    ]

    log_event(
        logger,
        "info",
        f"Starting GStreamer process for stream {stream_id}",
        event_type="gstreamer_start",
        stream_id=stream_id,
        extra={"command": " ".join(gst_command), "rtmp_server": RTMP_MEDIA_SERVER},
    )

    try:
        process = subprocess.Popen(
            gst_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Start threads to capture and log stdout/stderr
        stdout_thread = threading.Thread(
            target=_log_gstreamer_output,
            args=(process.stdout, "info", stream_id, "stdout"),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_log_gstreamer_output,
            args=(process.stderr, "warning", stream_id, "stderr"),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        log_event(
            logger,
            "info",
            f"GStreamer process started successfully for stream {stream_id}",
            event_type="gstreamer_started",
            stream_id=stream_id,
            extra={"pid": process.pid},
        )

        return process

    except Exception as e:
        log_event(
            logger,
            "error",
            f"Failed to start GStreamer process for stream {stream_id}: {str(e)}",
            event_type="gstreamer_error",
            stream_id=stream_id,
            extra={"error": str(e)},
        )
        raise
