#!/bin/bash
cd ~/greenops || exit

echo "Stopping old containers..."
docker compose down

echo "Building & starting GreenOps..."
docker compose up -d --build

echo ""
docker compose ps
echo ""
echo "App running at: http://localhost"

