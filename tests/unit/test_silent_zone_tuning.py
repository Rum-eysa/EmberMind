"""EM-044 per-region silent-zone tuning tests (Epic E4).

EM-044 lets an operator adjust, *per silent region*, the two detection knobs the
EM-035/EM-040 pipeline uses - the silence **eşik** (z-score) and the **minimum
sessizlik süresi** - and reset a region back to the inherited global default. It
**writes**: one override row per region (a ``NULL`` column inherits the default)
and, for every real change, one row in the unified ``audit_trail`` ledger under
the ``threshold`` domain. These tests pin the default-inheritance merge, the
upsert + partial-knob edit, the bounds/missing-region validation, the reset
semantics (drop the row, idempotent when already default), the ledger write, and
the HTTP surface.
"""
import pytest

from src.models.spatial import SilentRegion
from src.models.silent_zone_tuning import SilentZoneTuning
from src.services.audit_trail import list_audit
from src.services.silent_zone_tuning import (
    AUDIT_DOMAIN,
    DEFAULT_MIN_SILENCE_HOURS,
    DEFAULT_SENSITIVITY_Z,
    SILENT_ZONE_TUNING_ATTRIBUTION,
    SILENT_ZONE_TUNING_PERSISTENCE,
    SilentZoneTuningError,
    effective_for_region,
    get_override,
    list_effective,
    reset_tuning,
    set_tuning,
    tuning_config,
)

_REGION = (37.0, 38.0, 27.0, 28.0)


class _Settings:
    """Stub carrying the EM-044 knobs so ``getattr`` reads real values."""

    SILENT_TUNING_DEFAULT_SENSITIVITY_Z = DEFAULT_SENSITIVITY_Z
    SILENT_TUNING_DEFAULT_MIN_SILENCE_HOURS = DEFAULT_MIN_SILENCE_HOURS
    SILENT_TUNING_MIN_SENSITIVITY_Z = 0.5
    SILENT_TUNING_MAX_SENSITIVITY_Z = 5.0
    SILENT_TUNING_MIN_SILENCE_HOURS = 0.0
    SILENT_TUNING_MAX_SILENCE_HOURS = 168.0
    SILENT_TUNING_MAX_LIMIT = 200


def _add_region(session, name, active=True):
    region = SilentRegion(
        region_name=name,
        reason="test bölge",
        min_lat=_REGION[0],
        max_lat=_REGION[1],
        min_lon=_REGION[2],
        max_lon=_REGION[3],
        geometry_wkt="",
        is_active=active,
    )
    session.add(region)
    session.flush()
    return region


# --------------------------------------------------------------------------- #
# tuning_config
# --------------------------------------------------------------------------- #
def test_config_exposes_defaults_bounds_and_audit_domain():
    cfg = tuning_config(_Settings())
    assert set(cfg["knobs"]) == {"sensitivity_z", "min_silence_hours"}
    assert cfg["defaults"]["sensitivity_z"] == DEFAULT_SENSITIVITY_Z
    assert cfg["defaults"]["min_silence_hours"] == DEFAULT_MIN_SILENCE_HOURS
    assert cfg["bounds"]["sensitivity_z"] == {"min": 0.5, "max": 5.0}
    assert cfg["audit_domain"] == AUDIT_DOMAIN == "threshold"
    assert cfg["persistence"] == SILENT_ZONE_TUNING_PERSISTENCE


# --------------------------------------------------------------------------- #
# effective merge (default inheritance)
# --------------------------------------------------------------------------- #
def test_effective_inherits_default_when_untuned(session):
    region = _add_region(session, "Alpha")
    eff = effective_for_region(session, _Settings(), region.id)
    assert eff["is_overridden"] is False
    assert eff["sensitivity_z"] == DEFAULT_SENSITIVITY_Z
    assert eff["min_silence_hours"] == DEFAULT_MIN_SILENCE_HOURS
    assert eff["sensitivity_source"] == "default"
    assert eff["min_silence_source"] == "default"


