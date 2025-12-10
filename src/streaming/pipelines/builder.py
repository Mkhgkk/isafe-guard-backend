import os
import urllib.parse
from ..types import PipelineConfig

os.environ.setdefault("GST_PLUGIN_FEATURE_RANK", "avdec_h265:257,avdec_h264:257")


class PipelineBuilder:
    """Builder class for creating GStreamer pipelines."""

    @staticmethod
    def _escape_stream_url(stream_url: str) -> str:
        """
        Properly escape RTSP or SRT URL to handle special characters in credentials.

        Args:
            stream_url: RTSP or SRT URL that may contain special characters in username/password

        Returns:
            str: Properly escaped URL safe for GStreamer pipeline
        """
        if not (stream_url.startswith("rtsp://") or stream_url.startswith("srt://")):
            return stream_url

        try:
            # Parse the URL
            parsed = urllib.parse.urlparse(stream_url)

            # If there's no username/password, return as-is
            if not parsed.username and not parsed.password:
                return stream_url

            # Escape username and password separately
            escaped_username = (
                urllib.parse.quote(parsed.username, safe="") if parsed.username else ""
            )
            escaped_password = (
                urllib.parse.quote(parsed.password, safe="") if parsed.password else ""
            )

            # Reconstruct the URL with escaped credentials
            if escaped_username and escaped_password:
                credentials = f"{escaped_username}:{escaped_password}@"
            elif escaped_username:
                credentials = f"{escaped_username}@"
            else:
                credentials = ""

            # Reconstruct the full URL
            port_part = f":{parsed.port}" if parsed.port else ""
            path_part = parsed.path if parsed.path else ""
            query_part = f"?{parsed.query}" if parsed.query else ""

            escaped_url = f"{parsed.scheme}://{credentials}{parsed.hostname}{port_part}{path_part}{query_part}"
            return escaped_url

        except Exception:
            # If parsing fails, return original URL as fallback
            return stream_url

    @staticmethod
    def create_primary_pipeline(config: PipelineConfig) -> str:
        """Create the primary GStreamer pipeline with TCP transport for RTSP or SRT."""
        escaped_url = PipelineBuilder._escape_stream_url(config.rtsp_link)

        # Detect protocol type
        if config.rtsp_link.startswith("srt://"):
            # SRT pipeline
            return (
                f"srtsrc uri={escaped_url} latency={config.latency} "
                f"! identity name=bitrate_monitor_{config.sink_name} "
                f"! tsdemux "
                f"! decodebin force-sw-decoders=true "
                f"! videoconvert "
                f"! videoscale "
                f"! video/x-raw, width={config.width}, height={config.height}, format={config.format} "
                f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
                f"emit-signals=true sync=false"
            )
        else:
            # RTSP pipeline (default)
            return (
                f"rtspsrc location={escaped_url} latency={config.latency} "
                f"protocols=tcp "
                f"buffer-mode=auto drop-on-latency=true retry={config.retry_count} timeout={config.timeout} "
                f"! application/x-rtp, media=video "
                f"! rtpjitterbuffer latency=200 "
                f"! identity name=bitrate_monitor_{config.sink_name} "
                f"! decodebin force-sw-decoders=true "
                f"! videoconvert "
                f"! videoscale "
                f"! video/x-raw, width={config.width}, height={config.height}, format={config.format} "
                f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
                f"emit-signals=true sync=false"
            )

    @staticmethod
    def create_alternative_pipeline(config: PipelineConfig) -> str:
        """Create an alternative, more flexible pipeline for RTSP or SRT."""
        escaped_url = PipelineBuilder._escape_stream_url(config.rtsp_link)

        # Detect protocol type
        if config.rtsp_link.startswith("srt://"):
            # SRT alternative pipeline (simpler version)
            return (
                f"srtsrc uri={escaped_url} "
                f"! identity name=bitrate_monitor_{config.sink_name} "
                f"! decodebin force-sw-decoders=true "
                f"! videoconvert "
                f"! videoscale "
                f"! video/x-raw, width={config.width}, height={config.height}, format={config.format} "
                f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
                f"emit-signals=true sync=false"
            )
        else:
            # RTSP alternative pipeline (default)
            return (
                f"rtspsrc location={escaped_url} latency={config.latency} "
                f"protocols=tcp "
                f"retry={config.retry_count} timeout=10 "
                f"! identity name=bitrate_monitor_{config.sink_name} "
                f"! decodebin force-sw-decoders=true "
                f"! videoconvert "
                f"! videoscale "
                f"! video/x-raw, width={config.width}, height={config.height}, format={config.format} "
                f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
                f"emit-signals=true sync=false"
            )
