"""Manual fire event creation and management tests."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.fastapi_app import create_fastapi_app
from src.models.fire import FireCluster
from src.models.spatial import FireEvent
from src.services.manual_fire_event import (
    DuplicateFireEventError,
    ManualFireEventError,
    check_for_duplicates,
    create_manual_fire_event,
    generate_event_key,
    trigger_prediction_for_event,
)


def test_generate_event_key():
    """Test event key generation."""
    dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
    key = generate_event_key(41.0, 28.0, dt)
    
    assert key.startswith("manual_")
    assert "4100" in key
    assert "2800" in key
    assert "20240115103045" in key


def test_generate_event_key_negative_coords():
    """Test event key generation with negative coordinates."""
    dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
    key = generate_event_key(-41.0, -28.0, dt)
    
    assert key.startswith("manual_")
    assert "m4100" in key  # negative latitude
    assert "m2800" in key  # negative longitude


def test_check_for_duplicates_no_clusters(session):
    """Test duplicate detection when no clusters exist."""
    duplicate = check_for_duplicates(session, 41.0, 28.0)
    
    assert duplicate is None


def test_check_for_duplicates_with_cluster(session):
    """Test duplicate detection when a nearby cluster exists."""
    # Create a cluster at the same location
    cluster = FireCluster(
        cluster_key="test_cluster_123",
        latitude=41.0,
        longitude=28.0,
        observation_count=5,
        first_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
        last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(cluster)
    session.flush()
    
    # Check for duplicates at the same location
    duplicate = check_for_duplicates(session, 41.0, 28.0)
    
    assert duplicate is not None
    assert duplicate.cluster_key == "test_cluster_123"


def test_check_for_duplicates_far_cluster(session):
    """Test duplicate detection when cluster is far away."""
    # Create a cluster far away
    cluster = FireCluster(
        cluster_key="test_cluster_456",
        latitude=50.0,  # Far from 41.0
        longitude=35.0,  # Far from 28.0
        observation_count=5,
        first_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
        last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(cluster)
    session.flush()
    
    # Check for duplicates at a different location
    duplicate = check_for_duplicates(session, 41.0, 28.0)
    
    assert duplicate is None


def test_create_manual_fire_event_basic(session):
    """Test basic manual fire event creation."""
    event = create_manual_fire_event(
        session,
        name="Test Fire",
        latitude=41.0,
        longitude=28.0,
        min_lat=40.9,
        max_lat=41.1,
        min_lon=27.9,
        max_lon=28.1,
        geometry_wkt="POINT(28.0 41.0)",
        severity="medium",
        status="active",
        check_duplicates=False,
    )
    
    assert event is not None
    assert event.name == "Test Fire"
    assert event.latitude == 41.0
    assert event.longitude == 28.0
    assert event.source == "manual"
    assert event.severity == "medium"
    assert event.status == "active"
    assert event.event_key.startswith("manual_")


def test_create_manual_fire_event_with_notes(session):
    """Test manual fire event creation with notes and reporter info."""
    event = create_manual_fire_event(
        session,
        name="Reported Fire",
        latitude=41.0,
        longitude=28.0,
        min_lat=40.9,
        max_lat=41.1,
        min_lon=27.9,
        max_lon=28.1,
        geometry_wkt="POINT(28.0 41.0)",
        notes="Smoke visible from highway",
        reported_by="Operator John",
        check_duplicates=False,
    )
    
    assert event is not None
    assert event.notes == "Smoke visible from highway"
    assert event.reported_by == "Operator John"
    assert event.reported_at is not None


def test_create_manual_fire_event_duplicate_detection(session):
    """Test that duplicate detection raises an error."""
    # Create a nearby cluster
    cluster = FireCluster(
        cluster_key="test_cluster_duplicate",
        latitude=41.0,
        longitude=28.0,
        observation_count=5,
        first_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
        last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(cluster)
    session.flush()
    
    # Try to create manual event at same location with duplicate checking
    with pytest.raises(DuplicateFireEventError) as exc_info:
        create_manual_fire_event(
            session,
            name="Duplicate Fire",
            latitude=41.0,
            longitude=28.0,
            min_lat=40.9,
            max_lat=41.1,
            min_lon=27.9,
            max_lon=28.1,
            geometry_wkt="POINT(28.0 41.0)",
            check_duplicates=True,
        )
    
    assert "duplicates satellite detection" in str(exc_info.value)


def test_create_manual_fire_event_skip_duplicate_check(session):
    """Test that skipping duplicate check allows creation."""
    # Create a nearby cluster
    cluster = FireCluster(
        cluster_key="test_cluster_skip",
        latitude=41.0,
        longitude=28.0,
        observation_count=5,
        first_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
        last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(cluster)
    session.flush()
    
    # Create manual event with duplicate checking disabled
    event = create_manual_fire_event(
        session,
        name="Allowed Duplicate",
        latitude=41.0,
        longitude=28.0,
        min_lat=40.9,
        max_lat=41.1,
        min_lon=27.9,
        max_lon=28.1,
        geometry_wkt="POINT(28.0 41.0)",
        check_duplicates=False,
    )
    
    assert event is not None
    assert event.name == "Allowed Duplicate"


def test_trigger_prediction_for_event(session):
    """Test prediction triggering for an event."""
    event = FireEvent(
        event_key="test_event_pred",
        name="Test Event",
        latitude=41.0,
        longitude=28.0,
        min_lat=40.9,
        max_lat=41.1,
        min_lon=27.9,
        max_lon=28.1,
        geometry_wkt="POINT(28.0 41.0)",
        severity="medium",
        status="active",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(event)
    session.flush()
    
    result = trigger_prediction_for_event(session, event)
    
    assert result["status"] == "triggered"
    assert result["event_key"] == "test_event_pred"
    assert result["model_name"] == "default"
    assert "message" in result


def test_api_create_manual_event(client):
    """Test API endpoint for creating manual fire event."""
    response = client.post(
        "/api/v1/events/manual",
        json={
            "name": "API Test Fire",
            "latitude": 41.0,
            "longitude": 28.0,
            "min_lat": 40.9,
            "max_lat": 41.1,
            "min_lon": 27.9,
            "max_lon": 28.1,
            "geometry_wkt": "POINT(28.0 41.0)",
            "severity": "high",
            "notes": "Test via API",
            "reported_by": "Test Operator",
            "check_duplicates": False,
            "trigger_prediction": False,
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "created"
    assert data["event"]["name"] == "API Test Fire"
    assert data["event"]["source"] == "manual"
    assert data["event"]["notes"] == "Test via API"
    assert data["event"]["reported_by"] == "Test Operator"


def test_api_create_manual_event_with_prediction(client):
    """Test API endpoint with prediction triggering."""
    response = client.post(
        "/api/v1/events/manual",
        json={
            "name": "Prediction Test Fire",
            "latitude": 41.5,
            "longitude": 28.5,
            "min_lat": 41.4,
            "max_lat": 41.6,
            "min_lon": 28.4,
            "max_lon": 28.6,
            "geometry_wkt": "POINT(28.5 41.5)",
            "check_duplicates": False,
            "trigger_prediction": True,
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "created"
    assert data["prediction_triggered"] is not None
    assert data["prediction_triggered"]["status"] == "triggered"


def test_api_create_manual_event_duplicate_error(client, session):
    """Test API endpoint with duplicate detection error."""
    # Create a nearby cluster
    cluster = FireCluster(
        cluster_key="api_test_cluster",
        latitude=41.0,
        longitude=28.0,
        observation_count=5,
        first_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
        last_seen_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    session.add(cluster)
    session.flush()
    
    response = client.post(
        "/api/v1/events/manual",
        json={
            "name": "Duplicate Test Fire",
            "latitude": 41.0,
            "longitude": 28.0,
            "min_lat": 40.9,
            "max_lat": 41.1,
            "min_lon": 27.9,
            "max_lon": 28.1,
            "geometry_wkt": "POINT(28.0 41.0)",
            "check_duplicates": True,
        },
    )
    
    assert response.status_code == 409
    data = response.json()
    assert data["detail"]["status"] == "duplicate"
    assert "duplicates satellite detection" in data["detail"]["error"]


def test_api_get_event(client, session):
    """Test API endpoint for getting a single event."""
    # Create an event first
    event = FireEvent(
        event_key="get_test_event",
        name="Get Test Event",
        latitude=41.0,
        longitude=28.0,
        min_lat=40.9,
        max_lat=41.1,
        min_lon=27.9,
        max_lon=28.1,
        geometry_wkt="POINT(28.0 41.0)",
        severity="medium",
        status="active",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
        source="manual",
    )
    session.add(event)
    session.flush()
    
    response = client.get("/api/v1/events/get_test_event")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["event"]["event_key"] == "get_test_event"
    assert data["event"]["name"] == "Get Test Event"


def test_api_get_event_not_found(client):
    """Test API endpoint for non-existent event."""
    response = client.get("/api/v1/events/nonexistent_event")
    
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["status"] == "not_found"


def test_api_update_event(client, session):
    """Test API endpoint for updating an event."""
    # Create an event first
    event = FireEvent(
        event_key="update_test_event",
        name="Original Name",
        latitude=41.0,
        longitude=28.0,
        min_lat=40.9,
        max_lat=41.1,
        min_lon=27.9,
        max_lon=28.1,
        geometry_wkt="POINT(28.0 41.0)",
        severity="medium",
        status="active",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
        source="manual",
    )
    session.add(event)
    session.flush()
    
    response = client.put(
        "/api/v1/events/update_test_event",
        json={
            "name": "Updated Name",
            "severity": "high",
            "notes": "Updated notes",
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "updated"
    assert data["event"]["name"] == "Updated Name"
    assert data["event"]["severity"] == "high"
    assert data["event"]["notes"] == "Updated notes"


def test_api_update_event_not_found(client):
    """Test API endpoint for updating non-existent event."""
    response = client.put(
        "/api/v1/events/nonexistent_event",
        json={"name": "Updated Name"},
    )
    
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["status"] == "not_found"


def test_api_delete_event(client, session):
    """Test API endpoint for deleting an event."""
    # Create an event first
    event = FireEvent(
        event_key="delete_test_event",
        name="Delete Test Event",
        latitude=41.0,
        longitude=28.0,
        min_lat=40.9,
        max_lat=41.1,
        min_lon=27.9,
        max_lon=28.1,
        geometry_wkt="POINT(28.0 41.0)",
        severity="medium",
        status="active",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
        source="manual",
    )
    session.add(event)
    session.flush()
    
    response = client.delete("/api/v1/events/delete_test_event")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "deleted"
    assert data["event_key"] == "delete_test_event"
    
    # Verify it's deleted
    get_response = client.get("/api/v1/events/delete_test_event")
    assert get_response.status_code == 404


def test_api_delete_event_not_found(client):
    """Test API endpoint for deleting non-existent event."""
    response = client.delete("/api/v1/events/nonexistent_event")
    
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["status"] == "not_found"


def test_api_get_events_by_source(client, session):
    """Test filtering events by source."""
    # Create manual event
    manual_event = FireEvent(
        event_key="manual_filter_test",
        name="Manual Event",
        latitude=41.0,
        longitude=28.0,
        min_lat=40.9,
        max_lat=41.1,
        min_lon=27.9,
        max_lon=28.1,
        geometry_wkt="POINT(28.0 41.0)",
        severity="medium",
        status="active",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
        source="manual",
    )
    session.add(manual_event)
    
    # Create satellite event
    satellite_event = FireEvent(
        event_key="satellite_filter_test",
        name="Satellite Event",
        latitude=41.5,
        longitude=28.5,
        min_lat=41.4,
        max_lat=41.6,
        min_lon=28.4,
        max_lon=28.6,
        geometry_wkt="POINT(28.5 41.5)",
        severity="medium",
        status="active",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
        source="satellite",
    )
    session.add(satellite_event)
    session.flush()
    
    # Get only manual events
    response = client.get("/api/v1/spatial/events?source=manual")
    
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["events"][0]["source"] == "manual"
