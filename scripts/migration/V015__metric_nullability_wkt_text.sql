-- V015: Honest "unknown" metrics + wide geometry columns
--
-- 1) spread_evaluation_metrics: area_error_pct / arrival_time_error_min must
--    be nullable so "undefined" is stored as NULL instead of a fake perfect
--    0.0 (SQLite cannot DROP NOT NULL, so the table is rebuilt in place).
--    Historical 0.0 rows are preserved as-is.
CREATE TABLE spread_evaluation_metrics_v015 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key VARCHAR(64) NOT NULL,
    model_version VARCHAR(64) NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    iou_score FLOAT NOT NULL DEFAULT 0.0,
    area_error_pct FLOAT,
    arrival_time_error_min FLOAT,
    predicted_area_ha FLOAT NOT NULL DEFAULT 0.0,
    actual_area_ha FLOAT NOT NULL DEFAULT 0.0,
    predicted_arrival_min FLOAT,
    actual_arrival_min FLOAT,
    evaluation_batch VARCHAR(64),
    details_json TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO spread_evaluation_metrics_v015 (
    id, event_key, model_version, horizon_minutes, iou_score,
    area_error_pct, arrival_time_error_min, predicted_area_ha, actual_area_ha,
    predicted_arrival_min, actual_arrival_min, evaluation_batch, details_json,
    created_at, updated_at
)
SELECT
    id, event_key, model_version, horizon_minutes, iou_score,
    area_error_pct, arrival_time_error_min, predicted_area_ha, actual_area_ha,
    predicted_arrival_min, actual_arrival_min, evaluation_batch, details_json,
    created_at, updated_at
FROM spread_evaluation_metrics;
DROP TABLE spread_evaluation_metrics;
ALTER TABLE spread_evaluation_metrics_v015 RENAME TO spread_evaluation_metrics;
CREATE INDEX IF NOT EXISTS idx_spread_eval_event_key ON spread_evaluation_metrics (event_key);
CREATE INDEX IF NOT EXISTS idx_spread_eval_model_version ON spread_evaluation_metrics (model_version);
CREATE INDEX IF NOT EXISTS idx_spread_eval_event_version ON spread_evaluation_metrics (event_key, model_version);
CREATE INDEX IF NOT EXISTS idx_spread_eval_batch ON spread_evaluation_metrics (evaluation_batch);

-- 2) geometry_wkt VARCHAR(512) -> TEXT on fire_events, spatial_sources,
--    silent_regions and simulation_scenarios (long elliptical horizon rings
--    were truncated on PostgreSQL while SQLite applies TEXT affinity to
--    VARCHAR, so it is a documentation no-op there). Fresh schemas get the
--    widened type from the ORM models via create_all.
