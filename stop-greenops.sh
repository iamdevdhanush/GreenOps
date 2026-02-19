#!/bin/bash
cd ~/greenops || exit

echo "Stopping GreenOps..."
docker compose down

echo ""
docker ps
echo ""
echo "GreenOps stopped."

