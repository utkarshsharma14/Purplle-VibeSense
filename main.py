import threading
import os
import time
import uuid
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import uvicorn

from event_store import events_db
from core_ai import StoreMonitor
from vibe_engine import store_metrics
from models import Event

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}'
)
logger = logging.getLogger("vibesense")
_start_time = time.time()

# ── App ───────────────────────────────────────────────────────────────
app = FastAPI(title="VibeSense AI — Retail Intelligence API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="."), name="static")

# FIX: seen_events properly defined (was missing — caused NameError)
seen_events: set = set()

# ── Request logging middleware ────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    trace_id = str(uuid.uuid4())[:8]
    t0 = time.time()
    response = await call_next(request)
    latency = round((time.time() - t0) * 1000, 2)
    logger.info(
        f"trace_id={trace_id} method={request.method} path={request.url.path} "
        f"status={response.status_code} latency_ms={latency}"
    )
    return response

# ── AI Pipeline ───────────────────────────────────────────────────────
def run_ai_pipeline():
    try:
        monitor = StoreMonitor("store.mp4")
        monitor.start_monitoring()
    except Exception as e:
        logger.error(f"pipeline_error: {e}")

@app.on_event("startup")
def startup_event():
    threading.Thread(target=run_ai_pipeline, daemon=True).start()
    logger.info("VibeSense AI started")

# ── Dashboard ─────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def read_root():
    file_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    with open(file_path, "r") as f:
        return HTMLResponse(content=f.read())

# ── Legacy vibe endpoint (dashboard compatibility) ────────────────────
@app.get("/api/v1/store/vibe")
def get_store_vibe():
    return {
        "current_occupancy": store_metrics["current_count"],
        "store_vibe":        store_metrics["vibe"],
        "ambient_music":     store_metrics["ambient_music"],
        "realtime_alerts":   store_metrics["realtime_alerts"][-5:],
    }

# ── POST /events/ingest ───────────────────────────────────────────────
@app.post("/events/ingest")
def ingest_events(events: list[Event]):
    """
    Idempotent by event_id. Partial success on malformed events.
    Safe to call twice with same payload.
    """
    inserted  = 0
    duplicate = 0
    errors    = []
    for event in events:
        try:
            if event.event_id in seen_events:
                duplicate += 1
                continue
            seen_events.add(event.event_id)
            events_db.append(event.model_dump())
            inserted += 1
        except Exception as e:
            errors.append({"event_id": getattr(event, "event_id", "?"), "error": str(e)})
    logger.info(f"ingest inserted={inserted} duplicates={duplicate} errors={len(errors)}")
    return {
        "status":       "success",
        "inserted":     inserted,
        "duplicates":   duplicate,
        "errors":       errors,
        "total_events": len(events_db),
    }

# ── GET /health ───────────────────────────────────────────────────────
@app.get("/health")
def health():
    """
    STALE_FEED if no events in last 10 min.
    What an on-call engineer checks first.
    """
    now = datetime.now(timezone.utc)
    feed_status = "NO_DATA"
    last_event_at = None

    if events_db:
        try:
            timestamps = [e.get("timestamp") for e in events_db if e.get("timestamp")]
            if timestamps:
                last_event_at = max(timestamps)
                last_dt = datetime.fromisoformat(str(last_event_at).replace("Z", "+00:00"))
                lag_sec = (now - last_dt).total_seconds()
                feed_status = "STALE_FEED" if lag_sec > 600 else "LIVE"
        except Exception:
            feed_status = "UNKNOWN"

    return {
        "status":            "healthy",
        "service":           "VibeSense AI",
        "uptime_seconds":    round(time.time() - _start_time, 2),
        "current_occupancy": store_metrics["current_count"],
        "store_vibe":        store_metrics["vibe"],
        "alerts_count":      len(store_metrics["realtime_alerts"]),
        "total_events":      len(events_db),
        "feed_status":       feed_status,
        "last_event_at":     str(last_event_at) if last_event_at else None,
        "last_inference":    store_metrics["system_telemetry"]["last_inference_timestamp"],
        "anomaly":           store_metrics["system_telemetry"]["anomaly_flag"],
    }

# ── GET /stores/{store_id}/metrics ────────────────────────────────────
@app.get("/stores/{store_id}/metrics")
def get_store_metrics(store_id: str):
    """
    Real-time: unique visitors, conversion rate, avg dwell per zone.
    Excludes is_staff=True. Handles zero-traffic.
    """
    evts = [e for e in events_db if e.get("store_id") == store_id and not e.get("is_staff", False)]

    unique_visitors = len({e["visitor_id"] for e in evts if e.get("event_type") == "ENTRY"})
    entries  = len([e for e in evts if e.get("event_type") == "ENTRY"])
    exits    = len([e for e in evts if e.get("event_type") == "EXIT"])

    # Zone dwell
    zone_dwell: dict = defaultdict(list)
    for e in evts:
        if e.get("event_type") == "ZONE_DWELL" and e.get("zone_id") and e.get("dwell_ms", 0) > 0:
            zone_dwell[e["zone_id"]].append(e["dwell_ms"] / 1000)

    avg_dwell_per_zone = [
        {"zone_id": z, "avg_dwell_sec": round(sum(v)/len(v), 2), "visit_count": len(v)}
        for z, v in zone_dwell.items()
    ]

    # Conversion rate
    billing_vis = {
        e["visitor_id"] for e in evts
        if e.get("event_type") == "BILLING_QUEUE_JOIN"
        or "BILLING" in (e.get("zone_id") or "").upper()
    }
    conversion_rate = round(len(billing_vis) / unique_visitors, 4) if unique_visitors > 0 else 0.0

    # Queue depth (last 5 min)
    recent = [e for e in evts if _within_minutes(e.get("timestamp"), 5)]
    queue_depth = max(0,
        sum(1 for e in recent if e.get("event_type") == "BILLING_QUEUE_JOIN") -
        sum(1 for e in recent if e.get("event_type") == "BILLING_QUEUE_ABANDON")
    )

    abandon = len([e for e in evts if e.get("event_type") == "BILLING_QUEUE_ABANDON"])
    abandonment_rate = round(abandon / len(billing_vis), 4) if billing_vis else 0.0

    data_confidence = "HIGH" if unique_visitors >= 50 else "MEDIUM" if unique_visitors >= 20 else "LOW"

    return {
        "store_id":           store_id,
        "unique_visitors":    unique_visitors,
        "entries":            entries,
        "exits":              exits,
        "conversion_rate":    conversion_rate,
        "avg_dwell_per_zone": avg_dwell_per_zone,
        "queue_depth":        queue_depth,
        "abandonment_rate":   abandonment_rate,
        "current_occupancy":  store_metrics["current_count"],
        "store_vibe":         store_metrics["vibe"],
        "data_confidence":    data_confidence,
    }

# ── GET /stores/{store_id}/funnel ─────────────────────────────────────
@app.get("/stores/{store_id}/funnel")
def get_funnel(store_id: str):
    """
    Session-level funnel. Re-entries don't double-count.
    Entry → Zone Visit → Billing Queue → Purchase
    """
    evts = [e for e in events_db if e.get("store_id") == store_id and not e.get("is_staff", False)]

    sessions: dict = {}
    for e in sorted(evts, key=lambda x: str(x.get("timestamp", ""))):
        vid = e.get("visitor_id")
        if not vid:
            continue
        if vid not in sessions:
            sessions[vid] = {"entered": False, "visited_zone": False, "reached_billing": False}
        s  = sessions[vid]
        et = e.get("event_type", "")
        if et == "ENTRY":
            s["entered"] = True
        elif et == "REENTRY":
            pass  # same session, not new visitor
        elif et in ("ZONE_ENTER", "ZONE_DWELL") and e.get("zone_id"):
            s["visited_zone"] = True
        elif et == "BILLING_QUEUE_JOIN":
            s["reached_billing"] = True

    abandon_ids = {e["visitor_id"] for e in evts if e.get("event_type") == "BILLING_QUEUE_ABANDON"}

    entered   = sum(1 for s in sessions.values() if s["entered"])
    visited   = sum(1 for s in sessions.values() if s["entered"] and s["visited_zone"])
    billing   = sum(1 for s in sessions.values() if s["reached_billing"])
    purchased = sum(1 for vid, s in sessions.items() if s["reached_billing"] and vid not in abandon_ids)

    def drop(cur, prev): return round((1 - cur/prev)*100, 1) if prev > 0 else 0.0

    return {
        "store_id": store_id,
        "stages": [
            {"stage": "ENTRY",         "count": entered,   "dropoff_pct": drop(entered, len(sessions))},
            {"stage": "ZONE_VISIT",    "count": visited,   "dropoff_pct": drop(visited, entered)},
            {"stage": "BILLING_QUEUE", "count": billing,   "dropoff_pct": drop(billing, visited)},
            {"stage": "PURCHASE",      "count": purchased, "dropoff_pct": drop(purchased, billing)},
        ]
    }

# ── GET /stores/{store_id}/heatmap ────────────────────────────────────
@app.get("/stores/{store_id}/heatmap")
def get_heatmap(store_id: str):
    """
    Zone visit frequency + avg dwell, normalised 0-100.
    data_confidence=LOW if fewer than 20 sessions.
    """
    evts = [e for e in events_db if e.get("store_id") == store_id and not e.get("is_staff", False)]

    zone_visits: dict = defaultdict(int)
    zone_dwell:  dict = defaultdict(list)
    for e in evts:
        z = e.get("zone_id")
        if not z:
            continue
        if e.get("event_type") == "ZONE_ENTER":
            zone_visits[z] += 1
        if e.get("dwell_ms", 0) > 0:
            zone_dwell[z].append(e["dwell_ms"] / 1000)

    max_v = max(zone_visits.values()) if zone_visits else 1
    unique_sessions = len({e.get("visitor_id") for e in evts if e.get("visitor_id")})

    zones = []
    for z, visits in zone_visits.items():
        d = zone_dwell.get(z, [])
        zones.append({
            "zone_id":          z,
            "visit_frequency":  visits,
            "avg_dwell_sec":    round(sum(d)/len(d), 2) if d else 0.0,
            "normalised_score": round(visits / max_v * 100, 1),
            "data_confidence":  "LOW" if unique_sessions < 20 else "HIGH",
        })
    zones.sort(key=lambda z: z["normalised_score"], reverse=True)
    return {"store_id": store_id, "zones": zones, "generated_at": datetime.now(timezone.utc).isoformat()}

# ── GET /stores/{store_id}/anomalies ──────────────────────────────────
@app.get("/stores/{store_id}/anomalies")
def get_anomalies(store_id: str):
    """
    Active anomalies: QUEUE_SPIKE, CONVERSION_DROP, DEAD_ZONE, CAPACITY_EXCEEDED.
    Each with severity + suggested_action.
    """
    now  = datetime.now(timezone.utc)
    evts = [e for e in events_db if e.get("store_id") == store_id and not e.get("is_staff", False)]
    anomalies = []

    # Queue spike
    recent = [e for e in evts if _within_minutes(e.get("timestamp"), 5)]
    queue  = max(0,
        sum(1 for e in recent if e.get("event_type") == "BILLING_QUEUE_JOIN") -
        sum(1 for e in recent if e.get("event_type") == "BILLING_QUEUE_ABANDON")
    )
    if queue >= 5:
        anomalies.append({
            "anomaly_type": "BILLING_QUEUE_SPIKE",
            "severity": "CRITICAL" if queue >= 8 else "WARN",
            "description": f"Billing queue depth is {queue}.",
            "suggested_action": "Open additional counter immediately.",
            "zone_id": "BILLING", "value": queue,
        })

    # Conversion drop
    entries_set = {e["visitor_id"] for e in evts if e.get("event_type") == "ENTRY"}
    billing_set = {e["visitor_id"] for e in evts if e.get("event_type") == "BILLING_QUEUE_JOIN"}
    if len(entries_set) >= 10:
        conv = len(billing_set) / len(entries_set)
        if conv < 0.25:
            anomalies.append({
                "anomaly_type": "CONVERSION_DROP",
                "severity": "WARN",
                "description": f"Conversion {conv:.1%} below 25% baseline. {len(entries_set)} visitors, {len(billing_set)} reached billing.",
                "suggested_action": "Deploy floor staff to guide customers to billing.",
                "value": round(conv, 4),
            })

    # Dead zones (no visits in 30 min)
    active_zones = {e.get("zone_id") for e in evts if e.get("zone_id") and _within_minutes(e.get("timestamp"), 30)}
    all_zones    = {e.get("zone_id") for e in evts if e.get("zone_id")}
    for z in (all_zones - active_zones):
        anomalies.append({
            "anomaly_type": "DEAD_ZONE",
            "severity": "INFO",
            "description": f"Zone '{z}' has had no customer visits in 30 min.",
            "suggested_action": f"Check merchandising in {z}.",
            "zone_id": z,
        })

    # Capacity exceeded (from live pipeline)
    if store_metrics["system_telemetry"]["anomaly_flag"]:
        anomalies.append({
            "anomaly_type": "CAPACITY_EXCEEDED",
            "severity": "CRITICAL",
            "description": "Store capacity threshold exceeded.",
            "suggested_action": "Redirect customers and increase floor staff.",
        })

    return {
        "store_id":         store_id,
        "active_anomalies": anomalies,
        "checked_at":       now.isoformat(),
    }

# ── GET /stores/{store_id}/events ─────────────────────────────────────
@app.get("/stores/{store_id}/events")
def get_events(store_id: str, limit: int = 50):
    evts = [e for e in events_db if e.get("store_id") == store_id]
    return {"store_id": store_id, "total_events": len(evts), "events": evts[-limit:]}

# ── GET /stores/{store_id}/zones ──────────────────────────────────────
@app.get("/stores/{store_id}/zones")
def get_zones(store_id: str):
    evts = [e for e in events_db if e.get("store_id") == store_id and not e.get("is_staff", False)]
    zone_data: dict = defaultdict(lambda: {"occupancy": 0, "dwell_times": []})
    for e in evts:
        z = e.get("zone_id")
        if not z:
            continue
        if e.get("event_type") == "ZONE_ENTER":
            zone_data[z]["occupancy"] += 1
        if e.get("dwell_ms", 0) > 0:
            zone_data[z]["dwell_times"].append(e["dwell_ms"] / 1000)
    zones = []
    for z, d in zone_data.items():
        dt = d["dwell_times"]
        zones.append({"zone": z, "occupancy": d["occupancy"],
                      "avg_dwell_seconds": round(sum(dt)/len(dt), 2) if dt else 0.0})
    return {"store_id": store_id, "zones": zones}

# ── AI Insights ───────────────────────────────────────────────────────
class InsightRequest(BaseModel):
    count:         int
    vibe:          str
    music:         str
    alerts:        List[str] = []
    avg_occupancy: int       = 0
    dominant_vibe: str       = ""
    timestamp:     str       = ""

@app.post("/api/v1/ai/insights")
def get_ai_insights(req: InsightRequest):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""You are VibeSense AI, a retail analytics assistant for a Purplle beauty store.
CURRENT DATA: Occupancy={req.count}, Vibe={req.vibe}, Music={req.music},
Alerts={', '.join(req.alerts) or 'None'}, AvgOccupancy={req.avg_occupancy}, Time={req.timestamp}
Provide: 1.**Situation Summary** 2.**Staff Recommendation** 3.**Revenue Opportunity** 4.**Music & Ambiance** 5.**30-Min Forecast**
Be specific, reference numbers."""
        msg = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=800,
                                     messages=[{"role": "user", "content": prompt}])
        return {"insight": msg.content[0].text}
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI error: {str(e)}")

# ── Helper ────────────────────────────────────────────────────────────
def _within_minutes(ts, minutes: int) -> bool:
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() < minutes * 60
    except Exception:
        return False

# ── Entry Point ───────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)