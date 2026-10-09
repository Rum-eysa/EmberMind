"""EM-106: single-command demo database reset + seed tests.

The demo seed script lives under ``scripts/`` (not an importable package), so
the module is loaded by path here. The reset/seed behaviour itself is exercised
against a clean in-memory database with every model registered.
"""
import importlib.util
import os
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

import src.models  # noqa: F401  (populate Base.metadata for a full reset)
from src.database import Database
from src.models.spatial import FireEvent

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "demo_seed.py"


def _load_demo_seed():
    """Load scripts/demo_seed.py as a module for direct testing."""
    spec = importlib.util.spec_from_file_location("demo_seed", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="demo_seed")
def fixture_demo_seed():
    """Provide the loaded demo_seed module (path-based import)."""
    assert os.path.exists(_SCRIPT_PATH)
    return _load_demo_seed()


@pytest.fixture(name="test_db")
def fixture_test_db():
    """A clean in-memory database with all registered tables created."""
    db = Database("sqlite:///:memory:")
    db.create_all()
    return db


def _event_count(database: Database) -> int:
    with database.session() as session:
        return session.scalar(select(func.count()).select_from(FireEvent)) or 0


def test_reset_all_drops_and_recreates(test_db):
    """reset_all empties every table but leaves a usable schema behind."""
    test_db.reset_all()
    assert _event_count(test_db) == 0
    # Tables still exist after reset (create_all ran again).
    test_db.create_all()
    assert _event_count(test_db) == 0


def test_seed_demo_labels_synthetic_events(test_db, demo_seed):
    """A seeded scenario writes events labelled as synthetic."""
    report = demo_seed.seed_demo(test_db, seed=7, preset="standart")
    assert report["reset"] is False
    assert report["seed"] == 7
    assert report["scenario_tag"].startswith("syn-")
    assert report["counts"]["events"] >= 1
    assert "SENTETİK" in report["synthetic_label"]
    with test_db.session() as session:
        rows = session.scalars(select(FireEvent)).all()
    assert rows
    assert all(r.source == "synthetic" for r in rows)


def test_seed_demo_without_reset_is_idempotent(test_db, demo_seed):
    """Without reset, re-running the same seed does not duplicate events."""
    demo_seed.seed_demo(test_db, seed=7, preset="standart")
    first = _event_count(test_db)
    demo_seed.seed_demo(test_db, seed=7, preset="standart")
    second = _event_count(test_db)
    assert first == second
    assert first >= 1


def test_seed_demo_reset_wipes_stray_rows(test_db, demo_seed):
    """reset=True clears unrelated pre-existing rows before seeding."""
    with test_db.session() as session:
        session.add(
            FireEvent(
                event_key="stray-legacy-1",
                name="Eski kayıt",
                latitude=38.0,
                longitude=27.5,
                min_lat=38.0,
                max_lat=38.0,
                min_lon=27.5,
                max_lon=27.5,
                geometry_wkt="POINT(27.5 38.0)",
                severity="medium",
                status="active",
                started_at=datetime(2020, 1, 1),
                source="legacy",
            )
        )
    assert _event_count(test_db) >= 1

    demo_seed.seed_demo(test_db, seed=11, preset="standart", reset=True)
    with test_db.session() as session:
        stray = session.scalars(
            select(FireEvent).where(FireEvent.event_key == "stray-legacy-1")
        ).all()
        sources = {r.source for r in session.scalars(select(FireEvent)).all()}
    assert stray == []
    assert sources == {"synthetic"}


def test_seed_demo_reset_produces_single_scenario(test_db, demo_seed):
    """After a reset exactly one labelled scenario is present."""
    demo_seed.seed_demo(test_db, seed=9, preset="standart", reset=True)
    report = demo_seed.seed_demo(test_db, seed=9, preset="standart", reset=True)
    assert report["reset"] is True
    with test_db.session() as session:
        rows = session.scalars(select(FireEvent)).all()
    assert rows
    assert all(r.source == "synthetic" for r in rows)
    # Every event belongs to the freshly seeded scenario tag prefix.
    assert all(r.event_key.startswith("SYN-") for r in rows)


def test_reset_requested_reads_argv(demo_seed):
    """The CLI flag toggles reset regardless of environment."""
    assert demo_seed._reset_requested(["--reset"]) is True
    assert demo_seed._reset_requested([]) is False


def test_reset_requested_reads_env(demo_seed, monkeypatch):
    """A truthy DEMO_RESET env enables reset without the flag."""
    monkeypatch.setenv("DEMO_RESET", "true")
    assert demo_seed._reset_requested([]) is True
    monkeypatch.setenv("DEMO_RESET", "0")
    assert demo_seed._reset_requested([]) is False


def test_seed_demo_report_shape(test_db, demo_seed):
    """The returned report exposes the keys the CLI prints."""
    report = demo_seed.seed_demo(test_db, seed=5, preset="standart", reset=True)
    assert set(report) == {
        "reset",
        "seed",
        "preset",
        "scenario_tag",
        "counts",
        "exposure",
        "synthetic_label",
        "demo_account",
    }
    assert report["preset"] == "standart"
    assert "forecasts" in report["exposure"]
