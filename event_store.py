from datetime import datetime
from uuid import uuid4

events_db = []


def add_event(
    store_id,
    visitor_id,
    event_type,
    zone_id=None,
    dwell_ms=0
):
    event = {
        "event_id": str(uuid4()),
        "store_id": store_id,
        "camera_id": "CAM_01",
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": False,
        "confidence": 0.95
    }

    events_db.append(event)

    print(f"EVENT CREATED: {event_type}")
    print(f"TOTAL EVENTS: {len(events_db)}")

    return event