-- GreenOps Initial Schema
-- PostgreSQL 15+

-- Users table for admin authentication
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_role CHECK (role IN ('admin', 'viewer'))
);

-- Machines table - MAC address is PRIMARY IDENTITY
CREATE TABLE IF NOT EXISTS machines (
    id SERIAL PRIMARY KEY,
    mac_address VARCHAR(17) UNIQUE NOT NULL,  -- PRIMARY IDENTITY: one MAC = one machine forever
    hostname VARCHAR(255) NOT NULL,
    os_type VARCHAR(50) NOT NULL,
    os_version VARCHAR(100),
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_idle_seconds BIGINT DEFAULT 0,
    total_active_seconds BIGINT DEFAULT 0,
    energy_wasted_kwh DECIMAL(10,3) DEFAULT 0.0,  -- Cumulative energy waste
    status VARCHAR(20) DEFAULT 'offline',
    agent_token_hash VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_status CHECK (status IN ('online', 'offline', 'idle')),
    CONSTRAINT positive_energy CHECK (energy_wasted_kwh >= 0)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_machines_mac ON machines(mac_address);
CREATE INDEX IF NOT EXISTS idx_machines_status ON machines(status);
CREATE INDEX IF NOT EXISTS idx_machines_last_seen ON machines(last_seen);

-- Heartbeats table for tracking agent activity
CREATE TABLE IF NOT EXISTS heartbeats (
    id SERIAL PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    idle_seconds INTEGER NOT NULL DEFAULT 0,
    cpu_usage DECIMAL(5,2),
    memory_usage DECIMAL(5,2),
    is_idle BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_heartbeats_machine ON heartbeats(machine_id, timestamp DESC);

-- Agent tokens for authentication
CREATE TABLE IF NOT EXISTS agent_tokens (
    id SERIAL PRIMARY KEY,
    machine_id INTEGER UNIQUE NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    revoked BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_agent_tokens_machine ON agent_tokens(machine_id);

-- Create default admin user (password: admin123 - MUST CHANGE IN PRODUCTION)
-- Password hash is argon2: admin123
INSERT INTO users (username, password_hash, role) 
VALUES ('admin', '$argon2id$v=19$m=65536,t=2,p=4$qF0jpDQmZGwNwVjr3TuHMA$vxzDBmXhqtN4TauQDWCCmqPa3+xkW5Y1jtFbFMPdWxU', 'admin')
ON CONFLICT (username) DO NOTHING;
