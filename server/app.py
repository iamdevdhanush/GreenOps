from flask import Flask, request, render_template
from datetime import datetime

app = Flask(__name__)

AGENT_LOGS = []
CARBON_BUDGET = 5000  # kg CO2
CO2_FACTOR = 0.82
POWER_WATT = 150

@app.route("/")
def dashboard():
    total_idle = sum(log["idle_minutes"] for log in AGENT_LOGS)
    energy = (POWER_WATT * (total_idle / 60)) / 1000
    co2 = energy * CO2_FACTOR
    remaining = CARBON_BUDGET - co2

    return render_template(
        "dashboard.html",
        energy=round(energy, 2),
        co2=round(co2, 2),
        remaining=round(remaining, 2),
        logs=AGENT_LOGS[-10:]
    )

@app.route("/agent/report", methods=["POST"])
def agent_report():
    data = request.json
    data["received_at"] = datetime.utcnow().isoformat()
    AGENT_LOGS.append(data)
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

