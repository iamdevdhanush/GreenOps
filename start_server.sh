#!/bin/bash
echo "🚀 Starting GreenOps Server..."
sudo docker-compose up -d
echo ""
echo "⏳ Waiting for services to be ready..."
sleep 30
echo ""
echo "📊 Service Status:"
sudo docker-compose ps
echo ""
echo "🔍 Testing server health..."
curl -s http://localhost:8000/health | python3 -m json.tool
echo ""
echo "✅ Server is ready!"
echo "   Dashboard: http://localhost"
echo "   Login: admin / admin123"
echo ""
