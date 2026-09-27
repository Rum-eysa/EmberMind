-- V013: Exposed assets (settlements and energy lines) for EM-023 (Epic E2)
-- Table: exposed_assets — OpenStreetMap places and power lines that the
-- exposure analysis intersects with the spread-forecast horizon polygons to
-- compute a first-impact time (T+dk) per element. Roads are read from
-- road_segments (EM-011) and are not duplicated here.

CREATE TABLE IF NOT EXISTS exposed_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_key VARCHAR(96) UNIQUE NOT NULL,
    asset_type VARCHAR(32) NOT NULL,
    name VARCHAR(160),
    osm_id INTEGER,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    min_lat FLOAT NOT NULL,
    max_lat FLOAT NOT NULL,
    min_lon FLOAT NOT NULL,
    max_lon FLOAT NOT NULL,
    geometry_wkt TEXT NOT NULL,
    tags_json TEXT,
    source VARCHAR(64) NOT NULL DEFAULT 'OpenStreetMap',
    fetched_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_exposed_assets_type ON exposed_assets (asset_type);
CREATE INDEX IF NOT EXISTS idx_exposed_assets_spatial
    ON exposed_assets (min_lat, max_lat, min_lon, max_lon);
