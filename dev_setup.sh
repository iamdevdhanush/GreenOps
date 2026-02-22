#!/usr/bin/env bash
# =============================================================================
# GreenOps — Local Development Setup
# Run from the project root: bash dev-setup.sh
# =============================================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Check prerequisites ────────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || error "python3 not found"
command -v pip     >/dev/null 2>&1 || error "pip not found"
command -v docker  >/dev/null 2>&1 || error "docker not found"

PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MINOR" -lt 11 ]; then
    error "Python 3.11+ required (found 3.$PY_MINOR)"
fi

# ── Install Python dependencies ─────────────────────────────────────────────
info "Installing Python dependencies (psycopg2-binary, Flask, etc.)..."
pip install -r requirements.txt -q
info "Dependencies installed."

# ── Create .env if missing ──────────────────────────────────────────────────
if [ ! -f .env ]; then
    warn ".env not found. Generating from .env.example..."
    cp .env.example .env

    JWT_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    DB_PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

    sed -i "s/^JWT_SECRET_KEY=.*/JWT_SECRET_KEY=${JWT_KEY}/" .env
    sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${DB_PASS}/" .env
    sed -i "s/POSTGRES_PASSWORD_HERE/${DB_PASS}/" .env

    info ".env created with generated secrets."
    warn "Default admin password is 'admin123'. Change it after first login."
fi

# ── Start database ──────────────────────────────────────────────────────────
info "Starting PostgreSQL container..."
docker compose up -d db

info "Waiting for PostgreSQL to be ready..."
for i in $(seq 1 20); do
    if docker compose exec -T db pg_isready -U greenops -d greenops >/dev/null 2>&1; then
        info "PostgreSQL ready."
        break
    fi
    sleep 2
    if [ "$i" -eq 20 ]; then
        error "PostgreSQL did not become ready in 40 seconds."
    fi
done

# ── Export environment for local run ────────────────────────────────────────
DB_PASS_VAL=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)
JWT_KEY_VAL=$(grep '^JWT_SECRET_KEY=' .env | cut -d= -f2-)

export DATABASE_URL="postgresql://greenops:${DB_PASS_VAL}@localhost:5433/greenops"
export JWT_SECRET_KEY="${JWT_KEY_VAL}"
export ADMIN_INITIAL_PASSWORD="admin123"
export LOG_FILE="./logs/greenops.log"
export DEBUG="true"

mkdir -p logs

# ── Run server ───────────────────────────────────────────────────────────────
info "Starting GreenOps server on http://localhost:8000 ..."
info "Dashboard available at: open dashboard/index.html in browser"
info "Or run 'docker compose up -d --build' for full stack at http://localhost"
info ""
info "Press Ctrl+C to stop."
info ""

python3 -m server.main
