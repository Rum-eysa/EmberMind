-- V006: Fire Weather Index (FWI) & drought indicator layer for EM-014
-- Adds: per-zone daily FWI profiles and the precipitation input on weather
--       data points that the FWI computation requires.

CREATE TABLE IF NOT EXISTS fire_weather_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    zone_key VARCHAR(32) NOT NULL,
    region_name VARCHAR(64) NOT NULL,
    day DATE NOT NULL,
    center_lat FLOAT NOT NULL,
    center_lon FLOAT NOT NULL,
    min_lat FLOAT NOT NULL,
    min_lon FLOAT NOT NULL,
    max_lat FLOAT NOT NULL,
    max_lon FLOAT NOT NULL,
    temperature FLOAT,
    humidity FLOAT,
    wind_speed FLOAT,
    rain FLOAT,
    ffmc FLOAT NOT NULL,
    dmc FLOAT NOT NULL,
    dc FLOAT NOT NULL,
    isi FLOAT NOT NULL,
    bui FLOAT NOT NULL,
    fwi FLOAT NOT NULL,
    risk_category VARCHAR(16) NOT NULL,
    drought_category VARCHAR(16) NOT NULL,
    data_point_count INTEGER NOT NULL,
    computed_at DATETIME,
    CONSTRAINT uq_fwi_zone_day UNIQUE (zone_key, day)
);

CREATE INDEX IF NOT EXISTS ix_fire_weather_index_zone_key ON fire_weather_index (zone_key);
CREATE INDEX IF NOT EXISTS ix_fire_weather_index_day ON fire_weather_index (day);
CREATE INDEX IF NOT EXISTS ix_fire_weather_index_fwi ON fire_weather_index (fwi);

ALTER TABLE weather_data_points ADD COLUMN rain FLOAT NOT NULL DEFAULT 0.0;
