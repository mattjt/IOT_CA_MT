from flask import Flask, Response
from picamera2 import Picamera2
import cv2, time, threading

app = Flask(__name__)

picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (640, 360), "format": "RGB888"}))
picam2.start()

latest = None
lock = threading.Lock()

def capture_loop():
    global latest
    while True:
        frame = picam2.capture_array()
        ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ok:
            with lock:
                latest = jpg.tobytes()
        time.sleep(0.05)  # ~20fps cap

threading.Thread(target=capture_loop, daemon=True).start()

def gen():
    while True:
        with lock:
            frame = latest
        if frame is None:
            time.sleep(0.05)
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")

@app.get("/")
def index():
    return '<h2>Pi Live Stream</h2><img src="/video_feed">'

@app.get("/video_feed")
def video_feed():
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
