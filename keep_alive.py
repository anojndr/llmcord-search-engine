"""
Keep Alive Module

This module runs a lightweight Flask server in a separate thread to keep the 
application alive (e.g. when hosting on platforms that require a constant HTTP
endpoint). It defines health-check endpoints.
"""

from flask import Flask, jsonify
from threading import Thread
import logging

# Reduce logging noise from the underlying Werkzeug web server
werkzeug_log = logging.getLogger('werkzeug')
werkzeug_log.setLevel(logging.ERROR)

# Initialize Flask application.
app = Flask(__name__)

@app.route('/')
def index():
    """
    Root endpoint that returns a simple alive response.
    """
    return "i am alive"

@app.route('/healthz')
def healthz():
    """
    Health-check endpoint that returns a JSON object indicating health status.
    """
    return jsonify({"status": "healthy"}), 200

def run():
    """
    Run the Flask app on host 0.0.0.0 and port 8080.
    """
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    """
    Launch the Flask server in a separate thread so it won't block the main application.
    """
    t = Thread(target=run)
    t.start()