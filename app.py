from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO
from routes.socketio_handlers import setup_socketio_handlers
from socketio_instance import socketio
from routes.api_routes import app
import psutil
import GPUtil
from apscheduler.schedulers.background import BackgroundScheduler
from database.db import create_db_instance, close_db_connection



CORS(app)
# cors = CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
socketio.init_app(app, cors_allowed_origins="*", async_mode='threading')
# socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

setup_socketio_handlers(socketio)

app.socketio = socketio


def get_system_utilization():
    """Function to fetch CPU and GPU utilization and emit to frontend."""
    # Get CPU utilization
    cpu_usage = psutil.cpu_percent(interval=0)
    
    # Get GPU utilization (if NVIDIA GPU is present)
    gpus = GPUtil.getGPUs()
    gpu_usage = gpus[0].load * 100 if gpus else 0
    
    # Emit data to the frontend
    socketio.emit('system_status', {'cpu': cpu_usage, 'gpu': gpu_usage}, namespace='/video')


if __name__ == '__main__':
    # Initialize the scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=get_system_utilization, trigger="interval", seconds=2)
    # scheduler.start()

    create_db_instance()
    

    socketio.run(app, host='0.0.0.0', port=5000, debug=True)




