-- V004: EFFIS historical fire perimeter schema for EM-011
-- Table: historical_fire_perimeters (separate store for model calibration/validation)

CREATE TABLE IF NOT EXISTS historical_fire_perimeters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    perimeter_key VARCHAR(96) UNIQUE NOT NULL,
    effis_objectid INTEGER NOT NULL,
    fire_year INTEGER NOT NULL,
    country_code VARCHAR(8),
    country VARCHAR(64),
    national_code VARCHAR(64),
    date_start DATETIME,
    date_end DATETIME,
    area_km2 FLOAT NOT NULL DEFAULT 0.0,
    mmi_level VARCHAR(16),
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    geometry_json TEXT NOT NULL DEFAULT '{}',
    split VARCHAR(16),
    source VARCHAR(32) NOT NULL DEFAULT 'EFFIS',
    fetched_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hist_fires_objectid ON historical_fire_perimeters (effis_objectid);
CREATE INDEX IF NOT EXISTS idx_hist_fires_year ON historical_fire_perimeters (fire_year);
CREATE INDEX IF NOT EXISTS idx_hist_fires_year_country ON historical_fire_perimeters (fire_year, country_code);
CREATE INDEX IF NOT EXISTS idx_hist_fires_split ON historical_fire_perimeters (split, fire_year);
CREATE INDEX IF NOT EXISTS idx_hist_fires_centroid ON historical_fire_perimeters (latitude, longitude);
