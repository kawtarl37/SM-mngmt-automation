import os
import sqlite3
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from pathlib import Path
import sys

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from execution.config import DB_PATH, TMP_PINS_DIR

app = Flask(__name__)
CORS(app)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/api/pins', methods=['GET'])
def get_pending_pins():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.pin_id, p.title, p.description, p.image_path, p.status, p.seo_keywords,
               c.content_type
        FROM generated_pins p
        JOIN content_ideas c ON p.idea_id = c.idea_id
        WHERE p.status = 'pending'
    """)
    pins = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(pins)

@app.route('/api/pins/<int:pin_id>/approve', methods=['POST'])
def approve_pin(pin_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE generated_pins SET status = 'approved' WHERE pin_id = ?", (pin_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/pins/<int:pin_id>/reject', methods=['POST'])
def reject_pin(pin_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE generated_pins SET status = 'rejected' WHERE pin_id = ?", (pin_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/images/<path:filename>')
def serve_image(filename):
    # Images are in .tmp/pins/pin_X.jpg
    # Filename would be 'pin_X.jpg'
    return send_from_directory(TMP_PINS_DIR, filename)

@app.route('/')
def index():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>EGF Pin Approval Dashboard</title>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f4f7f6; color: #333; margin: 0; padding: 20px; }
            h1 { text-align: center; color: #2c3e50; }
            .container { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 20px; max-width: 1200px; margin: 0 auto; }
            .pin-card { background: white; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); overflow: hidden; display: flex; flex-direction: column; }
            .pin-image { width: 100%; height: 500px; object-fit: cover; background: #ddd; }
            .pin-content { padding: 15px; flex-grow: 1; }
            .pin-title { font-size: 1.2rem; font-weight: bold; margin-bottom: 10px; color: #2c3e50; }
            .pin-desc { font-size: 0.9rem; color: #666; margin-bottom: 15px; white-space: pre-wrap; }
            .pin-meta { font-size: 0.8rem; color: #999; margin-bottom: 10px; }
            .actions { display: flex; padding: 15px; border-top: 1px solid #eee; gap: 10px; }
            button { flex: 1; padding: 10px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; transition: opacity 0.2s; }
            .btn-approve { background: #27ae60; color: white; }
            .btn-reject { background: #e74c3c; color: white; }
            button:hover { opacity: 0.8; }
            .no-pins { text-align: center; grid-column: 1 / -1; padding: 50px; font-size: 1.2rem; color: #999; }
        </style>
    </head>
    <body>
        <h1>Easy Gluten Free - Pin Approval Dashboard</h1>
        <div id="pins-container" class="container">
            <div class="no-pins">Loading pending pins...</div>
        </div>

        <script>
            async function fetchPins() {
                const response = await fetch('/api/pins');
                const pins = await response.json();
                const container = document.getElementById('pins-container');
                
                if (pins.length === 0) {
                    container.innerHTML = '<div class="no-pins">🎉 All caught up! No pending pins to review.</div>';
                    return;
                }

                container.innerHTML = pins.map(pin => {
                    const filename = pin.image_path ? pin.image_path.split(/[\\\\/]/).pop() : '';
                    return `
                        <div class="pin-card" id="pin-${pin.pin_id}">
                            <img src="/images/${filename}" class="pin-image" alt="Pin Image">
                            <div class="pin-content">
                                <div class="pin-meta">${pin.content_type.toUpperCase()}</div>
                                <div class="pin-title">${pin.title}</div>
                                <div class="pin-desc">${pin.description}</div>
                                <div class="pin-meta"><strong>Keywords:</strong> ${pin.seo_keywords || 'N/A'}</div>
                            </div>
                            <div class="actions">
                                <button class="btn-approve" onclick="approvePin(${pin.pin_id})">Approve</button>
                                <button class="btn-reject" onclick="rejectPin(${pin.pin_id})">Reject</button>
                            </div>
                        </div>
                    `;
                }).join('');
            }

            async function approvePin(id) {
                if (!confirm('Approve this pin for scheduling?')) return;
                const response = await fetch(`/api/pins/${id}/approve`, { method: 'POST' });
                if (response.ok) {
                    document.getElementById(`pin-${id}`).remove();
                    checkEmpty();
                }
            }

            async function rejectPin(id) {
                if (!confirm('Reject this pin? it will not be posted.')) return;
                const response = await fetch(`/api/pins/${id}/reject`, { method: 'POST' });
                if (response.ok) {
                    document.getElementById(`pin-${id}`).remove();
                    checkEmpty();
                }
            }

            function checkEmpty() {
                const container = document.getElementById('pins-container');
                if (container.children.length === 0) {
                    container.innerHTML = '<div class="no-pins">🎉 All caught up! No pending pins to review.</div>';
                }
            }

            fetchPins();
        </script>
    </body>
    </html>
    """

if __name__ == '__main__':
    print("Starting EGF Dashboard on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
