-- V003: Road network and accessibility schema for EM-009
-- Tables: road_segments, road_closures, crew_bases

CREATE TABLE IF NOT EXISTS road_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_key VARCHAR(96) UNIQUE NOT NULL,
    osm_way_id INTEGER NOT NULL,
    from_node_id INTEGER NOT NULL,
    to_node_id INTEGER NOT NULL,
    from_lat FLOAT NOT NULL,
    from_lon FLOAT NOT NULL,
    to_lat FLOAT NOT NULL,
    to_lon FLOAT NOT NULL,
    name VARCHAR(128),
    highway VARCHAR(64) NOT NULL DEFAULT 'unclassified',
    length_km FLOAT NOT NULL DEFAULT 0.0,
    max_speed_kmh FLOAT NOT NULL DEFAULT 50.0,
    one_way BOOLEAN NOT NULL DEFAULT 0,
    fetched_at DATETIME NOT NULL,
    source VARCHAR(64) NOT NULL DEFAULT 'OpenStreetMap',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_road_segments_way ON road_segments (osm_way_id);
CREATE INDEX IF NOT EXISTS idx_road_segments_endpoints ON road_segments (from_node_id, to_node_id);
CREATE INDEX IF NOT EXISTS idx_road_segments_spatial ON road_segments (from_lat, to_lat, from_lon, to_lon);

CREATE TABLE IF NOT EXISTS road_closures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_key VARCHAR(96) NOT NULL,
    osm_way_id INTEGER,
    reason VARCHAR(256) NOT NULL DEFAULT 'unspecified',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    reported_by VARCHAR(128),
    reported_at DATETIME NOT NULL,
    resolved_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_road_closures_segment_status ON road_closures (segment_key, status);

CREATE TABLE IF NOT EXISTS crew_bases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_key VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(128) NOT NULL,
    latitude FLOAT NOT NULL,
    longitude FLOAT NOT NULL,
    crew_type VARCHAR(64) NOT NULL DEFAULT 'first_response',
    available BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_crew_bases_coords ON crew_bases (latitude, longitude);
