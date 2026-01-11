import os
import time
from datetime import datetime, timezone
from threading import Event, Lock, Thread

import requests
from dotenv import load_dotenv
from gpiozero import MotionSensor, LED
from picamera2 import Picamera2

from pubnub.pnconfiguration import PNConfiguration
from pubnub.pubnub import PubNub
from pubnub.callbacks import SubscribeCallback

load_dotenv()

PUB_KEY = os.environ.get("PUBNUB_PUB_KEY")
SUB_KEY = os.environ.get("PUBNUB_SUB_KEY")
UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN")

SERVER_BASE = os.environ.get("SERVER_BASE", "https://13-60-236-104.nip.io")
MOTION_CHANNEL = os.environ.get("PUBNUB_CHANNEL", "motion-events")
CONTROL_CHANNEL = os.environ.get("CONTROL_CHANNEL", "device-control")
STATUS_CHANNEL = os.environ.get("STATUS_CHANNEL", "device-status")
DEVICE_NAME = os.environ.get("DEVICE_NAME", "pi-zero-2w")

if not PUB_KEY or not SUB_KEY or not UPLOAD_TOKEN:
    raise RuntimeError("Missing PUBNUB_PUB_KEY / PUBNUB_SUB_KEY / UPLOAD_TOKEN in .env")

# GPIO
pir = MotionSensor(17)
led_green = LED(24)
led_orange = LED(23)
led_red = LED(22)

enabled_lock = Lock()
enabled = True

def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()

def set_enabled(state: bool):
    global enabled
    with enabled_lock:
        enabled = state

    if state:
        led_red.off()
        led_green.on()
    else:
        led_green.off()
        led_red.on()

    publish_status(connected=True)

def get_enabled() -> bool:
    with enabled_lock:
        return enabled

# PubNub client
pnconfig = PNConfiguration()
pnconfig.publish_key = PUB_KEY
pnconfig.subscribe_key = SUB_KEY
pnconfig.uuid = DEVICE_NAME
pnconfig.ssl = True
pubnub = PubNub(pnconfig)

def publish_status(connected: bool):
    msg = {
        "type": "device_status",
        "device": DEVICE_NAME,
        "connected": connected,
        "enabled": get_enabled(),
        "ts": now_utc_iso(),
    }
    pubnub.publish().channel(STATUS_CHANNEL).message(msg).sync()

class ControlListener(SubscribeCallback):
    def message(self, pubnub, event):
        msg = event.message or {}
        if (msg.get("type") or "").lower() == "set_enabled":
            new_state = bool(msg.get("enabled"))
            set_enabled(new_state)

pubnub.add_listener(ControlListener())
pubnub.subscribe().channels([CONTROL_CHANNEL]).execute()

# Camera
picam2 = Picamera2()
picam2.configure(picam2.create_still_configuration())
picam2.start()
time.sleep(1)

# LED startup: green flash to show connected
led_green.blink(on_time=0.15, off_time=0.15, n=3, background=False)
set_enabled(True)  # default enabled at boot
publish_status(connected=True)

def upload_snapshot(jpg_path: str) -> str | None:
    url = f"{SERVER_BASE}/api/upload"
    headers = {"X-Upload-Token": UPLOAD_TOKEN}

    with open(jpg_path, "rb") as f:
        files = {"image": ("snapshot.jpg", f, "image/jpeg")}
        data = {"device": DEVICE_NAME}
        r = requests.post(url, headers=headers, files=files, data=data, timeout=25)

    if r.status_code != 200:
        print("Upload failed:", r.status_code, r.text)
        return None

    return r.json().get("filename")

def publish_snapshot(filename: str):
    msg = {
        "type": "snapshot",
        "device": DEVICE_NAME,
        "filename": filename,
        "ts": now_utc_iso(),
    }
    pubnub.publish().channel(MOTION_CHANNEL).message(msg).sync()

print("Running. Waiting for motion...")
while True:
    if not get_enabled():
        time.sleep(0.2)
        continue

    pir.wait_for_motion()
    if not get_enabled():
        continue

    # Orange flash on motion
    led_orange.on()
    time.sleep(0.15)
    led_orange.off()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/snap_{ts}.jpg"
    picam2.capture_file(path)

    uploaded_name = upload_snapshot(path)
    if uploaded_name:
        print("Uploaded:", uploaded_name)
        publish_snapshot(uploaded_name)
    else:
        print("Upload failed; not publishing event.")

    time.sleep(2)  # cooldown
