# Structured JSON Logging

This document describes the structured JSON logging system implemented for the isafe-guard-backend service.

## Overview

The backend now uses structured JSON logging to provide well-formatted, machine-readable log output suitable for advanced logging systems, monitoring, and analysis.

## Features

- **JSON Format**: All logs are output in structured JSON format
- **Consistent Schema**: Every log entry follows the same structure
- **Contextual Information**: Rich metadata including timestamps, service info, and custom fields
- **Exception Handling**: Structured exception logging with type, message, and traceback
- **Configurable**: Can be toggled between JSON and plain text formats

## Configuration

### Environment Variables

- `LOG_LEVEL`: Set logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO
- `JSON_LOGGING`: Enable/disable JSON logging (true/false). Default: true

### Example

```bash
export LOG_LEVEL=INFO
export JSON_LOGGING=true
```

## Log Entry Structure

Each JSON log entry contains the following fields:

```json
{
  "timestamp": "2025-07-14T09:09:33.631160Z",
  "service": "isafe-guard-backend",
  "level": "INFO",
  "logger": "StreamManager.cam_001",
  "message": "Stream started successfully",
  "module": "stream_manager",
  "function": "start_stream",
  "line": 125,
  "thread": 140451728908992,
  "process": 1551570,
  "event_type": "stream_start",
  "stream_id": "cam_001",
  "camera_id": "CAM_001"
}
```

### Core Fields

- `timestamp`: UTC timestamp in ISO format
- `service`: Service name (isafe-guard-backend)
- `level`: Log level (INFO, WARNING, ERROR, DEBUG)
- `logger`: Logger name (often includes component/stream ID)
- `message`: Human-readable log message
- `module`: Python module name
- `function`: Function name where log was generated
- `line`: Line number in source code
- `thread`: Thread ID
- `process`: Process ID

### Custom Fields

Additional contextual fields are added based on the log type:

- `event_type`: Type of event (stream_start, detection, error, etc.)
- `stream_id`: Stream identifier
- `camera_id`: Camera identifier
- `detection_type`: Type of detection (person, vehicle, etc.)
- `confidence`: Detection confidence score
- `error_code`: Error code for failures
- `retry_count`: Number of retry attempts

## Usage

### Basic Logging

```python
from utils.logging_config import get_logger

logger = get_logger(__name__)
logger.info("This is a basic log message")
logger.warning("This is a warning")
logger.error("This is an error")
```

### Structured Event Logging

```python
from utils.logging_config import get_logger, log_event

logger = get_logger("StreamManager.cam_001")

# Stream event
log_event(
    logger, "info", 
    "Stream started successfully",
    event_type="stream_start",
    stream_id="cam_001",
    camera_id="CAM_001",
    extra={"rtsp_url": "rtsp://example.com/stream"}
)

# Detection event
log_event(
    logger, "info", 
    "Object detected in stream",
    event_type="detection",
    stream_id="cam_001",
    detection_type="person",
    confidence=0.95,
    extra={"bbox": [100, 200, 300, 400]}
)

# Error event
log_event(
    logger, "error", 
    "Failed to connect to camera",
    event_type="connection_error",
    stream_id="cam_002",
    camera_id="CAM_002",
    extra={"error_code": "CONN_TIMEOUT", "retry_count": 3}
)
```

### Exception Logging

```python
try:
    # Some operation
    pass
except Exception as e:
    logger.exception("Operation failed", extra={"operation": "stream_start"})
```

## Common Event Types

The system uses standardized event types for consistency:

- `stream_start`: Stream initialization
- `stream_stop`: Stream termination
- `detection`: Object detection events
- `ptz_move`: PTZ camera movement
- `ptz_autotrack_toggle`: PTZ autotrack enable/disable
- `connection_error`: Connection failures
- `validation_error`: Input validation failures
- `processing_error`: Processing failures

## Migration

All existing logging calls have been automatically migrated to use the new structured logging system. The migration script `utils/logging_migration.py` can be used to update additional files if needed.

## Testing

Use the test script to verify logging functionality:

```bash
python src/test_logging_simple.py
```

## Integration with Monitoring Systems

The JSON format is designed to integrate with:

- **ELK Stack**: Elasticsearch, Logstash, Kibana
- **Fluent Bit/Fluentd**: Log collection and forwarding
- **Prometheus**: Metrics extraction from logs
- **Grafana**: Log visualization and alerting
- **Splunk**: Log analysis and monitoring

## Example Log Analysis Queries

### Elasticsearch/Kibana

```json
{
  "query": {
    "bool": {
      "must": [
        {"term": {"event_type": "detection"}},
        {"term": {"stream_id": "cam_001"}},
        {"range": {"confidence": {"gte": 0.8}}}
      ]
    }
  }
}
```

### Grafana

```
{service="isafe-guard-backend"} | json | event_type="detection" | confidence > 0.8
```

## Best Practices

1. **Use structured logging**: Prefer `log_event()` over basic logger methods for important events
2. **Include context**: Always include relevant IDs (stream_id, camera_id)
3. **Use standard event types**: Stick to predefined event types for consistency
4. **Avoid sensitive data**: Never log passwords, tokens, or personal information
5. **Use appropriate log levels**: INFO for normal operations, WARNING for issues, ERROR for failures
6. **Include error context**: Add error codes and retry counts for debugging

## Performance Considerations

- JSON serialization has minimal overhead
- Structured logging provides better performance for log analysis
- Log level filtering reduces output in production
- Asynchronous logging can be enabled for high-throughput scenarios