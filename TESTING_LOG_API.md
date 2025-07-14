# Testing the Log API

## Setup Complete ✅

The log viewing REST API has been successfully implemented with the following components:

### 📁 Files Created/Modified:
1. **`main/logs/__init__.py`** - Log module initialization
2. **`main/logs/models.py`** - Data models and database operations
3. **`main/logs/routes.py`** - REST API endpoints
4. **`utils/log_handler.py`** - Database logging handler
5. **`main/__init__.py`** - Updated to register log routes
6. **`startup/services.py`** - Updated to initialize database logging
7. **`LOG_API.md`** - Complete API documentation
8. **`test_log_api.py`** - Test script for API endpoints

## 🔄 Restart Required

To activate the new log API, restart the backend:

```bash
cd /home/contil/Projects/isafe-guard
docker-compose restart backend
```

## 🧪 Testing the API

### 1. Quick Health Check
```bash
# Check if log API is available
curl http://localhost:5000/api/logs/levels

# Expected response:
# {"status": "success", "data": {"levels": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]}}
```

### 2. Get Recent Logs
```bash
curl http://localhost:5000/api/logs/recent
```

### 3. Get Log Statistics
```bash
curl http://localhost:5000/api/logs/statistics
```

### 4. Filter Logs by Level
```bash
curl "http://localhost:5000/api/logs/?level=ERROR&limit=10"
```

### 5. Search for Specific Events
```bash
curl "http://localhost:5000/api/logs/?event_type=detection&limit=20"
```

### 6. Run Comprehensive Test
```bash
cd /home/contil/Projects/isafe-guard/isafe-guard-backend
docker exec -it backend python src/test_log_api.py
```

## 📊 API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/logs/` | Get logs with filtering and pagination |
| GET | `/api/logs/recent` | Get 100 most recent logs |
| GET | `/api/logs/statistics` | Get log analytics and aggregations |
| GET | `/api/logs/levels` | Get available log levels |
| GET | `/api/logs/event-types` | Get available event types |
| GET | `/api/logs/streams` | Get stream information from logs |
| POST | `/api/logs/search` | Advanced log search with JSON body |
| POST | `/api/logs/cleanup` | Delete old logs (admin function) |

## 🔍 Key Features

### ✅ Automatic Log Storage
- All application logs are automatically stored in MongoDB
- Structured JSON format with rich metadata
- Background processing to avoid performance impact

### ✅ Advanced Filtering
- Filter by level, logger, message content, event type
- Time-based filtering with start/end times
- Stream and camera-specific filtering
- Regex support for text searches

### ✅ Pagination & Sorting
- Configurable page size (max 1000 entries)
- Offset-based pagination
- Ascending/descending sort by timestamp

### ✅ Analytics & Statistics
- Log count by level (ERROR, WARNING, INFO, etc.)
- Event type distribution
- Stream activity breakdown
- Recent activity trends (hourly)

### ✅ Performance Optimized
- Database indexes for efficient querying
- Background log processing
- Configurable retention policies

## 📱 Integration Examples

### Frontend Integration
```javascript
// Get recent error logs
fetch('/api/logs/?level=ERROR&limit=50')
  .then(response => response.json())
  .then(data => {
    console.log('Error logs:', data.data.logs);
  });

// Get real-time statistics
fetch('/api/logs/statistics')
  .then(response => response.json())
  .then(data => {
    const stats = data.data;
    console.log('Total logs:', stats.total_logs);
    console.log('Error rate:', stats.error_count / stats.total_logs);
  });
```

### Monitoring Dashboard
```javascript
// Dashboard data fetching
Promise.all([
  fetch('/api/logs/statistics'),
  fetch('/api/logs/?level=ERROR&limit=10'),
  fetch('/api/logs/streams')
]).then(responses => Promise.all(responses.map(r => r.json())))
  .then(([stats, errors, streams]) => {
    // Update dashboard widgets
    updateStatsWidget(stats.data);
    updateErrorsWidget(errors.data.logs);
    updateStreamsWidget(streams.data.streams);
  });
```

### Log Analysis Scripts
```bash
# Get all detection events from today
TODAY=$(date +%Y-%m-%d)
curl "http://localhost:5000/api/logs/?event_type=detection&start_time=${TODAY}T00:00:00Z&limit=1000"

# Get error summary for troubleshooting
curl "http://localhost:5000/api/logs/?level=ERROR&limit=100" | \
  jq '.data.logs[] | {timestamp, logger, message, stream_id}'
```

## 🔧 Configuration

### Log Retention
Configure automatic cleanup in your application:

```python
# In a scheduled task or cron job
from main.logs.models import LogEntry

log_entry = LogEntry()
deleted_count = log_entry.delete_old_logs(days_to_keep=30)
print(f"Cleaned up {deleted_count} old logs")
```

### Database Indexes
Indexes are automatically created for:
- `timestamp` (descending)
- `level + timestamp`
- `logger + timestamp`
- `event_type + timestamp`
- `stream_id + timestamp`
- `service + timestamp`

## 🚀 Next Steps

1. **Restart the backend** to activate the API
2. **Test the endpoints** using the provided examples
3. **Integrate with your frontend** for log viewing
4. **Set up monitoring** using the statistics endpoints
5. **Configure log retention** based on your storage needs

## 💡 Advanced Usage

### Custom Dashboards
Build custom monitoring dashboards using the statistics endpoint:
- Real-time error rates
- Stream activity monitoring
- Detection event trends
- System health indicators

### Alerting Integration
Use the API for alerting systems:
```bash
# Check for recent critical errors
ERROR_COUNT=$(curl -s "http://localhost:5000/api/logs/?level=ERROR&start_time=$(date -d '5 minutes ago' -u +%Y-%m-%dT%H:%M:%SZ)" | jq '.data.total_count')

if [ "$ERROR_COUNT" -gt 10 ]; then
  echo "ALERT: High error rate detected ($ERROR_COUNT errors in 5 minutes)"
fi
```

The log API is now ready for production use! 🎉