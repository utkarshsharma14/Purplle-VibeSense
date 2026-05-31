import pytest
import uuid
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from main import app, seen_events
from event_store import events_db

client = TestClient(app)

STORE_ID = "STORE_TEST_001"


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_state():
    """
    Clear event store and dedup set before each test.
    Both objects are module-level references, so .clear() propagates
    into main.py without re-import.
    """
    events_db.clear()
    seen_events.clear()
    yield
    events_db.clear()
    seen_events.clear()


def make_event(**overrides):
    """Helper to build a minimal valid event dict."""
    base = {
        "event_id":   str(uuid.uuid4()),
        "store_id":   STORE_ID,
        "camera_id":  "CAM_ENTRY_01",
        "visitor_id": f"VIS_{uuid.uuid4().hex[:6]}",
        "event_type": "ENTRY",
        "timestamp":  datetime.now(timezone.utc).isoformat(),  # always tz-aware
        "zone_id":    None,
        "dwell_ms":   0,
        "is_staff":   False,
        "confidence": 0.91,
        "metadata":   {}
    }
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════════════
# PART 1 — Core Endpoints
# ══════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_health_returns_200(self):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_response_shape(self):
        r = client.get("/health")
        data = r.json()
        assert "status" in data
        assert "uptime_seconds" in data
        assert "total_events" in data
        assert "feed_status" in data

    def test_health_no_data_feed_status(self):
        """No events ingested → feed_status should be NO_DATA"""
        r = client.get("/health")
        assert r.json()["feed_status"] == "NO_DATA"

    def test_health_after_ingest_feed_live(self):
        """After ingesting a fresh event → feed_status should be LIVE"""
        event = make_event()
        client.post("/events/ingest", json=[event])
        r = client.get("/health")
        assert r.json()["feed_status"] == "LIVE"


class TestStoreVibe:
    def test_vibe_returns_200(self):
        r = client.get("/api/v1/store/vibe")
        assert r.status_code == 200

    def test_vibe_response_fields(self):
        r = client.get("/api/v1/store/vibe")
        data = r.json()
        assert "current_occupancy" in data
        assert "store_vibe" in data
        assert "ambient_music" in data
        assert "realtime_alerts" in data
        assert isinstance(data["realtime_alerts"], list)


# ══════════════════════════════════════════════════════════════════════
# PART 2 — Event Ingest + Idempotency
# ══════════════════════════════════════════════════════════════════════

class TestIngest:
    def test_ingest_single_event(self):
        event = make_event()
        r = client.post("/events/ingest", json=[event])
        assert r.status_code == 200
        data = r.json()
        assert data["inserted"] == 1
        assert data["duplicates"] == 0

    def test_ingest_batch(self):
        events = [make_event() for _ in range(5)]
        r = client.post("/events/ingest", json=events)
        assert r.status_code == 200
        assert r.json()["inserted"] == 5

    def test_ingest_idempotency(self):
        """
        Same payload sent twice → second call returns 0 inserted, 1 duplicate.
        Critical for production safety.
        """
        event = make_event()
        r1 = client.post("/events/ingest", json=[event])
        r2 = client.post("/events/ingest", json=[event])
        assert r1.json()["inserted"] == 1
        assert r2.json()["inserted"] == 0
        assert r2.json()["duplicates"] == 1

    def test_ingest_partial_success(self):
        """All valid events should be accepted with empty errors list."""
        events = [make_event() for _ in range(3)]
        r = client.post("/events/ingest", json=events)
        assert r.json()["inserted"] == 3
        assert r.json()["errors"] == []

    def test_ingest_total_events_accumulates(self):
        e1 = make_event()
        e2 = make_event()
        client.post("/events/ingest", json=[e1])
        client.post("/events/ingest", json=[e2])
        r = client.post("/events/ingest", json=[make_event()])
        assert r.json()["total_events"] == 3


# ══════════════════════════════════════════════════════════════════════
# PART 3 — Metrics Edge Cases
# ══════════════════════════════════════════════════════════════════════

