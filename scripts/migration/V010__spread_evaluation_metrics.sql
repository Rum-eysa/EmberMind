-- V010: Spread evaluation metrics table for EM-017 (E2)
-- Stores IoU/Jaccard, area error, and arrival time error per model version.

CREATE TABLE IF NOT EXISTS spread_evaluation_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key VARCHAR(64) NOT NULL,
    model_version VARCHAR(64) NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    iou_score FLOAT NOT NULL DEFAULT 0.0,
    area_error_pct FLOAT NOT NULL DEFAULT 0.0,
    arrival_time_error_min FLOAT NOT NULL DEFAULT 0.0,
    predicted_area_ha FLOAT NOT NULL DEFAULT 0.0,
    actual_area_ha FLOAT NOT NULL DEFAULT 0.0,
    predicted_arrival_min FLOAT,
    actual_arrival_min FLOAT,
    evaluation_batch VARCHAR(64),
    details_json TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_spread_eval_event_key ON spread_evaluation_metrics (event_key);
CREATE INDEX IF NOT EXISTS idx_spread_eval_model_version ON spread_evaluation_metrics (model_version);
CREATE INDEX IF NOT EXISTS idx_spread_eval_event_version ON spread_evaluation_metrics (event_key, model_version);
CREATE INDEX IF NOT EXISTS idx_spread_eval_batch ON spread_evaluation_metrics (evaluation_batch);
