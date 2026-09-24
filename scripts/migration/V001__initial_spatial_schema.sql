-- V001: Initial Spatial PostGIS/SQLite Schema Migration for EM-005
-- Tables: fire_events, fire_forecasts, spatial_sources, silent_regions, simulation_scenarios

CREATE TABLE IF NOT EXISTS fire_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(128) NOT NULL,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    min_lat FLOAT NOT NULL,
    max_lat FLOAT NOT NULL,
    min_lon FLOAT NOT NULL,
    max_lon FLOAT NOT NULL,
    geometry_wkt TEXT NOT NULL,
    severity VARCHAR(32) NOT NULL DEFAULT 'medium',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    started_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fire_events_spatial ON fire_events (min_lat, max_lat, min_lon, max_lon);
CREATE INDEX IF NOT EXISTS idx_fire_events_coords ON fire_events (latitude, longitude);

CREATE TABLE IF NOT EXISTS fire_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key VARCHAR(64) NOT NULL,
    model_name VARCHAR(64) NOT NULL,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    predicted_area_ha FLOAT NOT NULL DEFAULT 0.0,
    geometry_wkt TEXT NOT NULL,
    forecast_for DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_fire_forecasts_spatial ON fire_forecasts (latitude, longitude);

CREATE TABLE IF NOT EXISTS spatial_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name VARCHAR(64) UNIQUE NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    min_lat FLOAT NOT NULL,
    max_lat FLOAT NOT NULL,
    min_lon FLOAT NOT NULL,
    max_lon FLOAT NOT NULL,
    geometry_wkt TEXT NOT NULL,
    last_synced_at DATETIME,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_spatial_sources_spatial ON spatial_sources (min_lat, max_lat, min_lon, max_lon);

CREATE TABLE IF NOT EXISTS silent_regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_name VARCHAR(128) NOT NULL,
    reason VARCHAR(256) NOT NULL,
    min_lat FLOAT NOT NULL,
    max_lat FLOAT NOT NULL,
    min_lon FLOAT NOT NULL,
    max_lon FLOAT NOT NULL,
    geometry_wkt TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_silent_regions_spatial ON silent_regions (min_lat, max_lat, min_lon, max_lon);

CREATE TABLE IF NOT EXISTS simulation_scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_name VARCHAR(128) NOT NULL,
    event_key VARCHAR(64) NOT NULL,
    min_lat FLOAT NOT NULL,
    max_lat FLOAT NOT NULL,
    min_lon FLOAT NOT NULL,
    max_lon FLOAT NOT NULL,
    geometry_wkt TEXT NOT NULL,
    wind_speed FLOAT NOT NULL DEFAULT 0.0,
    slope_angle FLOAT NOT NULL DEFAULT 0.0,
    fuel_model VARCHAR(64) NOT NULL DEFAULT 'varsayilan',
    simulated_area_ha FLOAT NOT NULL DEFAULT 0.0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_simulation_scenarios_spatial ON simulation_scenarios (min_lat, max_lat, min_lon, max_lon);