class TestMetrics:
    def test_metrics_empty_store(self):
        """Zero traffic — must return valid response, not crash or return null."""
        r = client.get(f"/stores/{STORE_ID}/metrics")
        assert r.status_code == 200
        data = r.json()
        assert data["unique_visitors"] == 0
        assert data["conversion_rate"] == 0.0
        assert data["queue_depth"] == 0

    def test_metrics_with_entries(self):
        visitors = [make_event(visitor_id=f"VIS_{i:04d}") for i in range(10)]
        client.post("/events/ingest", json=visitors)
        r = client.get(f"/stores/{STORE_ID}/metrics")
        data = r.json()
        assert data["unique_visitors"] == 10
        assert data["entries"] == 10

    def test_metrics_excludes_staff(self):
        """
        All-staff events — unique_visitors must be 0.
        is_staff=True must never count as customers.
        """
        staff_events = [
            make_event(is_staff=True, visitor_id=f"STAFF_{i}") for i in range(5)
        ]
        client.post("/events/ingest", json=staff_events)
        r = client.get(f"/stores/{STORE_ID}/metrics")
        assert r.json()["unique_visitors"] == 0

    def test_metrics_conversion_rate_zero_purchases(self):
        """Visitors enter but nobody reaches billing → conversion_rate = 0.0"""
        entries = [make_event(visitor_id=f"VIS_{i}") for i in range(10)]
        client.post("/events/ingest", json=entries)
        r = client.get(f"/stores/{STORE_ID}/metrics")
        assert r.json()["conversion_rate"] == 0.0

    def test_metrics_with_zone_dwell(self):
        vid = "VIS_abc123"
        events = [
            make_event(visitor_id=vid, event_type="ENTRY"),
            make_event(
                visitor_id=vid,
                event_type="ZONE_DWELL",
                zone_id="COSMETICS",
                dwell_ms=90000,
            ),
        ]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/metrics")
        zones = r.json()["avg_dwell_per_zone"]
        assert any(z["zone_id"] == "COSMETICS" for z in zones)
        cosmetics = next(z for z in zones if z["zone_id"] == "COSMETICS")
        assert cosmetics["avg_dwell_sec"] == 90.0   # 90000ms → 90s

    def test_metrics_data_confidence_low(self):
        """Fewer than 20 visitors → LOW confidence"""
        events = [make_event(visitor_id=f"VIS_{i}") for i in range(5)]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/metrics")
        assert r.json()["data_confidence"] == "LOW"

    def test_metrics_different_stores_isolated(self):
        """Events for STORE_A must not appear in STORE_B metrics."""
        event = make_event(store_id="STORE_A", visitor_id="VIS_x1")
        client.post("/events/ingest", json=[event])
        r = client.get("/stores/STORE_B/metrics")
        assert r.json()["unique_visitors"] == 0


# ══════════════════════════════════════════════════════════════════════
# PART 4 — Funnel + Re-entry Deduplication
# ══════════════════════════════════════════════════════════════════════

class TestFunnel:
    def test_funnel_empty_store(self):
        r = client.get(f"/stores/{STORE_ID}/funnel")
        assert r.status_code == 200
        data = r.json()
        assert "stages" in data
        assert all(s["count"] == 0 for s in data["stages"])

    def test_funnel_stage_order(self):
        r = client.get(f"/stores/{STORE_ID}/funnel")
        stages = [s["stage"] for s in r.json()["stages"]]
        assert stages == ["ENTRY", "ZONE_VISIT", "BILLING_QUEUE", "PURCHASE"]

    def test_funnel_reentry_does_not_double_count(self):
        """
        Same visitor_id with REENTRY must not inflate ENTRY count.
        ENTRY count must be 1, not 2.
        """
        vid = "VIS_reentry01"
        events = [
            make_event(visitor_id=vid, event_type="ENTRY"),
            make_event(visitor_id=vid, event_type="EXIT"),
            make_event(visitor_id=vid, event_type="REENTRY"),
        ]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/funnel")
        entry_stage = next(s for s in r.json()["stages"] if s["stage"] == "ENTRY")
        assert entry_stage["count"] == 1

    def test_funnel_full_journey(self):
        vid = "VIS_full01"
        events = [
            make_event(visitor_id=vid, event_type="ENTRY"),
            make_event(visitor_id=vid, event_type="ZONE_ENTER", zone_id="COSMETICS"),
            make_event(visitor_id=vid, event_type="BILLING_QUEUE_JOIN", zone_id="BILLING"),
        ]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/funnel")
        stages = {s["stage"]: s["count"] for s in r.json()["stages"]}
        assert stages["ENTRY"] == 1
        assert stages["ZONE_VISIT"] == 1
        assert stages["BILLING_QUEUE"] == 1

    def test_funnel_dropoff_never_negative(self):
        events = [make_event(visitor_id=f"VIS_{i}") for i in range(5)]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/funnel")
        for stage in r.json()["stages"]:
            assert stage["dropoff_pct"] >= 0.0


