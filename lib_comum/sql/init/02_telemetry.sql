-- Core telemetry hypertable used by Recipe 1 and downstream recipes.
-- Runs once at first boot, after 01_extensions.sql.

CREATE TABLE IF NOT EXISTS telemetry (
    ts        TIMESTAMPTZ      NOT NULL,
    machine   TEXT             NOT NULL,
    metric    TEXT             NOT NULL,
    value     DOUBLE PRECISION NOT NULL
);

SELECT create_hypertable(
    'telemetry',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Lookups by (machine, metric, ts) dominate the query pattern.
CREATE INDEX IF NOT EXISTS telemetry_machine_metric_ts_idx
    ON telemetry (machine, metric, ts DESC);

-- Compress chunks older than 7 days to keep disk usage low on small servers.
ALTER TABLE telemetry SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'machine, metric'
);

SELECT add_compression_policy('telemetry', INTERVAL '7 days', if_not_exists => TRUE);
