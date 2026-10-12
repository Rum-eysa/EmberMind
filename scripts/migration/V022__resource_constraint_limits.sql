-- V022: Constraint-based deployability limits for EM-050 (Epic E5 — kısıt tabanlı optimizasyon)
-- Adds optional operating limits to suppression resources and crew bases so the
-- positioning engine can reject proposals that violate menzil/yakıt-mesai/gece
-- constraints before they ever reach the commander. All columns are nullable:
-- NULL means "unknown / unconstrained", so every existing origin keeps
-- proposing exactly as before (backward compatible, ADD-only).

ALTER TABLE suppression_resources ADD COLUMN range_km FLOAT;
ALTER TABLE suppression_resources ADD COLUMN shift_minutes FLOAT;
ALTER TABLE suppression_resources ADD COLUMN night_capable BOOLEAN;

ALTER TABLE crew_bases ADD COLUMN range_km FLOAT;
ALTER TABLE crew_bases ADD COLUMN shift_minutes FLOAT;
ALTER TABLE crew_bases ADD COLUMN night_capable BOOLEAN;
