from flask import Flask, request, render_template, Response
from datetime import datetime
import sqlite3
import csv

# ----------------------
# CONFIG
# ----------------------
CARBON_BUDGET = 5000  # kg CO2
CO2_FACTOR = 0.82
POWER_WATT = 150
DB_PATH = "greenops.db"
COST_PER_KWH = 8  # INR per kWh

DEMO_DATA = [
    {"pc_id": "PC-01", "idle_minutes": 25, "action": "SLEEP"},
    {"pc_id": "PC-02", "idle_minutes": 10, "action": "NONE"},
    {"pc_id": "PC-03", "idle_minutes": 45, "action": "SLEEP"},
]

app = Flask(__name__)

# ----------------------
# DB INIT
# ----------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pc_id TEXT,
            idle_minutes REAL,
            action TEXT,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ----------------------
# DASHBOARD
# ----------------------
@app.route("/")
def dashboard():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT pc_id, idle_minutes, action
        FROM agent_logs
        ORDER BY id DESC
        LIMIT 10
    """)
    rows = cur.fetchall()
    conn.close()

    logs = [
        {"pc_id": r[0], "idle_minutes": r[1], "action": r[2]}
        for r in rows
    ]

    if not logs:
        logs = DEMO_DATA

    total_idle = sum(log["idle_minutes"] for log in logs)
    energy = (POWER_WATT * (total_idle / 60)) / 1000
    co2 = energy * CO2_FACTOR
    remaining = CARBON_BUDGET - co2
    money_saved = energy * COST_PER_KWH

    optimized = len([l for l in logs if l["action"] == "SLEEP"])
    active = len([l for l in logs if l["action"] == "NONE"])

    return render_template(
    "dashboard.html",
    energy=round(energy, 2),
    co2=round(co2, 2),
    remaining=round(remaining, 2),
    used=round(co2, 2),
    optimized=optimized,
    active=active,
    money_saved=round(money_saved, 2),
    logs=logs
)

# ----------------------
# AGENT API
# ----------------------
@app.route("/agent/report", methods=["POST"])
def agent_report():
    data = request.json

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO agent_logs (pc_id, idle_minutes, action, timestamp) VALUES (?, ?, ?, ?)",
        (
            data.get("pc_id"),
            data.get("idle_minutes"),
            data.get("action"),
            datetime.utcnow().isoformat()
        )
    )
    conn.commit()
    conn.close()

    return {"status": "ok"}

# ----------------------
# CSV EXPORT
# ----------------------
@app.route("/export/csv")
def export_csv():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT pc_id, idle_minutes, action, timestamp
        FROM agent_logs
        ORDER BY id DESC
    """)
    rows = cur.fetchall()
    conn.close()

    def generate():
        yield "PC ID,Idle Minutes,Action,Timestamp\n"
        for r in rows:
            yield f"{r[0]},{r[1]},{r[2]},{r[3]}\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=greenops_logs.csv"
        }
    )

# ----------------------
# START SERVER
# ----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

