# 🌱 GreenOps

GreenOps is a **digital carbon governance system** designed to reduce unnecessary carbon emissions caused by idle IT systems in colleges, offices, and labs.

Instead of just monitoring power usage, GreenOps introduces the concept of **carbon budgeting** for IT infrastructure.

---

## 🚀 What Problem Does It Solve?

- Computers stay idle but powered on
- Electricity usage is unaccounted at system level
- Carbon emissions are invisible and unmanaged
- No policy-driven energy governance exists

GreenOps makes IT carbon usage **visible, measurable, and controllable**.

---

## 🧠 How GreenOps Works

System Activity → Idle Detection → Policy Engine
→ Energy & CO₂ Calculation
→ Carbon Budget Tracking
→ Admin Dashboard


---

## 🖥 Components

### 1️⃣ GreenOps Server
- Flask-based admin dashboard
- Cross-platform (Linux / Windows)
- Carbon budgeting & reporting
- Demo & production modes

### 2️⃣ GreenOps Agent
- OS-aware (Linux & Windows)
- Detects idle time
- Applies safe power actions (sleep-first)
- Reports usage to server

---

## 🔐 Safety Design

- No forced shutdown
- Sleep-first policy
- Warning before actions
- Demo mode disables real power actions
- No auto-save claims

---

## ▶️ How to Run (Demo)

### Server
```bash
cd server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py

```
Open:

http://localhost:5000

Agent

cd agent
pip install -r requirements.txt
python agent.py

📊 Key Features

Carbon budget tracking

Energy & CO₂ estimation

Policy-based optimization

Admin-only interface

Audit-ready logs

Cross-platform design

⚠️ Demo vs Production

| Mode       | Behavior                    |
| ---------- | --------------------------- |
| Demo       | Actions simulated           |
| Production | Real sleep (admin-approved) |

🏁 Summary

GreenOps proves that software-level governance can significantly reduce IT-related carbon emissions without disrupting users.
