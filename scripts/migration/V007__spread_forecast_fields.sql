-- V007: Rothermel spread-engine forecast fields for EM-015
-- Adds: per-horizon spread attributes on fire_forecasts so each stored
--       polygon carries its rate, direction and resolved input snapshot.

ALTER TABLE fire_forecasts ADD COLUMN horizon_minutes INTEGER NOT NULL DEFAULT 0;
ALTER TABLE fire_forecasts ADD COLUMN rate_of_spread_m_per_min FLOAT NOT NULL DEFAULT 0.0;
ALTER TABLE fire_forecasts ADD COLUMN spread_direction_deg FLOAT NOT NULL DEFAULT 0.0;
ALTER TABLE fire_forecasts ADD COLUMN inputs_json TEXT;

CREATE INDEX IF NOT EXISTS ix_fire_forecasts_event_horizon
    ON fire_forecasts (event_key, horizon_minutes);
