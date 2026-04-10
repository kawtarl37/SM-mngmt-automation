import os
import sys
import sqlite3
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from pathlib import Path

# Fix python path to allow running script directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Imports from the execution package
from execution.config import DB_PATH, TMP_PINS_DIR
from execution.content.publish_scheduler import schedule_approved_pins, run_scheduled_publishes, execute_single_publish
from execution.content.generate_custom_content import generate_custom

app = Flask(__name__)
CORS(app)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ──────────────────────────────────────────────
# API: Pins
# ──────────────────────────────────────────────

@app.route('/api/pins', methods=['GET'])
def get_pending_pins():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Left join to accommodate custom pins where idea_id = 0
    cursor.execute("""
        SELECT p.pin_id, p.title, p.description, p.image_path, p.status, p.seo_keywords,
               c.content_type
        FROM generated_pins p
        LEFT JOIN content_ideas c ON p.idea_id = c.idea_id
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

    # Auto-schedule the pin for publishing
    try:
        schedule_approved_pins()
    except Exception as e:
        return jsonify({"success": True, "warning": f"Pin approved but scheduling failed: {e}"}), 200

    return jsonify({"success": True, "message": "Pin approved and added to publish queue."})

@app.route('/api/pins/<int:pin_id>/reject', methods=['POST'])
def reject_pin(pin_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    data = request.get_json() or {}
    reason = data.get("reason", "")
    cursor.execute(
        "UPDATE generated_pins SET status = 'rejected', rejection_reason = ? WHERE pin_id = ?",
        (reason, pin_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ──────────────────────────────────────────────
# API: Publish Schedule Queue
# ──────────────────────────────────────────────

@app.route('/api/schedule', methods=['GET'])
def get_schedule():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.schedule_id, s.pin_id, s.scheduled_time, s.status,
               s.error_message, s.completed_at,
               p.title as pin_title,
               b.wp_url
        FROM publish_schedule s
        JOIN generated_pins p ON s.pin_id = p.pin_id
        LEFT JOIN blogs b ON s.blog_id = b.blog_id
        ORDER BY s.scheduled_time ASC
        LIMIT 30
    """)
    schedule = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(schedule)

