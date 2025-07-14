# Log Viewing REST API

This document describes the REST API endpoints for viewing and managing application logs.

## Overview

The Log API provides comprehensive access to application logs with filtering, searching, and analytics capabilities. All logs are automatically stored in MongoDB with structured JSON format.

## Base URL

All log API endpoints are prefixed with `/api/logs`

## Authentication

Currently, log endpoints don't require authentication. Consider adding authentication for production use.

## Endpoints

### 1. Get Logs

**GET** `/api/logs/`

Retrieve logs with optional filtering and pagination.

**Query Parameters:**
- `level` (string): Filter by log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `logger` (string): Filter by logger name (supports partial matching)
- `message` (string): Filter by message content (supports partial matching)
- `event_type` (string): Filter by event type
- `stream_id` (string): Filter by stream ID
- `camera_id` (string): Filter by camera ID
- `detection_type` (string): Filter by detection type
- `start_time` (string): Start time in ISO format (e.g., "2025-07-14T00:00:00Z")
- `end_time` (string): End time in ISO format
- `limit` (integer): Number of logs to return (max 1000, default 100)
- `offset` (integer): Number of logs to skip (default 0)
- `sort_order` (string): Sort order "asc" or "desc" (default "desc")

**Example:**
```bash
GET /api/logs/?level=ERROR&stream_id=cam_001&limit=50&sort_order=desc
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "logs": [
      {
        "_id": "64f1234567890abcdef12345",
        "timestamp": "2025-07-14T12:34:56.789Z",
        "service": "isafe-guard-backend",
        "level": "ERROR",
        "logger": "StreamManager.cam_001",
        "message": "Failed to connect to camera",
        "module": "stream_manager",
        "function": "start_stream",
        "line": 125,
        "thread": 140181716300480,
        "process": 1,
        "event_type": "connection_error",
        "stream_id": "cam_001",
        "camera_id": "CAM_001",
        "error_code": "CONN_TIMEOUT",
        "created_at": "2025-07-14T12:34:56.789Z"
      }
    ],
    "total_count": 1247,
    "limit": 50,
    "offset": 0,
    "has_more": true
  }
}
```

### 2. Get Log Statistics

**GET** `/api/logs/statistics`

Get aggregated log statistics and analytics.

**Query Parameters:**
- `level` (string): Filter by log level
- `start_time` (string): Start time for statistics
- `end_time` (string): End time for statistics
- `stream_id` (string): Filter by stream ID
- `event_type` (string): Filter by event type

**Example:**
```bash
GET /api/logs/statistics?start_time=2025-07-14T00:00:00Z&end_time=2025-07-14T23:59:59Z
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "total_logs": 15432,
    "error_count": 127,
    "warning_count": 456,
    "level_distribution": [
      {"_id": "INFO", "count": 12849},
      {"_id": "WARNING", "count": 456},
      {"_id": "ERROR", "count": 127}
    ],
    "event_type_distribution": [
      {"_id": "detection", "count": 8934},
      {"_id": "stream_start", "count": 145},
      {"_id": "connection_error", "count": 67}
    ],
    "stream_distribution": [
      {"_id": "cam_001", "count": 5643},
      {"_id": "cam_002", "count": 4321}
    ],
    "recent_activity": [
      {"_id": {"year": 2025, "month": 7, "day": 14, "hour": 12}, "count": 234}
    ]
  }
}
```

### 3. Advanced Log Search

**POST** `/api/logs/search`

Perform advanced log search with complex criteria.

**Request Body:**
```json
{
  "level": "ERROR",
  "start_time": "2025-07-14T00:00:00Z",
  "end_time": "2025-07-14T23:59:59Z",
  "message": "connection",
  "stream_id": "cam_001",
  "limit": 100,
  "offset": 0,
  "sort_order": "desc"
}
```

**Response:** Same format as GET `/api/logs/`

### 4. Get Recent Logs

**GET** `/api/logs/recent`

Get the most recent 100 log entries.

**Response:** Same format as GET `/api/logs/` with 100 most recent logs.

### 5. Get Available Log Levels

**GET** `/api/logs/levels`

Get list of available log levels.

**Response:**
```json
{
  "status": "success",
  "data": {
    "levels": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
  }
}
```

### 6. Get Available Event Types

