-- Vibration data store for Recipe 2 (Tier 1 onwards).
--
-- PT: Tabelas para amplitudes espectrais e alertas. Receita 2 N1 publica
-- amplitudes nas bandas 1x rotação e BPFO; o receiver da N1 dispara
-- alertas quando a banda BPFO cresce acima do baseline rolante.
-- EN: Tables for spectral amplitudes and alerts. Recipe 2 Tier 1
-- publishes amplitudes in the 1x rotation and BPFO bands; the Tier 1
-- receiver fires alerts when the BPFO band crosses the rolling baseline.

CREATE TABLE IF NOT EXISTS vibration_bands (
    ts        TIMESTAMPTZ      NOT NULL,
    machine   TEXT             NOT NULL,
    axis      TEXT             NOT NULL,
    band      TEXT             NOT NULL,
    amp_g     DOUBLE PRECISION NOT NULL
);

SELECT create_hypertable(
    'vibration_bands',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS vibration_bands_machine_band_ts_idx
    ON vibration_bands (machine, band, ts DESC);

ALTER TABLE vibration_bands SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'machine, axis, band'
);

SELECT add_compression_policy('vibration_bands', INTERVAL '7 days', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS vibration_alerts (
    ts            TIMESTAMPTZ      NOT NULL,
    machine       TEXT             NOT NULL,
    axis          TEXT             NOT NULL,
    band          TEXT             NOT NULL,
    amp_g         DOUBLE PRECISION NOT NULL,
    baseline_g    DOUBLE PRECISION NOT NULL,
    threshold_pct DOUBLE PRECISION NOT NULL,
    severity      TEXT             NOT NULL
);

SELECT create_hypertable(
    'vibration_alerts',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS vibration_alerts_machine_ts_idx
    ON vibration_alerts (machine, ts DESC);