# ══════════════════════════════════════════════════════════════════════
# PART 5 — Heatmap
# ══════════════════════════════════════════════════════════════════════

class TestHeatmap:
    def test_heatmap_empty_store(self):
        r = client.get(f"/stores/{STORE_ID}/heatmap")
        assert r.status_code == 200
        assert r.json()["zones"] == []

    def test_heatmap_normalised_score_max_100(self):
        vid = "VIS_hmap01"
        events = [
            make_event(visitor_id=vid, event_type="ZONE_ENTER", zone_id="COSMETICS"),
            make_event(visitor_id=vid, event_type="ZONE_ENTER", zone_id="SKINCARE"),
            make_event(visitor_id=vid, event_type="ZONE_ENTER", zone_id="COSMETICS"),
        ]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/heatmap")
        zones = r.json()["zones"]
        scores = [z["normalised_score"] for z in zones]
        assert max(scores) == 100.0
        assert all(0 <= s <= 100 for s in scores)

    def test_heatmap_low_confidence_flag(self):
        """Fewer than 20 sessions → data_confidence LOW"""
        event = make_event(event_type="ZONE_ENTER", zone_id="COSMETICS")
        client.post("/events/ingest", json=[event])
        r = client.get(f"/stores/{STORE_ID}/heatmap")
        for z in r.json()["zones"]:
            assert z["data_confidence"] == "LOW"

    def test_heatmap_sorted_by_score(self):
        events = [
            make_event(event_type="ZONE_ENTER", zone_id="COSMETICS"),
            make_event(event_type="ZONE_ENTER", zone_id="COSMETICS"),
            make_event(event_type="ZONE_ENTER", zone_id="SKINCARE"),
        ]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/heatmap")
        scores = [z["normalised_score"] for z in r.json()["zones"]]
        assert scores == sorted(scores, reverse=True)


# ══════════════════════════════════════════════════════════════════════
# PART 6 — Anomaly Detection
# ══════════════════════════════════════════════════════════════════════

class TestAnomalies:
    def test_anomalies_empty_store(self):
        r = client.get(f"/stores/{STORE_ID}/anomalies")
        assert r.status_code == 200
        assert r.json()["active_anomalies"] == []

    def test_anomaly_response_shape(self):
        r = client.get(f"/stores/{STORE_ID}/anomalies")
        data = r.json()
        assert "store_id" in data
        assert "active_anomalies" in data
        assert "checked_at" in data

    def test_conversion_drop_anomaly(self):
        """10+ entries with no billing → CONVERSION_DROP anomaly raised."""
        events = [
            make_event(visitor_id=f"VIS_{i}", event_type="ENTRY")
            for i in range(12)
        ]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/anomalies")
        types = [a["anomaly_type"] for a in r.json()["active_anomalies"]]
        assert "CONVERSION_DROP" in types

    def test_dead_zone_anomaly(self):
        """Zone visited > 30 min ago → DEAD_ZONE anomaly raised."""
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        event = make_event(
            event_type="ZONE_ENTER",
            zone_id="HAIRCARE",
            timestamp=old_ts,
        )
        client.post("/events/ingest", json=[event])
        r = client.get(f"/stores/{STORE_ID}/anomalies")
        types = [a["anomaly_type"] for a in r.json()["active_anomalies"]]
        assert "DEAD_ZONE" in types

    def test_anomaly_has_suggested_action(self):
        """Every anomaly must include a non-empty suggested_action string."""
        events = [make_event(visitor_id=f"VIS_{i}") for i in range(12)]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/anomalies")
        for anomaly in r.json()["active_anomalies"]:
            assert "suggested_action" in anomaly
            assert len(anomaly["suggested_action"]) > 0

    def test_anomaly_severity_values(self):
        """Severity must be one of INFO / WARN / CRITICAL."""
        events = [make_event(visitor_id=f"VIS_{i}") for i in range(12)]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/anomalies")
        valid = {"INFO", "WARN", "CRITICAL"}
        for a in r.json()["active_anomalies"]:
            assert a["severity"] in valid


