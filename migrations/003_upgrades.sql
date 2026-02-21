-- GreenOps Migration 003 — Upgrade: Commands, Uptime, Password Policy
-- Safe to run multiple times (all DDL is idempotent via DO blocks or IF NOT EXISTS).
-- For EXISTING deployments: run manually via:
--   docker compose exec db psql -U greenops < migrations/003_upgrades.sql

-- ── must_change_password column on users ─────────────────────────────────────
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'must_change_password'
    ) THEN
        ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
        -- Force existing admin to change password on next login.
        UPDATE users SET must_change_password = TRUE WHERE username = 'admin';
    END IF;
END $$;

-- ── uptime_seconds column on machines ─────────────────────────────────────────
-- Stores the last reported system uptime (seconds since boot) from the agent.
-- More accurate than accumulating heartbeat intervals.
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'machines' AND column_name = 'uptime_seconds'
    ) THEN
        ALTER TABLE machines ADD COLUMN uptime_seconds BIGINT NOT NULL DEFAULT 0;
    END IF;
END $$;

-- ── machine_commands table ────────────────────────────────────────────────────
-- Admin-initiated remote commands (sleep / shutdown).
-- Agent polls for pending commands, executes them, then reports the result.
CREATE TABLE IF NOT EXISTS machine_commands (
    id          SERIAL PRIMARY KEY,
    machine_id  INTEGER     NOT NULL REFERENCES machines (id) ON DELETE CASCADE,
    command     VARCHAR(20) NOT NULL,                 -- 'sleep' or 'shutdown'
    status      VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | executed | failed | expired
    created_by  INTEGER     REFERENCES users (id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at TIMESTAMPTZ,
    result_msg  TEXT,
    CONSTRAINT valid_command CHECK (command  IN ('sleep', 'shutdown')),
    CONSTRAINT valid_cmd_status CHECK (status IN ('pending', 'executed', 'failed', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_commands_machine_status
    ON machine_commands (machine_id, status)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_commands_created
    ON machine_commands (created_at DESC);

-- Expire commands older than 5 minutes that were never picked up.
-- Call via pg_cron or the background checker.
CREATE OR REPLACE FUNCTION expire_stale_commands()
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    expired INTEGER;
BEGIN
    UPDATE machine_commands
    SET status = 'expired'
    WHERE status = 'pending'
      AND created_at < NOW() - INTERVAL '5 minutes';
    GET DIAGNOSTICS expired = ROW_COUNT;
    RETURN expired;
END;
$$;
