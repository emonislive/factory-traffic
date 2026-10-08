-- Schema DDL for Factory Traffic Management System
-- Frozen at Gate 1 (Instruction.md section 5.4, Decision.md P-01)

CREATE TABLE IF NOT EXISTS junctions (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    config JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS junction_state (
    junction_id VARCHAR(64) PRIMARY KEY REFERENCES junctions(id) ON DELETE CASCADE,
    version INT NOT NULL DEFAULT 1,
    mode VARCHAR(32) NOT NULL,
    serving VARCHAR(16) NOT NULL,
    step VARCHAR(32) NOT NULL,
    target VARCHAR(16),
    deadline_at DOUBLE PRECISION,
    desired JSONB NOT NULL,
    actual JSONB NOT NULL,
    manual JSONB NOT NULL,
    emergencies JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vehicles (
    id BIGSERIAL PRIMARY KEY,
    junction_id VARCHAR(64) NOT NULL REFERENCES junctions(id) ON DELETE CASCADE,
    vehicle_id VARCHAR(64) NOT NULL,
    direction VARCHAR(16) NOT NULL,
    vehicle_type VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL, -- WAITING, CLEARED, ORPHAN_CLEARED
    arrival_seq BIGINT,
    clear_seq BIGINT,
    arrived_server_at DOUBLE PRECISION,
    arrived_sensor_at TIMESTAMPTZ,
    cleared_server_at DOUBLE PRECISION
);

-- Partial unique index per P-01: exactly one WAITING row per (junction_id, vehicle_id)
CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicles_unique_waiting 
ON vehicles(junction_id, vehicle_id) 
WHERE status = 'WAITING';

CREATE INDEX IF NOT EXISTS idx_vehicles_junction_direction_status
ON vehicles(junction_id, direction, status);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id VARCHAR(128) PRIMARY KEY,
    junction_id VARCHAR(64) NOT NULL REFERENCES junctions(id) ON DELETE CASCADE,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome VARCHAR(32) NOT NULL, -- APPLIED, DUPLICATE, STALE, REJECTED
    payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS direction_sequence (
    junction_id VARCHAR(64) NOT NULL REFERENCES junctions(id) ON DELETE CASCADE,
    direction VARCHAR(16) NOT NULL,
    last_sequence_no BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (junction_id, direction)
);

CREATE TABLE IF NOT EXISTS commands (
    command_id VARCHAR(128) PRIMARY KEY,
    junction_id VARCHAR(64) NOT NULL REFERENCES junctions(id) ON DELETE CASCADE,
    direction VARCHAR(16) NOT NULL,
    requested_state VARCHAR(16) NOT NULL,
    status VARCHAR(32) NOT NULL, -- PENDING, ACKED, FAILED, ABANDONED
    attempts INT NOT NULL DEFAULT 1,
    sent_at DOUBLE PRECISION NOT NULL,
    deadline_at DOUBLE PRECISION NOT NULL,
    acked_at DOUBLE PRECISION,
    actual_state VARCHAR(16)
);

CREATE TABLE IF NOT EXISTS device_status (
    junction_id VARCHAR(64) NOT NULL REFERENCES junctions(id) ON DELETE CASCADE,
    device_type VARCHAR(64) NOT NULL, -- SIGNAL_CONTROLLER, SENSOR
    direction VARCHAR(16) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL, -- ONLINE, OFFLINE, DEGRADED, WARNING, UNKNOWN
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (junction_id, device_type, direction)
);

-- Append-only audit log: no UPDATE or DELETE code paths (Instruction.md 5.4)
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    junction_id VARCHAR(64) NOT NULL REFERENCES junctions(id) ON DELETE CASCADE,
    event_type VARCHAR(64) NOT NULL,
    direction VARCHAR(16),
    previous_state VARCHAR(16),
    new_state VARCHAR(16),
    command_id VARCHAR(128),
    reason TEXT,
    payload JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source VARCHAR(64) NOT NULL DEFAULT 'SYSTEM'
);

CREATE INDEX IF NOT EXISTS idx_audit_log_junction_occurred
ON audit_log(junction_id, id DESC);
