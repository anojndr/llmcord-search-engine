from flask import Flask, jsonify
from threading import Thread

app = Flask(__name__)

@app.route('/')
def index():
    return "i am alive"

@app.route('/healthz')
def healthz():
    return jsonify({"status": "healthy"}), 200

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    """
    Launches the Flask server in a separate thread.
    """
    t = Thread(target=run)
    t.start()