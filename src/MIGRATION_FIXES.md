# Migration Fixes Applied

## Fixed Syntax Errors

### 1. main/stream/routes.py:242
**Issue**: Malformed f-string with unmatched parentheses
```python
# Before (broken):
app.log_event(logger, "error", f"An error occurred in /get_current_ptz_values for stream_id '{stream_id if 'stream_id' in locals(, event_type="error") else 'unknown'}': {e}")

# After (fixed):
log_event(logger, "error", f"An error occurred in /get_current_ptz_values for stream_id '{stream_id if 'stream_id' in locals() else 'unknown'}': {e}", event_type="error")
```

### 2. main/stream/routes.py:243
**Issue**: Incorrect function call with misplaced parentheses
```python
# Before (broken):
app.log_event(logger, "error", traceback.format_exc(, event_type="error"))

# After (fixed):
log_event(logger, "error", traceback.format_exc(), event_type="error")
```

### 3. Other app.log_event calls
**Issue**: Incorrect function name (should be log_event, not app.log_event)
```python
# Before (broken):
app.log_event(logger, "warning", f"Attempted to get PTZ for non-existent or inactive stream_id: {stream_id}", event_type="warning")

# After (fixed):
log_event(logger, "warning", f"Attempted to get PTZ for non-existent or inactive stream_id: {stream_id}", event_type="warning")
```

## Fixed Import/Reference Errors

### 4. database/__init__.py:5
**Issue**: Missing logger definition and incorrect logging.basicConfig call
```python
# Before (broken):
from utils.logging_config import get_logger, log_event
logging.basicConfig(level=logging.INFO)

# After (fixed):
from utils.logging_config import get_logger, log_event
logger = get_logger(__name__)
```

### 5. startup/services.py:10-15
**Issue**: Obsolete logging configuration calls
```python
# Before (broken):
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("ultralytics").setLevel(logging.WARNING)

# After (fixed):
# Logging configuration moved to utils/logging_config.py
# These specific logger level settings are now handled in setup_logging()
```

### 6. streaming/health/monitor.py:47
**Issue**: Direct logging.warning call and missing logger definition
```python
# Before (broken):
logging.warning(f"Reconnection attempt {self.reconnect_attempt} failed. Retrying in {wait_time}s")

# After (fixed):
logger = get_logger(__name__)  # Added at top of file
log_event(logger, "warning", f"Reconnection attempt {self.reconnect_attempt} failed. Retrying in {wait_time}s", event_type="reconnection_failed")
```

### 7. utils/notifications.py:30
**Issue**: Direct logging.warning call, duplicate imports, missing logger definition
```python
# Before (broken):
from utils.logging_config import get_logger, log_event
from utils.logging_config import get_logger, log_event  # Duplicate
logging.warning(f"Failed to send notification. Status code: {response.status_code}")

# After (fixed):
from utils.logging_config import get_logger, log_event
logger = get_logger(__name__)  # Added
log_event(logger, "warning", f"Failed to send notification. Status code: {response.status_code}", event_type="notification_failed")
```

## Root Cause
The migration script had several issues:
1. Complex f-string patterns with nested parentheses
2. Incorrect transformation of `app.log_event` calls
3. Removal of `import logging` but leaving `logging.` references
4. Missing logger variable definitions after import changes

## Resolution
All syntax and import errors have been manually fixed:
- Fixed malformed f-strings and function calls
- Corrected import statements and added missing logger definitions
- Replaced direct logging calls with structured log_event calls
- Removed obsolete logging configuration code

## Additional Logger Definition Fixes

### 8. Multiple files missing logger definitions
**Issue**: Files had log_event calls but no logger variable defined
**Fixed files**:
- `detection/__init__.py`
- `detection/detector.py`
- `main/event/model.py`
- `main/stream/routes.py`
- `main/stream/model.py`
- `ptz/autotrack.py`
- `ptz/base.py`
- `ptz/controller.py`
- `ptz/tracker.py`
- `streaming/pipelines/manager.py`
- `streaming/processing/event_processor.py`
- `utils/__init__.py`
- `utils/camera_controller.py`

**Solution**: Added `logger = get_logger(__name__)` to all files with log_event calls

## Verification
- All Python files compile without syntax errors
- JSON logging implementation is working correctly
- All logging calls use structured format
- All files with log_event calls have proper logger definitions
- Migration has been completed successfully