@app.route('/api/publish/run', methods=['POST'])
def run_publish():
    """Manually trigger the scheduled publishes check."""
    try:
        run_scheduled_publishes()
        return jsonify({"success": True, "message": "Publish runner executed successfully."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/publish/now/<int:pin_id>', methods=['POST'])
def publish_now(pin_id):
    """Publish a pin immediately, out of schedule."""
    try:
        success = execute_single_publish(pin_id)
        if success:
            return jsonify({"success": True, "message": "Pin published immediately."})
        else:
            return jsonify({"success": False, "error": "Internal publishing error."}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/generate_custom', methods=['POST'])
def generate_custom_api():
    """Generate on-demand custom content."""
    data = request.get_json() or {}
    topic_type = data.get("topic_type", "Educational")
    try:
        result = generate_custom(topic_type)
        if result:
            return jsonify({"success": True, "pin": result})
        return jsonify({"success": False, "error": "Failed to generate (returned None)."}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ──────────────────────────────────────────────
# Static: Images
# ──────────────────────────────────────────────

@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(TMP_PINS_DIR, filename)

# ──────────────────────────────────────────────
# Frontend
# ──────────────────────────────────────────────

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
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f0f4f3; color: #333; }

            /* Header */
            header { background: #1a1a2e; color: white; padding: 18px 30px; display: flex; align-items: center; justify-content: space-between; }
            header h1 { font-size: 1.3rem; font-weight: 700; letter-spacing: 0.5px; display:flex; align-items:center; gap: 15px;}
            .tab-nav { display: flex; gap: 10px; }
            .tab-btn { background: rgba(255,255,255,0.1); border: none; color: white; padding: 8px 20px;
                       border-radius: 20px; cursor: pointer; font-size: 0.9rem; transition: background 0.2s; }
            .tab-btn.active, .tab-btn:hover { background: #e94560; }

            /* Main layout */
            main { max-width: 1300px; margin: 0 auto; padding: 30px 20px; }
            .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
            .section-title { font-size: 1.1rem; font-weight: 700; color: #1a1a2e; }

            /* Pin Cards */
            .pins-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 22px; }
            .pin-card { background: white; border-radius: 14px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); overflow: hidden; display: flex; flex-direction: column; }
            .pin-image { width: 100%; height: 480px; object-fit: cover; background: #ddd; }
            .pin-content { padding: 16px; flex-grow: 1; }
            .pin-badge { display: inline-block; font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
                         letter-spacing: 1px; background: #f0f4f3; color: #555; padding: 3px 10px;
                         border-radius: 20px; margin-bottom: 10px; }
            .pin-title { font-size: 1.05rem; font-weight: 700; color: #1a1a2e; margin-bottom: 8px; }
            .pin-desc { font-size: 0.88rem; color: #666; margin-bottom: 12px; line-height: 1.5; white-space: pre-wrap; }
            .pin-keywords { font-size: 0.78rem; color: #999; }
            .pin-actions { display: flex; padding: 14px 16px; border-top: 1px solid #f0f0f0; gap: 10px; }
            .btn { flex: 1; padding: 10px; border: none; border-radius: 8px; cursor: pointer; font-weight: 700; font-size: 0.9rem; transition: opacity 0.2s, transform 0.1s; }
            .btn:hover { opacity: 0.85; transform: translateY(-1px); }
            .btn-approve { background: #27ae60; color: white; }
            .btn-reject  { background: #e74c3c; color: white; }
            
            .btn-publish { background: #f39c12; color: white; font-size: 0.8rem; padding: 4px 10px; border-radius: 4px;}
            .btn-gen { background: #e94560; color: white; border: none; border-radius: 6px; cursor: pointer; padding: 10px 15px; font-weight:600; font-size:0.9rem;}
            .btn-trigger { background: #e94560; color: white; flex: none; padding: 10px 20px; font-size: 0.85rem; }
            .btn-trigger:disabled, .btn-gen:disabled { background: #ccc; cursor: not-allowed; }

            /* Schedule Table */
            .schedule-table { width: 100%; border-collapse: collapse; background: white; border-radius: 14px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
            .schedule-table th { background: #1a1a2e; color: white; padding: 12px 16px; text-align: left; font-size: 0.85rem; }
            .schedule-table td { padding: 12px 16px; border-bottom: 1px solid #f0f0f0; font-size: 0.88rem; }
            .schedule-table tr:last-child td { border-bottom: none; }
            .status-badge { padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; }
            .status-pending   { background: #fff3cd; color: #856404; }
            .status-published { background: #d1e7dd; color: #155724; }
            .status-failed    { background: #f8d7da; color: #842029; }
            .error-text { color: #e74c3c; font-size: 0.75rem; display: block; margin-top: 4px; max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: help; }

            /* Empty state */
            .empty { text-align: center; padding: 60px 20px; color: #aaa; font-size: 1.1rem; grid-column: 1/-1; }
            .tab-content { display: none; }
            .tab-content.active { display: block; }

            /* Modal */
            .modal-overlay { position: fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); display:none; justify-content:center; align-items:center; z-index:999;}
            .modal { background:white; padding:25px; border-radius:12px; max-width:400px; width:100%; box-shadow: 0 10px 30px rgba(0,0,0,0.2);}
            .modal h2 { font-size:1.2rem; margin-bottom:15px; color:#1a1a2e;}
            .modal select { width:100%; padding:10px; margin-bottom:20px; border-radius:6px; border:1px solid #ccc; font-size:1rem;}
            .modal .actions { display:flex; gap:10px; justify-content:flex-end;}
            .btn-close { background:#ccc; color:#333; }
            
            /* Loading Spinner */
            .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid rgba(255,255,255,.3); border-radius: 50%; border-top-color: #fff; animation: spin 1s ease-in-out infinite; margin-right: 8px; display: none; }
            @keyframes spin { to { transform: rotate(360deg); } }
            .loading .spinner { display: inline-block; }
            .action-col { display: flex; gap: 8px; flex-wrap: wrap; }
        </style>
    </head>
    <body>
        <header>
            <h1>
                🌿 Easy Gluten Free 
                <button class="btn-gen" onclick="openGenModal()">+ Generate Content</button>
            </h1>
            <nav class="tab-nav">
                <button class="tab-btn active" onclick="showTab('tab-pending')">Pending Review</button>
                <button class="tab-btn" onclick="showTab('tab-queue')">Publish Queue</button>
            </nav>
        </header>

        <main>
            <!-- PENDING PINS -->
            <div id="tab-pending" class="tab-content active">
                <div class="section-header">
                    <p class="section-title">Pins Awaiting Approval</p>
                </div>
                <div id="pins-container" class="pins-grid">
                    <div class="empty">Loading pins...</div>
                </div>
            </div>

            <!-- PUBLISH QUEUE -->
            <div id="tab-queue" class="tab-content">
                <div class="section-header">
                    <p class="section-title">Upcoming Publish Schedule (US Eastern)</p>
                    <button id="btn-run-publish" class="btn btn-trigger" onclick="triggerPublishRunner()">
                        <span class="spinner"></span>
                        Trigger Publish Now
                    </button>
                </div>
                <table class="schedule-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Pin Title</th>
                            <th>Scheduled Time (EST)</th>
                            <th>Status / Error</th>
                            <th>Blog Link</th>
                            <th>Quick Actions</th>
                        </tr>
                    </thead>
                    <tbody id="schedule-body">
                        <tr><td colspan="6" style="text-align:center;padding:30px;color:#aaa;">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </main>
        
        <!-- Generate Modal -->
        <div class="modal-overlay" id="gen-modal">
            <div class="modal">
                <h2>Generate Custom Content</h2>
                <p style="font-size:0.9rem; color:#666; margin-bottom:15px;">Generate a complete blog + pin package for a specific topic. It will be added silently to Pending Review.</p>
                <select id="gen-topic">
                    <option value="Educational">Educational (Know Your Ingredients)</option>
                    <option value="Practical Guide">Practical Guide (Tips & Tricks)</option>
                    <option value="Lifestyle">Lifestyle (Living Gluten-Free)</option>
                    <option value="Health & Wellness">Health & Wellness (Healthy Living)</option>
                </select>
                <div class="actions">
                    <button class="btn btn-close" onclick="closeGenModal()">Cancel</button>
                    <button class="btn btn-approve" id="btn-gen-submit" onclick="submitGenerate()">
                        <span class="spinner"></span> Generate
                    </button>
                </div>
            </div>
        </div>

        <script>
            // ── Tab navigation ──
            function showTab(id) {
                document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
                document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
                document.getElementById(id).classList.add('active');
                event.target.classList.add('active');
                if (id === 'tab-queue') fetchSchedule();
                else fetchPins();
            }

            // ── Generate Modal ──
            function openGenModal() { document.getElementById('gen-modal').style.display = 'flex'; }
            function closeGenModal() { document.getElementById('gen-modal').style.display = 'none'; }
            async function submitGenerate() {
                const topic = document.getElementById('gen-topic').value;
                const btn = document.getElementById('btn-gen-submit');
                btn.classList.add('loading'); btn.disabled = true;
                
                try {
                    const res = await fetch('/api/generate_custom', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({topic_type: topic})
                    });
                    const data = await res.json();
                    if(data.success) {
                        alert('Generation complete! Check Pending Review Tab.');
                        closeGenModal();
                        fetchPins();
                    } else {
                        alert('Generation failed: ' + data.error);
                    }
                } catch(e) { alert('Error: ' + e); }
                
                btn.classList.remove('loading'); btn.disabled = false;
            }

            // ── Pins ──
            async function fetchPins() {
                const res = await fetch('/api/pins');
                const pins = await res.json();
                const container = document.getElementById('pins-container');
                if (pins.length === 0) {
                    container.innerHTML = '<div class="empty">🎉 All caught up! No pending pins.</div>';
                    return;
                }
                container.innerHTML = pins.map(pin => {
                    const filename = pin.image_path ? pin.image_path.split(/[\\\\/]/).pop() : '';
                    const cType = pin.content_type || 'Custom Gen';
                    return `
                        <div class="pin-card" id="pin-${pin.pin_id}">
                            <img src="/images/${filename}" class="pin-image" alt="Pin Image" onerror="this.src=''">
                            <div class="pin-content">
                                <span class="pin-badge">${cType}</span>
                                <div class="pin-title">${pin.title}</div>
                                <div class="pin-desc">${pin.description}</div>
                                <div class="pin-keywords"><strong>Keywords:</strong> ${pin.seo_keywords || 'N/A'}</div>
                            </div>
                            <div class="pin-actions">
                                <button class="btn btn-approve" onclick="approvePin(${pin.pin_id})">✓ Approve</button>
                                <button class="btn btn-reject"  onclick="rejectPin(${pin.pin_id})">✗ Reject</button>
                            </div>
                        </div>`;
                }).join('');
            }

            async function approvePin(id) {
                if (!confirm('Approve this pin? It will be added to the publish queue.')) return;
                const res = await fetch(`/api/pins/${id}/approve`, { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    document.getElementById(`pin-${id}`).remove();
                    checkEmpty('pins-container', '<div class="empty">🎉 All caught up! No pending pins.</div>');
                    alert(data.message || 'Pin approved and scheduled!');
                }
            }

            async function rejectPin(id) {
                const reason = prompt('Rejection reason (optional):') || '';
                const res = await fetch(`/api/pins/${id}/reject`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ reason })
                });
                if ((await res.json()).success) {
                    document.getElementById(`pin-${id}`).remove();
                    checkEmpty('pins-container', '<div class="empty">🎉 All caught up! No pending pins.</div>');
                }
            }

            function checkEmpty(containerId, html) {
                const c = document.getElementById(containerId);
                if (c && c.children.length === 0) c.innerHTML = html;
            }

            // ── Schedule ──
            async function fetchSchedule() {
                const res = await fetch('/api/schedule');
                const rows = await res.json();
                const tbody = document.getElementById('schedule-body');
                if (rows.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:30px;color:#aaa;">No scheduled publishes yet.</td></tr>';
                    return;
                }
                tbody.innerHTML = rows.map((r, i) => {
                    const t = new Date(r.scheduled_time);
                    const estTime = t.toLocaleString('en-US', { timeZone: 'America/New_York', dateStyle: 'medium', timeStyle: 'short' });
                    const statusClass = `status-${r.status}`;
                    const link = r.wp_url ? `<a href="${r.wp_url}" target="_blank">View Post</a>` : '—';
                    const error = r.error_message ? `<span class="error-text" title="${r.error_message}">${r.error_message}</span>` : '';
                    
                    let actions = '';
                    if (r.status === 'pending' || r.status === 'failed') {
                        actions = `<button class="btn btn-publish" onclick="postNow(${r.pin_id}, this)"><span class="spinner"></span> Post Now</button>`;
                    }
                    
                    return `<tr>
                        <td>${i + 1}</td>
                        <td>${r.pin_title}</td>
                        <td>${estTime}</td>
                        <td>
                            <span class="status-badge ${statusClass}">${r.status}</span>
                            ${error}
                        </td>
                        <td>${link}</td>
                        <td class="action-col">${actions}</td>
                    </tr>`;
                }).join('');
            }
            
            async function postNow(pin_id, btnEl) {
                if(!confirm('Publish this post immediately?')) return;
                btnEl.classList.add('loading'); btnEl.disabled = true;
                try {
                    const res = await fetch(`/api/publish/now/${pin_id}`, { method: 'POST' });
                    const data = await res.json();
                    if(data.success) {
                        alert(data.message);
                        fetchSchedule();
                    } else {
                        alert('Error: ' + data.error);
                        btnEl.classList.remove('loading'); btnEl.disabled = false;
                    }
                } catch(e) {
                    alert('Request failed: ' + e);
                    btnEl.classList.remove('loading'); btnEl.disabled = false;
                }
            }

            async function triggerPublishRunner() {
                const btn = document.getElementById('btn-run-publish');
                if (!confirm('Run the publish runner now? This will process any due slots.')) return;
                
                btn.classList.add('loading');
                btn.disabled = true;
                
                try {
                    const res = await fetch('/api/publish/run', { method: 'POST' });
                    const data = await res.json();
                    if (data.success) {
                        alert(data.message);
                        fetchSchedule();
                    } else {
                        alert('Error: ' + (data.error || 'Unknown error'));
                    }
                } catch (e) {
                    alert('Request failed: ' + e);
                } finally {
                    btn.classList.remove('loading');
                    btn.disabled = false;
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
