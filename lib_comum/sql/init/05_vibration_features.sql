-- Per-axis vibration feature vectors used by Recipe 2 Tier 2 onwards.
--
-- PT: O extractor publica um vector de features por snapshot. O detector
-- de anomalia (Isolation Forest) lê dela. Mantemos as features separadas
-- das amplitudes de banda em vibration_bands para que a Tier 1 continue
-- viável sem features extras.
-- EN: The extractor publishes one feature vector per snapshot. The
-- anomaly detector (Isolation Forest) reads from this table. We keep
-- features separate from the band amplitudes in vibration_bands so that
-- Tier 1 stays usable without computing the extra features.

CREATE TABLE IF NOT EXISTS vibration_features (
    ts                  TIMESTAMPTZ      NOT NULL,
    machine             TEXT             NOT NULL,
    axis                TEXT             NOT NULL,
    rms_g               DOUBLE PRECISION NOT NULL,
    peak_g              DOUBLE PRECISION NOT NULL,
    crest_factor        DOUBLE PRECISION NOT NULL,
    kurtosis            DOUBLE PRECISION NOT NULL,
    dominant_freq_hz    DOUBLE PRECISION NOT NULL,
    band_rotation_1x_g  DOUBLE PRECISION NOT NULL,
    band_bpfo_g         DOUBLE PRECISION NOT NULL,
    anomaly_score       DOUBLE PRECISION
);

SELECT create_hypertable(
    'vibration_features',
    'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS vibration_features_machine_ts_idx
    ON vibration_features (machine, ts DESC);

ALTER TABLE vibration_features SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'machine, axis'
);

SELECT add_compression_policy('vibration_features', INTERVAL '7 days', if_not_exists => TRUE);