def test_effective_overrides_only_the_touched_knob(session):
    region = _add_region(session, "Alpha")
    set_tuning(session, _Settings(), region.id, sensitivity_z=3.0)
    eff = effective_for_region(session, _Settings(), region.id)
    assert eff["is_overridden"] is True
    assert eff["sensitivity_z"] == 3.0
    assert eff["sensitivity_source"] == "override"
    # The untouched knob still inherits the global default.
    assert eff["min_silence_hours"] == DEFAULT_MIN_SILENCE_HOURS
    assert eff["min_silence_source"] == "default"


def test_effective_missing_region_raises(session):
    with pytest.raises(SilentZoneTuningError, match="not found"):
        effective_for_region(session, _Settings(), 999999)


# --------------------------------------------------------------------------- #
# set_tuning (upsert + audit)
# --------------------------------------------------------------------------- #
def test_set_creates_override_and_writes_audit(session):
    region = _add_region(session, "Alpha")
    result = set_tuning(
        session,
        _Settings(),
        region.id,
        sensitivity_z=2.0,
        min_silence_hours=12.0,
        actor="op-1",
    )
    assert result["created"] is True
    assert result["tuning"]["sensitivity_z"] == 2.0
    assert result["tuning"]["min_silence_hours"] == 12.0
    assert result["tuning"]["updated_by"] == "op-1"
    assert result["audit"]["domain"] == "threshold"
    assert result["audit"]["action"] == "create"
    ledger = list_audit(session, _Settings(), domain="threshold")
    assert ledger["total_matching"] == 1
    assert ledger["entries"][0]["subject_key"] == f"silent-region:{region.id}"


def test_set_updates_existing_row(session):
    region = _add_region(session, "Alpha")
    set_tuning(session, _Settings(), region.id, sensitivity_z=2.0)
    second = set_tuning(session, _Settings(), region.id, min_silence_hours=8.0)
    assert second["created"] is False
    assert second["audit"]["action"] == "update"
    # Both knobs now present on the single row (partial edit preserved the first).
    assert second["tuning"]["sensitivity_z"] == 2.0
    assert second["tuning"]["min_silence_hours"] == 8.0
    count = len(session.query(SilentZoneTuning).all())
    assert count == 1


def test_set_requires_at_least_one_knob(session):
    region = _add_region(session, "Alpha")
    with pytest.raises(SilentZoneTuningError, match="en az bir ayar"):
        set_tuning(session, _Settings(), region.id)


def test_set_rejects_out_of_bounds_sensitivity(session):
    region = _add_region(session, "Alpha")
    with pytest.raises(SilentZoneTuningError, match="sensitivity_z"):
        set_tuning(session, _Settings(), region.id, sensitivity_z=99.0)


def test_set_rejects_out_of_bounds_min_silence(session):
    region = _add_region(session, "Alpha")
    with pytest.raises(SilentZoneTuningError, match="min_silence_hours"):
        set_tuning(session, _Settings(), region.id, min_silence_hours=-1.0)


def test_set_missing_region_raises(session):
    with pytest.raises(SilentZoneTuningError, match="not found"):
        set_tuning(session, _Settings(), 424242, sensitivity_z=2.0)


def test_get_override_none_when_untuned(session):
    region = _add_region(session, "Alpha")
    assert get_override(session, region.id) is None


# --------------------------------------------------------------------------- #
# reset_tuning (drop row + audit; idempotent)
# --------------------------------------------------------------------------- #
def test_reset_drops_row_and_writes_delete_audit(session):
    region = _add_region(session, "Alpha")
    set_tuning(session, _Settings(), region.id, sensitivity_z=3.0)
    result = reset_tuning(session, _Settings(), region.id, actor="op-2")
    assert result["reset"] is True
    assert result["already_default"] is False
    assert get_override(session, region.id) is None
    assert result["effective"]["sensitivity_z"] == DEFAULT_SENSITIVITY_Z
    assert result["audit"]["action"] == "delete"
    ledger = list_audit(session, _Settings(), domain="threshold")
    # create + delete => two threshold rows, newest first is the delete.
    assert ledger["total_matching"] == 2
    assert ledger["entries"][0]["action"] == "delete"


