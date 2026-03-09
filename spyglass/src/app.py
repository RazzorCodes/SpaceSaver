import os
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# The URL of the transcoder service (defaulting to localhost for easy local dev outside container)
TRANSCODER_URL = os.environ.get("TRANSCODER_URL", "http://localhost:8000").rstrip("/")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/list", methods=["GET"])
def get_list():
    try:
        response = requests.get(f"{TRANSCODER_URL}/list", timeout=10)
        return jsonify(response.json()), response.status_code
    except requests.Timeout as e:
        return jsonify({"error": str(e)}), 504
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502

@app.route("/api/version", methods=["GET"])
def get_version():
    try:
        response = requests.get(f"{TRANSCODER_URL}/version", timeout=5)
        return jsonify(response.json()), response.status_code
    except requests.Timeout as e:
        return jsonify({"error": str(e)}), 504
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502

@app.route("/api/status", methods=["GET"])
def get_status():
    try:
        response = requests.get(f"{TRANSCODER_URL}/status", timeout=5)
        return jsonify(response.json()), response.status_code
    except requests.Timeout as e:
        return jsonify({"error": str(e)}), 504
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502

@app.route("/api/process/<hash>", methods=["PUT", "POST"])
def process_hash(hash):
    try:
        # Transcoder API expects a PUT /process/{hash}
        response = requests.put(f"{TRANSCODER_URL}/process/{hash}", timeout=5)
        return jsonify(response.json()), response.status_code
    except requests.Timeout as e:
        return jsonify({"error": str(e)}), 504
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502

@app.route("/api/cancel/<uuid>", methods=["DELETE"])
def cancel_task(uuid):
    try:
        response = requests.delete(f"{TRANSCODER_URL}/cancel/{uuid}", timeout=5)
        if response.content:
            return jsonify(response.json()), response.status_code
        return jsonify({}), response.status_code
    except requests.Timeout as e:
        return jsonify({"error": str(e)}), 504
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502

@app.route("/api/scan", methods=["PUT", "POST"])
def scan_library():
    try:
        response = requests.put(f"{TRANSCODER_URL}/scan", timeout=10)
        return jsonify(response.json()), response.status_code
    except requests.Timeout as e:
        return jsonify({"error": str(e)}), 504
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502

@app.route("/api/quality", methods=["GET"])
def get_quality():
    try:
        response = requests.get(f"{TRANSCODER_URL}/quality", timeout=5)
        return jsonify(response.json()), response.status_code
    except requests.Timeout as e:
        return jsonify({"error": str(e)}), 504
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502

@app.route("/api/quality", methods=["POST"])
def set_quality():
    try:
        response = requests.post(f"{TRANSCODER_URL}/quality", json=request.json, timeout=5)
        return jsonify(response.json()), response.status_code
    except requests.Timeout as e:
        return jsonify({"error": str(e)}), 504
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
