from datetime import datetime, timezone
from uuid import uuid4

# Single shared list — imported by reference in main.py and tests.
# Both callers get the same object, so .clear() in fixtures propagates correctly.
events_db: list = []


def add_event(
    store_id: str,
    visitor_id: str,
    event_type: str,
    zone_id: str | None = None,
    dwell_ms: int = 0,
    is_staff: bool = False,
    confidence: float = 0.95,
) -> dict:
    """
    Create a single event dict and append it to events_db.

    FIX: datetime.now(timezone.utc) instead of datetime.utcnow()
    so timestamps are always timezone-aware (+00:00).
    This prevents TypeError in _within_minutes() when comparing
    aware vs naive datetimes.
    """
    event = {
        "event_id":  str(uuid4()),
        "store_id":  store_id,
        "camera_id": "CAM_01",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp":  datetime.now(timezone.utc).isoformat(),   # ← fixed
        "zone_id":    zone_id,
        "dwell_ms":   dwell_ms,
        "is_staff":   is_staff,
        "confidence": confidence,
    }
    events_db.append(event)
    print(f"EVENT CREATED : {event_type}")
    print(f"TOTAL EVENTS  : {len(events_db)}")
    return event


def add_event_from_model(event_dict: dict) -> dict:
    """
    Append a pre-validated event dict (from Pydantic model_dump) to events_db.

    FIX: main.py's ingest endpoint now routes through here instead of calling
    events_db.append() directly, so there is a single ingest code path and no
    risk of divergence (e.g. missing fields, wrong timestamp format).
    """
    events_db.append(event_dict)
    return event_dict