import asyncio
import json
import struct
import cv2
import numpy as np
import time
from typing import Optional, Dict, Any, Callable
from threading import Thread
from utils.logging_config import get_logger, log_event

try:
    import websockets
except ImportError:
    raise ImportError(
        "websockets library is required for KDL detector. "
        "Install it with: pip install websockets"
    )

logger = get_logger(__name__)

MAX_DATA_SIZE = 10 * 1024 * 1024  # 10MB


class KDLWebSocketClient:
    """WebSocket client for KDL detection server."""

    def __init__(
        self,
        server_url: str,
        port: int = 12321,
        endpoint: str = "/send_frame",
    ):
        """Initialize KDL WebSocket client.

        Args:
            server_url: URL of the KDL server
            port: Port number for the server
            endpoint: WebSocket endpoint path
        """
        self.server_url = server_url
        self.port = port
        self.endpoint = endpoint
        self.uri = f"ws://{server_url}:{port}{endpoint}"

        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[Thread] = None
        self.running = False

        # Frame queue for sending (will be initialized in async context)
        self.frame_queue: Optional[asyncio.Queue] = None

        # Callback for receiving results
        self.result_callback: Optional[Callable[[Dict[str, Any], bytes], None]] = None

        # Track the current stream_id (assumes only one stream uses KDL at a time)
        self.current_stream_id: str = "default"

        # Track last send time per stream for rate limiting (1 FPS per stream)
        self.last_send_time: Dict[str, float] = {}

        log_event(
            logger,
            "info",
            f"KDL WebSocket client initialized with URI: {self.uri}",
            event_type="kdl_init",
        )

    def start(self):
        """Start the WebSocket client in a background thread."""
        if self.running:
            log_event(
                logger,
                "warning",
                "KDL WebSocket client is already running",
                event_type="kdl_warning",
            )
            return

        self.running = True
        self.thread = Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()

        log_event(
            logger,
            "info",
            "KDL WebSocket client started",
            event_type="kdl_start",
        )

    def _run_event_loop(self):
        """Run the asyncio event loop in a background thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self._connect_and_run())
        except Exception as e:
            log_event(
                logger,
                "error",
                f"KDL WebSocket event loop error: {e}",
                event_type="kdl_error",
            )
        finally:
            self.loop.close()

    async def _connect_and_run(self):
        """Connect to the WebSocket server and run send/receive loops."""
        while self.running:
            try:
                log_event(
                    logger,
                    "info",
                    f"Connecting to KDL server at {self.uri}",
                    event_type="kdl_connect",
                )

                async with websockets.connect(
                    self.uri,
                    max_size=MAX_DATA_SIZE,
                    ping_interval=20,
                    ping_timeout=10,
                ) as websocket:
                    self.websocket = websocket
                    self.frame_queue = asyncio.Queue(maxsize=10)

                    log_event(
                        logger,
                        "info",
                        "Successfully connected to KDL server",
                        event_type="kdl_connected",
                    )

                    # Run send and receive loops concurrently
                    await asyncio.gather(
                        self._send_loop(),
                        self._receive_loop(),
                    )

            except websockets.exceptions.WebSocketException as e:
                log_event(
                    logger,
                    "error",
                    f"KDL WebSocket connection error: {e}",
                    event_type="kdl_error",
                )
                if self.running:
                    log_event(
                        logger,
                        "info",
                        "Reconnecting to KDL server in 5 seconds...",
                        event_type="kdl_reconnect",
                    )
                    await asyncio.sleep(5)
            except Exception as e:
                log_event(
                    logger,
                    "error",
                    f"Unexpected error in KDL WebSocket: {e}",
                    event_type="kdl_error",
                )
                if self.running:
                    await asyncio.sleep(5)

    async def _send_loop(self):
        """Continuously send frames from the queue to the server.

        Rate limited to 1 frame per second per stream.
        """
        while self.running:
            try:
                # Wait for a frame with timeout
                frame_data = await asyncio.wait_for(self.frame_queue.get(), timeout=1.0)

                # Check rate limiting: only send if 1 second has passed since last send for this stream
                current_time = time.time()
                stream_id = self.current_stream_id
                last_send = self.last_send_time.get(stream_id, 0)

                time_since_last_send = current_time - last_send

                if time_since_last_send >= 1.0:
                    # Enough time has passed, send the frame
                    if self.websocket:
                        await self.websocket.send(frame_data)
                        self.last_send_time[stream_id] = current_time
                        # log_event(
                        #     logger,
                        #     "info",
                        #     f"Sent frame to KDL server for stream {stream_id} ({len(frame_data) / 1024:.2f} KB)",
                        #     event_type="kdl_send",
                        # )
                else:
                    # Drop frame due to rate limiting
                    log_event(
                        logger,
                        "debug",
                        f"Dropped frame for stream {stream_id} (rate limiting: {time_since_last_send:.2f}s since last send)",
                        event_type="kdl_rate_limit",
                    )

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log_event(
                    logger,
                    "error",
                    f"Error in KDL send loop: {e}",
                    event_type="kdl_error",
                )

    async def _receive_loop(self):
        """Continuously receive results from the server."""
        while self.running:
            try:
                if self.websocket:
                    data = await self.websocket.recv()

                    # Parse multipart data: [4 bytes: json_len][json_len bytes: metadata][remaining: image]
                    json_len = struct.unpack(">I", data[:4])[0]
                    metadata = json.loads(data[4 : 4 + json_len])
                    image_bytes = data[4 + json_len :]

                    # log_event(
                    #     logger,
                    #     "info",
                    #     f"Received result from KDL server - Metadata: {metadata}, Image size: {len(image_bytes) / 1024:.2f} KB",
                    #     event_type="kdl_receive",
                    # )

                    # Call the result callback if set
                    # Pass the current_stream_id via metadata since KDL server doesn't track it
                    if self.result_callback:
                        # log_event(
                        #     logger,
                        #     "info",
                        #     f"Calling result callback with stream_id: {self.current_stream_id}",
                        #     event_type="kdl_callback",
                        # )
                        # Add stream_id to metadata
                        metadata["stream_id"] = self.current_stream_id
                        self.result_callback(metadata, image_bytes)
                    else:
                        log_event(
                            logger,
                            "warning",
                            "No result callback set!",
                            event_type="kdl_warning",
                        )

            except Exception as e:
                if self.running:
                    log_event(
                        logger,
                        "error",
                        f"Error in KDL receive loop: {e}",
                        event_type="kdl_error",
                    )
                break

    def send_frame(self, frame: np.ndarray, stream_id: str):
        """Queue a frame to be sent to the KDL server.

        Args:
            frame: The frame to send (numpy array)
            stream_id: The stream ID for tracking
        """
        if not self.running or self.frame_queue is None:
            log_event(
                logger,
                "warning",
                "KDL WebSocket client is not running, cannot send frame",
                event_type="kdl_warning",
            )
            return

        # Store the stream_id for this frame
        self.current_stream_id = stream_id

        try:
            # Encode frame as JPEG
            _, encoded = cv2.imencode(".jpg", frame)
            frame_bytes = encoded.tobytes()

            # Queue the frame for sending (non-blocking)
            if self.loop:
                asyncio.run_coroutine_threadsafe(
                    self._queue_frame(frame_bytes, stream_id), self.loop
                )
        except Exception as e:
            log_event(
                logger,
                "error",
                f"Error encoding/queuing frame for KDL: {e}",
                event_type="kdl_error",
            )

    async def _queue_frame(self, frame_bytes: bytes, stream_id: str):
        """Internal method to queue frame in async context."""
        if self.frame_queue is not None:
            try:
                # Try to put without blocking, drop if queue is full
                self.frame_queue.put_nowait(frame_bytes)
            except asyncio.QueueFull:
                log_event(
                    logger,
                    "warning",
                    f"KDL frame queue full for stream {stream_id}, dropping frame",
                    event_type="kdl_warning",
                )

    def set_result_callback(self, callback: Callable[[Dict[str, Any], bytes], None]):
        """Set the callback function for when results are received.

        Args:
            callback: Function that takes (metadata, image_bytes) as arguments
        """
        self.result_callback = callback

    def stop(self):
        """Stop the WebSocket client."""
        self.running = False

        if self.loop and self.websocket:
            asyncio.run_coroutine_threadsafe(self.websocket.close(), self.loop)

        if self.thread:
            self.thread.join(timeout=5)

        log_event(
            logger,
            "info",
            "KDL WebSocket client stopped",
            event_type="kdl_stop",
        )


# Global KDL client instance
_kdl_client: Optional[KDLWebSocketClient] = None


def get_kdl_client() -> Optional[KDLWebSocketClient]:
    """Get the global KDL WebSocket client instance."""
    return _kdl_client


def initialize_kdl_client(server_url: str, port: int = 12321) -> KDLWebSocketClient:
    """Initialize the global KDL WebSocket client.

    Args:
        server_url: URL of the KDL server
        port: Port number for the server

    Returns:
        The initialized KDL client instance
    """
    global _kdl_client

    if _kdl_client is not None:
        log_event(
            logger,
            "warning",
            "KDL client already initialized",
            event_type="kdl_warning",
        )
        return _kdl_client

    _kdl_client = KDLWebSocketClient(server_url, port)
    _kdl_client.start()

    return _kdl_client


def shutdown_kdl_client():
    """Shutdown the global KDL WebSocket client."""
    global _kdl_client

    if _kdl_client:
        _kdl_client.stop()
        _kdl_client = None
