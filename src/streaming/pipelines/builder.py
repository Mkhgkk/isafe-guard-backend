import os
import urllib.parse
from ..types import PipelineConfig

os.environ.setdefault("GST_PLUGIN_FEATURE_RANK", "avdec_h265:257,avdec_h264:257")


class PipelineBuilder:
    """Builder class for creating GStreamer pipelines."""

    @staticmethod
    def _extract_credentials(stream_url: str) -> tuple[str, str, str]:
        """
        Extract username and password from URL and return cleaned URL with credentials.

        Args:
            stream_url: RTSP or SRT URL that may contain credentials

        Returns:
            tuple: (cleaned_url, username, password)
        """
        if not (stream_url.startswith("rtsp://") or stream_url.startswith("srt://")):
            return stream_url, "", ""

        try:
            # Parse the URL
            parsed = urllib.parse.urlparse(stream_url)

            # Extract username and password
            username = parsed.username or ""
            password = parsed.password or ""

            # Reconstruct URL without credentials
            port_part = f":{parsed.port}" if parsed.port else ""
            path_part = parsed.path if parsed.path else ""
            query_part = f"?{parsed.query}" if parsed.query else ""

            cleaned_url = f"{parsed.scheme}://{parsed.hostname}{port_part}{path_part}{query_part}"
            return cleaned_url, username, password

        except Exception:
            # If parsing fails, return original URL with empty credentials
            return stream_url, "", ""

    @staticmethod
    def create_primary_pipeline(config: PipelineConfig) -> str:
        """Create the primary GStreamer pipeline with TCP transport for RTSP or SRT."""
        cleaned_url, username, password = PipelineBuilder._extract_credentials(config.rtsp_link)

        # Detect protocol type
        if config.rtsp_link.startswith("srt://"):
            # SRT pipeline - credentials in URI if present
            srt_url = f"{cleaned_url}?passphrase={urllib.parse.quote(password, safe='')}" if password else cleaned_url
            return (
                f"srtsrc uri={srt_url} latency={config.latency} "
                f"! identity name=bitrate_monitor_{config.sink_name} "
                f"! tsdemux "
                f"! decodebin force-sw-decoders=true "
                f"! videoconvert "
                f"! videoscale "
                f"! videorate drop-only=true "
                f"! video/x-raw, width={config.width}, height={config.height}, format={config.format}, framerate=10/1 "
                f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
                f"emit-signals=true sync=false"
            )
        else:
            # RTSP pipeline - use user-id and user-pw properties (no encoding needed)
            auth_params = ""
            if username:
                auth_params += f'user-id="{username}" '
            if password:
                auth_params += f'user-pw="{password}" '

            return (
                f"rtspsrc location={cleaned_url} {auth_params}"
                f"latency={config.latency} "
                f"protocols=tcp "
                f"buffer-mode=auto drop-on-latency=true retry={config.retry_count} timeout={config.timeout} "
                f"! application/x-rtp, media=video "
                f"! rtpjitterbuffer latency=200 "
                f"! identity name=bitrate_monitor_{config.sink_name} "
                f"! decodebin force-sw-decoders=true "
                f"! videoconvert "
                f"! videoscale "
                f"! videorate drop-only=true "
                f"! video/x-raw, width={config.width}, height={config.height}, format={config.format}, framerate=10/1 "
                f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
                f"emit-signals=true sync=false"
            )

    @staticmethod
    def create_alternative_pipeline(config: PipelineConfig) -> str:
        """Create an alternative, more flexible pipeline for RTSP or SRT."""
        cleaned_url, username, password = PipelineBuilder._extract_credentials(config.rtsp_link)

        # Detect protocol type
        if config.rtsp_link.startswith("srt://"):
            # SRT alternative pipeline (simpler version)
            srt_url = f"{cleaned_url}?passphrase={urllib.parse.quote(password, safe='')}" if password else cleaned_url
            return (
                f"srtsrc uri={srt_url} "
                f"! identity name=bitrate_monitor_{config.sink_name} "
                f"! decodebin force-sw-decoders=true "
                f"! videoconvert "
                f"! videoscale "
                f"! videorate drop-only=true "
                f"! video/x-raw, width={config.width}, height={config.height}, format={config.format}, framerate=10/1 "
                f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
                f"emit-signals=true sync=false"
            )
        else:
            # RTSP alternative pipeline - use user-id and user-pw properties (no encoding needed)
            auth_params = ""
            if username:
                auth_params += f'user-id="{username}" '
            if password:
                auth_params += f'user-pw="{password}" '

            return (
                f"rtspsrc location={cleaned_url} {auth_params}"
                f"latency={config.latency} "
                f"protocols=tcp "
                f"retry={config.retry_count} timeout=10 "
                f"! identity name=bitrate_monitor_{config.sink_name} "
                f"! decodebin force-sw-decoders=true "
                f"! videoconvert "
                f"! videoscale "
                f"! videorate drop-only=true "
                f"! video/x-raw, width={config.width}, height={config.height}, format={config.format}, framerate=10/1 "
                f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
                f"emit-signals=true sync=false"
            )
