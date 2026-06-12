-- OEE continuous aggregates and helper views.
--
-- PT: Continuous aggregates da TimescaleDB que calculam disponibilidade,
-- performance e qualidade por turno. Recipe 1 Nivel 2 (Pro) e seguintes.
-- EN: TimescaleDB continuous aggregates that compute availability,
-- performance and quality per shift. Used by Recipe 1 Tier 2 and on.
--
-- Three components of OEE:
--   - Availability: time the machine reported "running" / time scheduled.
--   - Performance:  units produced / units producible at standard rate.
--   - Quality:      good units / total units.
--
-- Recipe 1 Tier 1 has only availability data (current draw is the proxy).
-- Recipe 1 Tier 2 brings shift_count for performance. Quality lands in
-- Recipe 2 onward (defect / rework events).
--
-- The Modbus emulator publishes:
--   metric=state         -> values 0..5 (see lib_comum/plc_sim/modbus_emulator)
--   metric=shift_count   -> monotonic counter (resets at start of shift)
--   metric=temperature_c -> machine internal temp, useful for case studies
--
-- We define a base materialised view over those samples and one continuous
-- aggregate per granularity that the Grafana dashboards consume.

-- Per-minute machine availability — running fraction per minute per machine.
CREATE MATERIALIZED VIEW IF NOT EXISTS machine_availability_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', ts) AS bucket,
    machine,
    AVG(CASE WHEN value = 1 THEN 1.0 ELSE 0.0 END)::float AS running_fraction,
    COUNT(*)                                                 AS n_samples
FROM telemetry
WHERE metric = 'state'
GROUP BY bucket, machine
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'machine_availability_1m',
    start_offset => INTERVAL '2 hours',
    end_offset   => INTERVAL '1 minute',
    schedule_interval => INTERVAL '30 seconds',
    if_not_exists => TRUE
);

-- Hourly roll-up sitting on top of the 1-minute aggregate.
CREATE MATERIALIZED VIEW IF NOT EXISTS machine_availability_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', bucket) AS bucket,
    machine,
    AVG(running_fraction)::float       AS availability,
    SUM(n_samples)::bigint             AS n_samples
FROM machine_availability_1m
GROUP BY 1, machine
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'machine_availability_1h',
    start_offset => INTERVAL '7 days',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists => TRUE
);

-- Convenience view: latest 24h availability per machine. Not a continuous
-- aggregate — just a regular view that queries the 1-hour roll-up.
CREATE OR REPLACE VIEW machine_availability_last_24h AS
SELECT
    machine,
    AVG(availability)::float AS availability_24h,
    SUM(n_samples)::bigint   AS n_samples
FROM machine_availability_1h
WHERE bucket >= NOW() - INTERVAL '24 hours'
GROUP BY machine
ORDER BY machine;