def test_reset_is_idempotent_when_already_default(session):
    region = _add_region(session, "Alpha")
    result = reset_tuning(session, _Settings(), region.id, actor="op-2")
    assert result["reset"] is False
    assert result["already_default"] is True
    assert result["audit"] is None
    ledger = list_audit(session, _Settings(), domain="threshold")
    assert ledger["total_matching"] == 0


def test_reset_missing_region_raises(session):
    with pytest.raises(SilentZoneTuningError, match="not found"):
        reset_tuning(session, _Settings(), 999999)


# --------------------------------------------------------------------------- #
# list_effective (enumerate active, tuned-first)
# --------------------------------------------------------------------------- #
def test_list_effective_includes_all_active_regions(session):
    _add_region(session, "Alpha")
    _add_region(session, "Beta")
    rows = list_effective(session, _Settings())
    assert len(rows) == 2
    assert all(r["is_overridden"] is False for r in rows)


def test_list_effective_sorts_tuned_first(session):
    alpha = _add_region(session, "Alpha")
    _add_region(session, "Beta")
    set_tuning(session, _Settings(), alpha.id, sensitivity_z=4.0)
    rows = list_effective(session, _Settings())
    assert rows[0]["region_id"] == alpha.id
    assert rows[0]["is_overridden"] is True
    assert rows[1]["is_overridden"] is False


def test_list_effective_skips_inactive_regions(session):
    _add_region(session, "Alpha")
    _add_region(session, "Ghost", active=False)
    rows = list_effective(session, _Settings())
    names = {r["region_name"] for r in rows}
    assert names == {"Alpha"}


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #
def test_endpoint_config(client):
    body = client.get("/api/v1/silent-zone-tuning/config").json()
    assert body["persistence"] == SILENT_ZONE_TUNING_PERSISTENCE
    assert body["attribution"] == SILENT_ZONE_TUNING_ATTRIBUTION
    assert "bounds" in body


def test_endpoint_effective_list_and_single(client, session):
    region = _add_region(session, "Alpha")
    session.commit()
    every = client.get("/api/v1/silent-zone-tuning/effective").json()
    assert every["count"] == 1
    one = client.get(
        "/api/v1/silent-zone-tuning/effective", params={"region_id": region.id}
    ).json()
    assert one["effective"]["sensitivity_z"] == DEFAULT_SENSITIVITY_Z


def test_endpoint_effective_missing_region_404(client):
    resp = client.get(
        "/api/v1/silent-zone-tuning/effective", params={"region_id": 888888}
    )
    assert resp.status_code == 404


def test_endpoint_set_then_reset(client, session):
    region = _add_region(session, "Alpha")
    session.commit()
    saved = client.post(
        "/api/v1/silent-zone-tuning",
        json={"region_id": region.id, "sensitivity_z": 2.5, "actor": "op-9"},
    )
    assert saved.status_code == 200
    assert saved.json()["status"] == "saved"
    eff = client.get(
        "/api/v1/silent-zone-tuning/effective", params={"region_id": region.id}
    ).json()
    assert eff["effective"]["sensitivity_z"] == 2.5
    reset = client.post(
        "/api/v1/silent-zone-tuning/reset",
        json={"region_id": region.id, "actor": "op-9"},
    )
    assert reset.status_code == 200
    assert reset.json()["reset"] is True


def test_endpoint_set_bad_value_400(client, session):
    region = _add_region(session, "Alpha")
    session.commit()
    resp = client.post(
        "/api/v1/silent-zone-tuning",
        json={"region_id": region.id, "sensitivity_z": 999.0},
    )
    assert resp.status_code == 400


def test_endpoint_set_missing_region_404(client):
    resp = client.post(
        "/api/v1/silent-zone-tuning",
        json={"region_id": 777777, "sensitivity_z": 2.0},
    )
    assert resp.status_code == 404
