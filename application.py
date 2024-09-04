import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, Response, jsonify, redirect, url_for
from flask_bootstrap import Bootstrap
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
#import datetime
from object_detection import VideoStreaming
from camera_settings import check_settings, reset_settings
from datetime import datetime
from flask_cors import CORS

# Initialize the Flask application

application = Flask(__name__)
CORS(application)
application.secret_key = 'your_secret_key'  # Needed for session management
Bootstrap(application)
from flask_migrate import Migrate

# Initialize SocketIO with eventlet for asynchronous operation
socketio = SocketIO(application, async_mode='eventlet')

# Configure MySQL database
application.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:@localhost/isafeguard'
application.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(application)
migrate = Migrate(application, db)
# Initialize LoginManager
login_manager = LoginManager()
login_manager.init_app(application)
login_manager.login_view = 'login'  # Redirect to login page if not authenticated

# User model for authentication
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        return check_password_hash(self.password, password)


# Database model for event videos
class EventVideo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=True)
    video_path = db.Column(db.String(256), nullable=False)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera_stream.id'), nullable=False)



# Database model for camera streams
class CameraStream(db.Model):
    __tablename__ = 'camera_stream'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    rtsp_link = db.Column(db.String(256), nullable=False)
    description = db.Column(db.String(256))


class DetectorSchedule(db.Model):
    __tablename__ = 'detector_schedule'
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    detector_type = db.Column(db.String(64), nullable=False)
    camera_id = db.Column(db.Integer, db.ForeignKey('camera_stream.id'), nullable=False)

    camera = db.relationship('CameraStream', backref=db.backref('schedules', lazy=True))


# Create database tables
with application.app_context():
    db.create_all()

# Check initial camera settings
check_settings()

# Initialize Video Streaming
VIDEO = VideoStreaming(application, db, EventVideo)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@application.route("/")
def home():
    """Redirect to the dashboard page."""
    return redirect(url_for('dashboard'))


@application.route("/dashboard")
@login_required
def dashboard():
    """Render the dashboard page with all active camera streams according to schedules."""
    TITLE = "iSafe Guard"

    now = datetime.now()
    # Fetch all streams with their schedules
    streams = CameraStream.query.options(db.joinedload(CameraStream.schedules)).all()
    active_schedules = [
        schedule for stream in streams for schedule in stream.schedules
        if schedule.start_date <= now.date() <= schedule.end_date and
           schedule.start_time <= now.time() <= schedule.end_time
    ]

    print(f"Loaded {len(active_schedules)} schedules")  # Debugging line

    return render_template("dashboard.html", TITLE=TITLE, active_schedules=active_schedules)

