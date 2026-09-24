-- V002: Add manual fire event creation fields for EM-008
-- Adds: source, notes, reported_by, reported_at to fire_events table

ALTER TABLE fire_events ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'satellite';
ALTER TABLE fire_events ADD COLUMN notes TEXT;
ALTER TABLE fire_events ADD COLUMN reported_by VARCHAR(128);
ALTER TABLE fire_events ADD COLUMN reported_at DATETIME;
