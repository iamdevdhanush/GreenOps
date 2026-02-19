#!/bin/bash
echo "🤖 Starting GreenOps Agent..."
cd agent
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
echo "📦 Installing dependencies..."
pip install -q -r requirements.txt
echo "🚀 Starting agent..."
python3 agent.py
