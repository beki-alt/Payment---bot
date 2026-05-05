"""
keep_alive.py - Flask Keep-Alive Server
Runs a lightweight Flask web server on a background thread so that
UptimeRobot / Render.com free-tier instances stay awake.
"""

import os
import threading
import logging
from flask import Flask, jsonify

logger = logging.getLogger(__name__)

app = Flask(__name__)

_start_time = None


@app.route("/")
def home():
    return jsonify({
        "status": "alive",
        "service": "Telegram Subscription Bot",
        "message": "Bot is running ✅"
    })


@app.route("/health")
def health():
    import time
    uptime = int(time.time() - _start_time) if _start_time else 0
    return jsonify({
        "status": "ok",
        "uptime_seconds": uptime,
    })


@app.route("/ping")
def ping():
    return "pong", 200


def run_flask():
    """Run Flask in a daemon thread. Called once at bot startup."""
    import time
    global _start_time
    _start_time = time.time()

    port = int(os.getenv("PORT", 8080))
    logger.info(f"Flask keep-alive server starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def keep_alive():
    """Start the Flask server in a background daemon thread."""
    thread = threading.Thread(target=run_flask, daemon=True, name="KeepAliveFlask")
    thread.start()
    logger.info("✅ Keep-alive Flask server started in background thread.")