**GET** `/api/logs/event-types`

Get list of event types found in recent logs.

**Response:**
```json
{
  "status": "success",
  "data": {
    "event_types": [
      "detection",
      "stream_start",
      "stream_stop",
      "connection_error",
      "ptz_move",
      "validation_error"
    ]
  }
}
```

### 7. Get Stream Information

**GET** `/api/logs/streams`

Get list of stream IDs found in logs with their log counts.

**Response:**
```json
{
  "status": "success",
  "data": {
    "streams": [
      {"stream_id": "cam_001", "log_count": 5643},
      {"stream_id": "cam_002", "log_count": 4321},
      {"stream_id": "cam_003", "log_count": 2108}
    ]
  }
}
```

### 8. Cleanup Old Logs

**POST** `/api/logs/cleanup`

Delete old logs to free up storage space.

**Request Body:**
```json
{
  "days_to_keep": 30
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Deleted 1247 old log entries",
  "data": {
    "deleted_count": 1247,
    "days_to_keep": 30
  }
}
```

## Log Entry Structure

Each log entry contains the following fields:

### Core Fields
- `_id`: Unique MongoDB document ID
- `timestamp`: UTC timestamp when log was generated
- `service`: Service name (always "isafe-guard-backend")
- `level`: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `logger`: Logger name (often includes component/stream ID)
- `message`: Human-readable log message
- `module`: Python module name
- `function`: Function name where log was generated
- `line`: Line number in source code
- `thread`: Thread ID
- `process`: Process ID
- `created_at`: UTC timestamp when log was stored in database

### Optional Fields
- `event_type`: Categorized event type
- `stream_id`: Associated stream identifier
- `camera_id`: Associated camera identifier
- `detection_type`: Type of detection (person, vehicle, etc.)
- `confidence`: Detection confidence score (0.0-1.0)
- `error_code`: Error code for failures
- `retry_count`: Number of retry attempts
- `exception`: Exception information (for ERROR level logs)
  - `type`: Exception class name
  - `message`: Exception message
  - `traceback`: Full exception traceback

## Error Handling

All endpoints return consistent error responses:

```json
{
  "status": "error",
  "message": "Error description",
  "errors": {
    "field_name": ["validation error message"]
  }
}
```

Common HTTP status codes:
- `200`: Success
- `400`: Bad Request (validation errors)
- `500`: Internal Server Error

## Usage Examples

### Get Error Logs from Specific Stream
```bash
curl "http://localhost:5000/api/logs/?level=ERROR&stream_id=cam_001&limit=20"
```

### Get Logs from Last Hour
```bash
START_TIME=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)
END_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
curl "http://localhost:5000/api/logs/?start_time=${START_TIME}&end_time=${END_TIME}"
```

### Search for Connection Errors
```bash
curl -X POST http://localhost:5000/api/logs/search \
  -H "Content-Type: application/json" \
  -d '{
    "level": "ERROR",
    "message": "connection",
    "event_type": "connection_error",
    "limit": 50
  }'
```

### Get Daily Statistics
```bash
curl "http://localhost:5000/api/logs/statistics?start_time=2025-07-14T00:00:00Z&end_time=2025-07-14T23:59:59Z"
```

## Performance Considerations

- Database indexes are automatically created for efficient querying
- Use pagination (limit/offset) for large result sets
- Consider time range filters for better performance
- Log cleanup should be performed regularly to manage storage

## Integration with Monitoring Tools

The structured log format is designed for integration with:

### ELK Stack
```bash
# Example Logstash configuration
input {
  http {
    port => 8080
  }
}
filter {
  json {
    source => "message"
  }
  date {
    match => [ "timestamp", "ISO8601" ]
  }
}
output {
  elasticsearch {
    hosts => ["localhost:9200"]
    index => "isafe-guard-logs-%{+YYYY.MM.dd}"
  }
}
```

### Grafana Loki
```yaml
# Example Promtail configuration
clients:
  - url: http://loki:3100/loki/api/v1/push
scrape_configs:
  - job_name: isafe-guard-logs
    static_configs:
      - targets:
          - localhost:5000
        labels:
          service: isafe-guard-backend
```

### Prometheus Metrics
The API can be extended to expose metrics for Prometheus monitoring:
- Log count by level
- Error rate trends
- Stream activity metrics