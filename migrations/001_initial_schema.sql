-- GreenOps Initial Schema
-- PostgreSQL 15+
-- All timestamps stored with time zone to avoid UTC/naive mismatch bugs.

-- Users table for admin authentication
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(512)        NOT NULL,
    role          VARCHAR(50)         NOT NULL DEFAULT 'viewer',
    created_at    TIMESTAMPTZ         DEFAULT NOW(),
    CONSTRAINT valid_role CHECK (role IN ('admin', 'viewer'))
);

-- Machines table — MAC address is the permanent primary identity
CREATE TABLE IF NOT EXISTS machines (
    id                   SERIAL PRIMARY KEY,
    mac_address          VARCHAR(17) UNIQUE NOT NULL,
    hostname             VARCHAR(255)       NOT NULL,
    os_type              VARCHAR(50)        NOT NULL,
    os_version           VARCHAR(100),
    first_seen           TIMESTAMPTZ        DEFAULT NOW(),
    last_seen            TIMESTAMPTZ        DEFAULT NOW(),
    total_idle_seconds   BIGINT             DEFAULT 0,
    total_active_seconds BIGINT             DEFAULT 0,
    energy_wasted_kwh    DECIMAL(10, 3)     DEFAULT 0.0,
    status               VARCHAR(20)        DEFAULT 'offline',
    created_at           TIMESTAMPTZ        DEFAULT NOW(),
    updated_at           TIMESTAMPTZ        DEFAULT NOW(),
    CONSTRAINT valid_status   CHECK (status IN ('online', 'offline', 'idle')),
    CONSTRAINT positive_energy CHECK (energy_wasted_kwh >= 0)
);

CREATE INDEX IF NOT EXISTS idx_machines_mac            ON machines (mac_address);
CREATE INDEX IF NOT EXISTS idx_machines_status_last    ON machines (status, last_seen DESC);

-- Heartbeats table
CREATE TABLE IF NOT EXISTS heartbeats (
    id            SERIAL PRIMARY KEY,
    machine_id    INTEGER        NOT NULL REFERENCES machines (id) ON DELETE CASCADE,
    timestamp     TIMESTAMPTZ    DEFAULT NOW(),
    idle_seconds  INTEGER        NOT NULL DEFAULT 0,
    cpu_usage     DECIMAL(5, 2),
    memory_usage  DECIMAL(5, 2),
    is_idle       BOOLEAN        DEFAULT FALSE,
    created_at    TIMESTAMPTZ    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_heartbeats_machine_ts ON heartbeats (machine_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_heartbeats_timestamp  ON heartbeats (timestamp DESC);

-- Agent tokens
CREATE TABLE IF NOT EXISTS agent_tokens (
    id         SERIAL PRIMARY KEY,
    machine_id INTEGER UNIQUE  NOT NULL REFERENCES machines (id) ON DELETE CASCADE,
    token_hash VARCHAR(64)     NOT NULL,
    issued_at  TIMESTAMPTZ     DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    revoked    BOOLEAN         DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_agent_tokens_hash    ON agent_tokens (token_hash);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_machine ON agent_tokens (machine_id);

-- Default admin user.
-- Password is argon2id hash of 'admin123'.
-- IMPORTANT: Set ADMIN_INITIAL_PASSWORD in your environment to override this
-- on first boot. The server reads this variable and replaces the hash before
-- accepting any traffic. Do NOT rely on admin123 in production.
INSERT INTO users (username, password_hash, role)
VALUES (
    'admin',
    '$argon2id$v=19$m=65536,t=2,p=4$qF0jpDQmZGwNwVjr3TuHMA$vxzDBmXhqtN4TauQDWCCmqPa3+xkW5Y1jtFbFMPdWxU',
    'admin'
)
ON CONFLICT (username) DO NOTHING;
