import os
import logging
import numpy as np
import subprocess
from typing import Tuple, Optional
from config import STATIC_DIR

RTMP_MEDIA_SERVER = os.getenv("RTMP_MEDIA_SERVER", "rtmp://localhost:1935")


def du(path: str) -> str:
    return subprocess.check_output(["du", "-sh", path]).split()[0].decode("utf-8")


def df() -> Optional[str]:
    try:
        result = subprocess.check_output(
            "df -h | awk '$NF==\"/\" {print $2, $3, $4}'", shell=True, text=True
        )
        return result.strip()
    except subprocess.CalledProcessError as e:
        logging.error(f"Error: {e}")
        return None


def create_video_writer(
    stream_id: str,
    frame: np.ndarray,
    timestamp: str,
    model_name: str,
    output_fps: float,
) -> Tuple[subprocess.Popen, str]:
    EVENT_VIDEO_DIR = os.path.join(STATIC_DIR, stream_id, "videos")

    video_directory = os.path.abspath(
        os.path.join(os.path.dirname(__file__), EVENT_VIDEO_DIR)
    )
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
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    return process, video_name


def start_ffmpeg_process(stream_id: str) -> subprocess.Popen:
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
        "1280x720",
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
    return subprocess.Popen(ffmpeg_command, stdin=subprocess.PIPE)


def start_gstreamer_process(stream_id: str) -> subprocess.Popen:
    gst_command = [
        "gst-launch-1.0",
        "fdsrc",
        "!",
        "videoparse",
        "width=1280",
        "height=720",
        "framerate=30/1",
        "format=bgr",  # matches bgr24 input
        "!",
        "videoconvert",
        "!",
        "x264enc",
        "tune=zerolatency",
        "speed-preset=ultrafast",
        "!",
        "flvmux",
        "streamable=true",
        "!",
        "rtmpsink",
        f"location={RTMP_MEDIA_SERVER}/live/{stream_id}",
    ]
    return subprocess.Popen(gst_command, stdin=subprocess.PIPE)
