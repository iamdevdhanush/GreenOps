-- GreenOps Migration 002
-- Adds heartbeat retention function and any missing indexes.
-- Safe to run multiple times (all objects use IF NOT EXISTS / OR REPLACE).

-- Covering index to make status-filtered machine list queries index-only
CREATE INDEX IF NOT EXISTS idx_machines_status_energy
    ON machines (status, last_seen DESC, energy_wasted_kwh);

-- Allow fast lookup of heartbeats newer than a given timestamp (used by retention)
CREATE INDEX IF NOT EXISTS idx_heartbeats_timestamp_machine
    ON heartbeats (timestamp DESC, machine_id);

-- Retention function: deletes heartbeats older than retain_days.
-- Call via pg_cron, a cron job, or an admin API endpoint.
-- Example: SELECT prune_old_heartbeats(90);
CREATE OR REPLACE FUNCTION prune_old_heartbeats(retain_days INTEGER DEFAULT 90)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    deleted INTEGER;
BEGIN
    DELETE FROM heartbeats
    WHERE timestamp < NOW() - (retain_days || ' days')::INTERVAL;
    GET DIAGNOSTICS deleted = ROW_COUNT;
    RAISE NOTICE 'prune_old_heartbeats: deleted % rows older than % days', deleted, retain_days;
    RETURN deleted;
END;
$$;

-- Trigger function: keep updated_at current on machines rows
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_machines_updated_at ON machines;
CREATE TRIGGER trg_machines_updated_at
    BEFORE UPDATE ON machines
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();
