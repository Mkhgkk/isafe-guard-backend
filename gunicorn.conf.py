# Gunicorn configuration file for production deployment
# Optimized for ML model applications to avoid model duplication

import multiprocessing
import os

# Server socket
bind = "0.0.0.0:5000"
backlog = 2048

# Single worker to avoid model duplication - models are loaded once
workers = 1  # Single worker to share model instances across all requests
worker_class = "eventlet"  # Async worker for high concurrency and SocketIO support
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "2000"))  # Higher concurrency for single worker

# Timeouts - increased for ML inference
timeout = int(os.getenv("GUNICORN_TIMEOUT", "300"))  # Longer timeout for model inference
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "60"))

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Logging
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" inference_time=%(D)sµs'

# Process naming
proc_name = "isafe-guard-backend"

# Restart worker after this many requests to prevent memory leaks from ML models
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "2000"))  # Higher for single worker
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "100"))

# Preload app for better memory usage and faster model loading
preload_app = True

# Restart workers gracefully on code change
reload = False

# Working directory
chdir = "/app/src"

# User and group (if running as root)
# user = "nobody"
# group = "nobody"

# Enable stdout/stderr capture
capture_output = True

# Disable redirect access logs to syslog
disable_redirect_access_to_syslog = True

def when_ready(server):
    server.log.info("🚀 Production server ready with single worker for shared ML models")

def worker_int(worker):
    worker.log.info("🔄 Worker received INT or QUIT signal")

def pre_fork(server, worker):
    server.log.info("🔧 Worker spawning (pid: %s)", worker.pid)

def post_fork(server, worker):
    server.log.info("✅ Worker spawned (pid: %s) - ML models will be loaded once", worker.pid)

def post_worker_init(worker):
    worker.log.info("🧠 Worker initialized (pid: %s) - Ready for ML inference", worker.pid)

def worker_abort(worker):
    worker.log.info("⚠️ Worker received SIGABRT signal")

def on_starting(server):
    server.log.info("🎯 Starting Gunicorn with single worker for ML model optimization")

def on_reload(server):
    server.log.info("🔄 Reloading Gunicorn configuration")