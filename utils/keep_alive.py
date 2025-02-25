"""
Keep Alive Module

This module runs a lightweight Flask server in a separate thread to keep the 
application alive (e.g. when hosting on platforms that require a constant HTTP
endpoint). It defines health-check endpoints.
"""

from flask import Flask, jsonify
from threading import Thread
import logging
from typing import Tuple, Dict, Any

werkzeug_log: logging.Logger = logging.getLogger('werkzeug')
werkzeug_log.setLevel(logging.ERROR)

app: Flask = Flask(__name__)

@app.route('/')
def index() -> str:
    """
    Root endpoint that returns a simple alive response.
    """
    return "i am alive"

@app.route('/healthz')
def healthz() -> Tuple[Dict[str, Any], int]:
    """
    Health-check endpoint that returns a JSON object indicating health status.
    """
    return jsonify({"status": "healthy"}), 200

def run() -> None:
    """
    Run the Flask app on host 0.0.0.0 and port 8080.
    """
    app.run(host='0.0.0.0', port=8080)

def keep_alive() -> None:
    """
    Launch the Flask server in a separate thread so it won't block the main application.
    """
    t: Thread = Thread(target=run)
    t.start()