-- V005: Multi-satellite (VIIRS/MODIS) merge and latency fields for EM-012
-- Adds: common-schema product, publication time and latency to detections;
--       contributing satellites, worst-case latency and dedup counters to clusters.

ALTER TABLE fire_observations ADD COLUMN product VARCHAR(48);
ALTER TABLE fire_observations ADD COLUMN published_at DATETIME;
ALTER TABLE fire_observations ADD COLUMN latency_minutes FLOAT;

ALTER TABLE fire_clusters ADD COLUMN sources VARCHAR(160);
ALTER TABLE fire_clusters ADD COLUMN latency_minutes FLOAT;
ALTER TABLE fire_clusters ADD COLUMN deduplicated_count INTEGER NOT NULL DEFAULT 0;
