from flask import Flask, request, render_template
from datetime import datetime

DEMO_DATA = [
    {"pc_id": "PC-01", "idle_minutes": 25, "action": "SLEEP"},
    {"pc_id": "PC-02", "idle_minutes": 10, "action": "NONE"},
    {"pc_id": "PC-03", "idle_minutes": 45, "action": "SLEEP"},
]

app = Flask(__name__)

AGENT_LOGS = []
CARBON_BUDGET = 5000  # kg CO2
CO2_FACTOR = 0.82
POWER_WATT = 150

@app.route("/")
def dashboard():
    data = AGENT_LOGS if AGENT_LOGS else [
        {"pc_id": "PC-01", "idle_minutes": 25, "action": "SLEEP"},
        {"pc_id": "PC-02", "idle_minutes": 10, "action": "NONE"},
        {"pc_id": "PC-03", "idle_minutes": 45, "action": "SLEEP"}
    ]

    total_idle = sum(item["idle_minutes"] for item in data)
    energy = (POWER_WATT * (total_idle / 60)) / 1000
    co2 = energy * CO2_FACTOR
    remaining = CARBON_BUDGET - co2

    optimized = len([d for d in data if d["action"] == "SLEEP"])
    active = len([d for d in data if d["action"] == "NONE"])

    return render_template(
        "dashboard.html",
        energy=round(energy, 2),
        co2=round(co2, 2),
        remaining=round(remaining, 2),
        used=round(co2, 2),
        optimized=optimized,
        active=active,
        logs=data
    )



@app.route("/agent/report", methods=["POST"])
def agent_report():
    data = request.json
    data["received_at"] = datetime.utcnow().isoformat()
    AGENT_LOGS.append(data)
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

