from flask import Flask, render_template
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()

# Read PubNub keys from environment
PUB_KEY = os.environ.get("PUBNUB_PUB_KEY")
SUB_KEY = os.environ.get("PUBNUB_SUB_KEY")

if not PUB_KEY or not SUB_KEY:
    raise RuntimeError("Missing PubNub keys in .env")

app = Flask(__name__)

@app.route("/")
def index():
    # Stream URL can be updated later (LAN IP or tunnel URL)
    stream_url = "REPLACE_ME"

    return render_template(
        "dashboard.html",
        pub_key=PUB_KEY,
        sub_key=SUB_KEY,
        stream_url=stream_url
    )

if __name__ == "__main__":
    # Gunicorn will be used in production; this is for local testing
    app.run(host="0.0.0.0", port=8000)
