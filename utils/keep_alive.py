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

# Configure logging for Flask/Werkzeug
werkzeug_log: logging.Logger = logging.getLogger('werkzeug')
werkzeug_log.setLevel(logging.ERROR)

# Our own logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

app: Flask = Flask(__name__)

@app.route('/')
def index() -> str:
    """
    Root endpoint that returns a simple alive response.
    """
    logger.debug("Root endpoint accessed")
    return "i am alive"

@app.route('/healthz')
def healthz() -> Tuple[Dict[str, Any], int]:
    """
    Health-check endpoint that returns a JSON object indicating health status.
    """
    logger.debug("Health check endpoint accessed")
    return jsonify({"status": "healthy"}), 200

def run() -> None:
    """
    Run the Flask app on host 0.0.0.0 and port 8080.
    """
    try:
        logger.info("Starting Flask keep-alive server on 0.0.0.0:8080")
        app.run(host='0.0.0.0', port=8080)
    except Exception as e:
        logger.error(f"Error starting Flask server: {e}", exc_info=True)

def keep_alive() -> None:
    """
    Launch the Flask server in a separate thread so it won't block the main application.
    """
    try:
        logger.info("Initializing keep-alive server thread")
        t: Thread = Thread(target=run)
        t.daemon = True  # Set as daemon so it doesn't block program exit
        t.start()
        logger.info("Keep-alive server thread started")
    except Exception as e:
        logger.error(f"Failed to start keep-alive thread: {e}", exc_info=True)