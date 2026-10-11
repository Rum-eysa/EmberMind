-- V035: Kullanici ve rol yonetimi ulke kapsami (EM-101, Epic E10)
-- Adds a nullable country scope to the EM-098 accounts table so an
-- administrator can assign a per-account country (TR / GR) alongside the role
-- ("Rol atama ve ülke bazlı yetki"). NULL means a global, unscoped account, so
-- every existing row keeps its current behaviour and the change is purely
-- additive. Add/edit/deactivate themselves are audited through the EM-096
-- unified ledger (audit_trail, V030) - no new table is needed here.

ALTER TABLE users ADD COLUMN country VARCHAR(2);
