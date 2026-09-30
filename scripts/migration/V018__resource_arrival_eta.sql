-- V018: Time-dependent capacity arrival for EM-033 (Epic E3 — en-route ETA)
-- Adds an estimated on-station arrival instant to suppression resources so the
-- capacity-gap timeline can bring an "en_route" asset online from its ETA. The
-- column is nullable: a resource with no committed arrival keeps the EM-031
-- behaviour (excluded from effective capacity until it flips to "available").

ALTER TABLE suppression_resources ADD COLUMN arrival_eta DATETIME;
