# # Gunicorn configuration file
# import multiprocessing
# import os
# import signal
# import logging

# # Server socket
# bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
# backlog = 2048

# # Worker processes
# workers = 1  # Keep to 1 for your background tasks
# worker_class = "sync"
# worker_connections = 1000
# timeout = 30
# keepalive = 2

# # Restart workers after this many requests, to prevent memory leaks
# max_requests = 1000
# max_requests_jitter = 50

# # Logging
# accesslog = "-"
# errorlog = "-"
# loglevel = "info"
# access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# # Process naming
# proc_name = "your-app-name"

# # Server mechanics
# preload_app = True
# daemon = False
# pidfile = "/tmp/gunicorn.pid"
# user = None
# group = None
# tmp_upload_dir = None

# # SSL (uncomment if needed)
# # keyfile = "/path/to/keyfile"
# # certfile = "/path/to/certfile"

# def on_starting(server):
#     """Called just before the master process is initialized."""
#     server.log.info("Starting Gunicorn server")

# def on_reload(server):
#     """Called to recycle workers during a reload via SIGHUP."""
#     server.log.info("Reloading Gunicorn server")

# def worker_int(worker):
#     """Called just after a worker exited on SIGINT or SIGQUIT."""
#     worker.log.info("Worker received INT or QUIT signal")

# def pre_fork(server, worker):
#     """Called just before a worker is forked."""
#     server.log.info("Worker spawned (pid: %s)", worker.pid)

# def post_fork(server, worker):
#     """Called just after a worker has been forked."""
#     server.log.info("Worker spawned (pid: %s)", worker.pid)

# def worker_abort(worker):
#     """Called when a worker received the SIGABRT signal."""
#     worker.log.info("Worker received SIGABRT signal")