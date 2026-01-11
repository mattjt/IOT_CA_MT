import os
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from werkzeug.utils import secure_filename

from pubnub.pnconfiguration import PNConfiguration
from pubnub.pubnub import PubNub

load_dotenv()

UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN")
if not UPLOAD_TOKEN:
    raise RuntimeError("Missing UPLOAD_TOKEN")

app = Flask(__name__)

UPLOAD_DIR = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


ALLOWED_EXTS = {"jpg", "jpeg"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

PUB_KEY = os.environ.get("PUBNUB_PUB_KEY")
SUB_KEY = os.environ.get("PUBNUB_SUB_KEY")
SECRET_KEY = os.environ.get("SECRET_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

if not PUB_KEY or not SUB_KEY:
    raise RuntimeError("Missing PubNub keys")

if not SECRET_KEY:
    raise RuntimeError("Missing SECRET_KEY")

if not DATABASE_URL:
    raise RuntimeError("Missing DATABASE_URL")

pnconfig = PNConfiguration()
pnconfig.publish_key = PUB_KEY
pnconfig.subscribe_key = SUB_KEY
pnconfig.uuid = "aws-server"
pnconfig.ssl = True
pubnub = PubNub(pnconfig)

app.config["SECRET_KEY"] = SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Secure session cookies
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

class MotionEvent(db.Model):
    __tablename__ = "motion_events"

    id = db.Column(db.Integer, primary_key=True)
    device = db.Column(db.String(80), nullable=False)
    image_filename = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())


with app.app_context():
    db.create_all()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
@login_required
def dashboard():
    events = MotionEvent.query.order_by(MotionEvent.id.desc()).limit(20).all()
    latest = events[0].image_filename if events else None

    return render_template(
        "dashboard.html",
        pub_key=PUB_KEY,
        sub_key=SUB_KEY,
        username=session.get("username"),
        events=events,
        latest_image=latest,
    )

@app.post("/api/device/toggle")
@login_required
def toggle_device():
    enabled = request.json.get("enabled", None)
    if enabled is None:
        return {"error": "enabled_required"}, 400

    msg = {"type": "set_enabled", "enabled": bool(enabled), "ts": datetime.utcnow().isoformat() + "Z"}
    pubnub.publish().channel("device-control").message(msg).sync()
    return {"ok": True, "sent": msg}, 200


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not username or not password:
            flash("Username and password required")
            return redirect(url_for("register"))

        if password != confirm:
            flash("Passwords do not match")
            return redirect(url_for("register"))

        if User.query.filter_by(username=username).first():
            flash("Username already exists")
            return redirect(url_for("register"))

        user = User(
            username=username,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()

        flash("Account created, please log in")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid username or password")
            return redirect(url_for("login"))

        session["user_id"] = user.id
        session["username"] = user.username
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def allowed_file(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTS

@app.post("/api/upload")
def api_upload():
    token = request.headers.get("X-Upload-Token", "")
    if token != UPLOAD_TOKEN:
        return {"error": "unauthorized"}, 401

    if "image" not in request.files:
        return {"error": "missing_file"}, 400

    image = request.files["image"]
    device = request.form.get("device", "pi").strip() or "pi"

    if image.filename == "":
        return {"error": "empty_filename"}, 400

    if not allowed_file(image.filename):
        return {"error": "invalid_file_type"}, 400

    safe_name = secure_filename(image.filename)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    final_name = f"{device}_{ts}.jpg"
    save_path = os.path.join(UPLOAD_DIR, final_name)

    image.save(save_path)

    ev = MotionEvent(device=device, image_filename=final_name)
    db.session.add(ev)
    db.session.commit()

    
    msg = {
        "type": "snapshot",
        "device": device,
        "filename": final_name,
        "ts": datetime.utcnow().isoformat() + "Z"
    }
    try:
        pubnub.publish().channel("motion-events").message(msg).sync()
    except Exception as e:
        
        print("PubNub publish failed:", e)

    return {"ok": True, "filename": final_name}, 200