# ══════════════════════════════════════════════════════════════════════
# PART 7 — Store Events Endpoint
# ══════════════════════════════════════════════════════════════════════

class TestStoreEvents:
    def test_events_empty(self):
        r = client.get(f"/stores/{STORE_ID}/events")
        assert r.status_code == 200
        assert r.json()["total_events"] == 0
        assert r.json()["events"] == []

    def test_events_returns_ingested(self):
        event = make_event()
        client.post("/events/ingest", json=[event])
        r = client.get(f"/stores/{STORE_ID}/events")
        assert r.json()["total_events"] == 1

    def test_events_limit_param(self):
        events = [make_event() for _ in range(10)]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/events?limit=5")
        assert len(r.json()["events"]) <= 5


# ══════════════════════════════════════════════════════════════════════
# PART 8 — Zones Endpoint (NEW)
# ══════════════════════════════════════════════════════════════════════

class TestZones:
    def test_zones_empty(self):
        """No events → zones list must be empty, not a crash."""
        r = client.get(f"/stores/{STORE_ID}/zones")
        assert r.status_code == 200
        assert r.json()["zones"] == []

    def test_zones_returns_zone_data(self):
        event = make_event(event_type="ZONE_ENTER", zone_id="COSMETICS")
        client.post("/events/ingest", json=[event])
        r = client.get(f"/stores/{STORE_ID}/zones")
        zones = r.json()["zones"]
        assert any(z["zone"] == "COSMETICS" for z in zones)

    def test_zones_occupancy_count(self):
        """3 ZONE_ENTER events for COSMETICS → occupancy = 3."""
        events = [
            make_event(event_type="ZONE_ENTER", zone_id="COSMETICS")
            for _ in range(3)
        ]
        client.post("/events/ingest", json=events)
        r = client.get(f"/stores/{STORE_ID}/zones")
        cosmetics = next(z for z in r.json()["zones"] if z["zone"] == "COSMETICS")
        assert cosmetics["occupancy"] == 3

    def test_zones_excludes_staff(self):
        """Staff zone events must not appear in the zone report."""
        event = make_event(event_type="ZONE_ENTER", zone_id="STOCKROOM", is_staff=True)
        client.post("/events/ingest", json=[event])
        r = client.get(f"/stores/{STORE_ID}/zones")
        zone_names = [z["zone"] for z in r.json()["zones"]]
        assert "STOCKROOM" not in zone_names

    def test_zones_avg_dwell(self):
        """dwell_ms on zone event → avg_dwell_seconds correctly computed."""
        event = make_event(
            event_type="ZONE_ENTER",
            zone_id="SKINCARE",
            dwell_ms=60000,
        )
        client.post("/events/ingest", json=[event])
        r = client.get(f"/stores/{STORE_ID}/zones")
        skincare = next(z for z in r.json()["zones"] if z["zone"] == "SKINCARE")
        assert skincare["avg_dwell_seconds"] == 60.0


# ══════════════════════════════════════════════════════════════════════
# PART 9 — AI Insights Endpoint (NEW)
# ══════════════════════════════════════════════════════════════════════

class TestAIInsights:
    PAYLOAD = {
        "count": 10,
        "vibe": "Cozy",
        "music": "Jazz",
        "alerts": [],
        "avg_occupancy": 8,
        "dominant_vibe": "Cozy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    def test_insights_missing_api_key(self, monkeypatch):
        """No ANTHROPIC_API_KEY env var → 500 with clear error message."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        r = client.post("/api/v1/ai/insights", json=self.PAYLOAD)
        assert r.status_code == 500
        assert "ANTHROPIC_API_KEY" in r.json()["detail"]

    def test_insights_request_shape_validated(self):
        """Missing required fields → 422 Unprocessable Entity."""
        r = client.post("/api/v1/ai/insights", json={"count": 5})
        assert r.status_code == 422

    def test_insights_response_has_insight_key(self, monkeypatch):
        """
        With a valid API key, response must contain 'insight' key.
        Skipped automatically if ANTHROPIC_API_KEY is not set in environment.
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            pytest.skip("ANTHROPIC_API_KEY not set — skipping live AI test")
        r = client.post("/api/v1/ai/insights", json=self.PAYLOAD)
        assert r.status_code == 200
        assert "insight" in r.json()
        assert len(r.json()["insight"]) > 0