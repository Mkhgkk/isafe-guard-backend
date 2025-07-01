from ..types import PipelineConfig

class PipelineBuilder:
    """Builder class for creating GStreamer pipelines."""
    
    @staticmethod
    def create_primary_pipeline(config: PipelineConfig) -> str:
        """Create the primary GStreamer pipeline with TCP transport."""
        return (
            f"rtspsrc location={config.rtsp_link} latency={config.latency} "
            f"protocols=tcp "
            f"buffer-mode=auto drop-on-latency=true retry={config.retry_count} timeout={config.timeout} "
            f"! application/x-rtp, media=video "
            f"! rtpjitterbuffer latency=200 "
            f"! decodebin "
            f"! videoconvert "
            f"! videoscale "
            f"! video/x-raw, width={config.width}, height={config.height}, format={config.format} "
            f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
            f"emit-signals=true sync=false"
        )
    
    @staticmethod
    def create_alternative_pipeline(config: PipelineConfig) -> str:
        """Create an alternative, more flexible pipeline."""
        return (
            f"rtspsrc location={config.rtsp_link} latency={config.latency} "
            f"protocols=tcp "
            f"retry={config.retry_count} timeout=10 "
            f"! decodebin "
            f"! videoconvert "
            f"! videoscale "
            f"! video/x-raw, width={config.width}, height={config.height}, format={config.format} "
            f"! appsink name={config.sink_name} drop=true max-buffers={config.max_buffers} "
            f"emit-signals=true sync=false"
        )