@application.route("/feed")
def feed():
    camera_id = request.args.get("camera_id")
    model_name = request.args.get("model", "PPE")
    if camera_id == "1":
        rtsp_link = "rtsp://admin:1q2w3e4r.@218.54.201.82:554/idis?trackid=2"
    else:
        rtsp_link = "rtsp://admin:admin1234!@218.54.201.82:40551/unicast/c1/s0/live"

    return Response(
        VIDEO.show(model_name, rtsp_link),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@application.route("/video_feed/<int:camera_id>")
# @login_required
def video_feed(camera_id):
    """Video streaming route."""
    camera = CameraStream.query.get_or_404(camera_id)

    model_name = request.args.get("model", "PPE")  # Default to "PPE" if no model is specified
    return Response(
        VIDEO.show(model_name, camera.rtsp_link),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@application.route("/add_stream", methods=["GET", "POST"])
@login_required
def add_stream():
    """Add a new camera stream."""
    if request.method == "POST":
        name = request.form.get("name")
        rtsp_link = request.form.get("rtsp_link")
        description = request.form.get("description")

        new_stream = CameraStream(name=name, rtsp_link=rtsp_link, description=description)
        try:
            db.session.add(new_stream)
            db.session.commit()
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.session.remove()
    return render_template("add_stream.html")


@application.route("/schedule", methods=["GET", "POST"])
@login_required
def schedule():
    """Schedule detector for camera streams."""
    if request.method == "POST":
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")
        detector_type = request.form.get("detector_type")
        camera_id = request.form.get("camera_id")

        new_schedule = DetectorSchedule(
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            detector_type=detector_type,
            camera_id=camera_id
        )

        try:
            db.session.add(new_schedule)
            db.session.commit()
            return redirect(url_for('schedule'))
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.session.remove()

    streams = CameraStream.query.all()
    return render_template("schedule.html", streams=streams)


@application.route("/login", methods=["GET", "POST"])
def login():
    """Render the login page."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            return render_template("login.html", error="Invalid username or password")

    return render_template("login.html")


@application.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# * Button requests
@application.route("/request_preview_switch")
@login_required
def request_preview_switch():
    """Toggle the preview setting."""
    VIDEO.preview = not VIDEO.preview
    return "nothing"


@application.route("/request_flipH_switch")
@login_required
def request_flipH_switch():
    """Toggle the horizontal flip setting."""
    VIDEO.flipH = not VIDEO.flipH
    return "nothing"


@application.route("/request_model_switch")
@login_required
def request_model_switch():
    """Toggle the model detection setting."""
    VIDEO.detect = not VIDEO.detect
    return "nothing"


@application.route("/request_exposure_down")
@login_required
def request_exposure_down():
    """Decrease the exposure setting."""
    VIDEO.exposure -= 1
    return "nothing"


@application.route("/request_exposure_up")
@login_required
def request_exposure_up():
    """Increase the exposure setting."""
    VIDEO.exposure += 1
    return "nothing"


@application.route("/request_contrast_down")
@login_required
def request_contrast_down():
    """Decrease the contrast setting."""
    VIDEO.contrast -= 4
    return "nothing"


@application.route("/request_contrast_up")
@login_required
def request_contrast_up():
    """Increase the contrast setting."""
    VIDEO.contrast += 4
    return "nothing"


@application.route("/reset_camera")
@login_required
def reset_camera():
    """Reset the camera settings to defaults."""
    STATUS = reset_settings()
    return "nothing"


def new_video_added(video_path):
    """Handle new video added event."""
    timestamp = datetime.datetime.now()
    new_video = EventVideo(timestamp=timestamp, video_path=video_path)
    try:
        db.session.add(new_video)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
    finally:
        db.session.remove()
    socketio.emit('new_video', {'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'), 'video_path': video_path},
                  broadcast=True)


@application.route("/register", methods=["GET", "POST"])
def register():
    """Render the registration page."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if User.query.filter_by(username=username).first():
            return render_template("register.html", error="Username already exists")

        new_user = User(username=username)
        new_user.set_password(password)

        try:
            db.session.add(new_user)
            db.session.commit()
            return render_template("register.html", success="Registration successful. Please log in.")
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.session.remove()

    return render_template("register.html")


@application.route("/schedules")
@login_required
def schedules():
    """View all schedules."""
    schedules = DetectorSchedule.query.all()
    return render_template("schedules.html", schedules=schedules)

@application.route("/edit_schedule/<int:schedule_id>", methods=["GET", "POST"])
@login_required
def edit_schedule(schedule_id):
    """Edit a specific schedule."""
    schedule = DetectorSchedule.query.get_or_404(schedule_id)
    streams = CameraStream.query.all()

    if request.method == "POST":
        schedule.start_date = request.form.get("start_date")
        schedule.end_date = request.form.get("end_date")
        schedule.start_time = request.form.get("start_time")
        schedule.end_time = request.form.get("end_time")
        schedule.detector_type = request.form.get("detector_type")
        schedule.camera_id = request.form.get("camera_id")

        try:
            db.session.commit()
            return redirect(url_for('schedules'))
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    return render_template("edit_schedule.html", schedule=schedule, streams=streams)


@application.route("/stream/<int:camera_id>")
@login_required
def stream_detail(camera_id):
    """Render the detail view for a specific camera stream."""
    camera = CameraStream.query.get_or_404(6)

    # Fetch unsafe event videos for this camera
    unsafe_videos = EventVideo.query.filter_by(camera_id=camera_id).order_by(EventVideo.timestamp.desc()).all()

    return render_template("stream_detail.html", camera=camera, unsafe_videos=unsafe_videos)

@application.route("/add_schedule", methods=["GET", "POST"])
@login_required
def add_schedule():
    """Add a new schedule for camera streams."""
    if request.method == "POST":
        # Extract form data
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")
        detector_type = request.form.get("detector_type")
        camera_id = request.form.get("camera_id")

        new_schedule = DetectorSchedule(
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            detector_type=detector_type,
            camera_id=camera_id
        )

        try:
            db.session.add(new_schedule)
            db.session.commit()
            return redirect(url_for('view_schedule'))
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.session.remove()

    streams = CameraStream.query.all()
    return render_template("add_schedule.html", streams=streams)


@application.route("/view_schedule")
@login_required
def view_schedule():
    """View all schedules for camera streams."""
    schedules = DetectorSchedule.query.all()
    return render_template("view_schedule.html", schedules=schedules)


@application.route("/view_streams")
@login_required
def view_streams():
    """View all camera streams."""
    streams = CameraStream.query.all()
    return render_template("view_streams.html", streams=streams)


@application.route("/edit_stream/<int:stream_id>", methods=["GET", "POST"])
@login_required
def edit_stream(stream_id):
    """Edit an existing camera stream."""
    stream = CameraStream.query.get_or_404(stream_id)

    if request.method == "POST":
        stream.name = request.form.get("name")
        stream.rtsp_link = request.form.get("rtsp_link")
        stream.description = request.form.get("description")

        try:
            db.session.commit()
            return redirect(url_for('view_streams'))
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            db.session.remove()

    return render_template("edit_stream.html", stream=stream)

if __name__ == "__main__":
    # Run the application
    socketio.run(application, debug=True)
