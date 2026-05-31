import threading
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import anthropic
import uvicorn

# Local modules
from core_ai import StoreMonitor
from vibe_engine import store_metrics
from models import Event

# ── App ──────────────────────────────────────────────────────────────
app = FastAPI(title="VibeSense AI — Retail Intelligence API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory="."), name="static")

# Anthropic client
ai_client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY")
)

# ── Event Storage ────────────────────────────────────────────────────

events_db = []
seen_events = set()

# ── AI Pipeline ──────────────────────────────────────────────────────

def run_ai_pipeline():
    monitor = StoreMonitor("store.mp4")
    monitor.start_monitoring()


@app.on_event("startup")
def startup_event():
    threading.Thread(
        target=run_ai_pipeline,
        daemon=True
    ).start()


# ── Routes ───────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def read_root():
    file_path = os.path.join(
        os.path.dirname(__file__),
        "templates",
        "index.html"
    )

    with open(file_path, "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/v1/store/vibe")
def get_store_vibe():
    return {
        "current_occupancy":
            store_metrics["current_count"],

        "store_vibe":
            store_metrics["vibe"],

        "ambient_music":
            store_metrics["ambient_music"],

        "realtime_alerts":
            store_metrics["realtime_alerts"][-5:]
    }


# ── Event Ingestion API ──────────────────────────────────────────────

@app.post("/events/ingest")
def ingest_events(events: list[Event]):

    inserted = 0

    for event in events:

        if event.event_id in seen_events:
            continue

        seen_events.add(event.event_id)

        events_db.append(
            event.model_dump()
        )

        inserted += 1

    return {
        "status": "success",
        "inserted": inserted,
        "total_events": len(events_db)
    }


# ── Health API ───────────────────────────────────────────────────────

@app.get("/health")
def health():

    return {
        "status": "healthy",

        "service":
            "VibeSense AI",

        "current_occupancy":
            store_metrics["current_count"],

        "store_vibe":
            store_metrics["vibe"],

        "alerts_count":
            len(store_metrics["realtime_alerts"]),

        "events_count":
            len(events_db),

        "last_inference":
            store_metrics["system_telemetry"]["last_inference_timestamp"],

        "anomaly":
            store_metrics["system_telemetry"]["anomaly_flag"]
    }


# ── AI Insights ──────────────────────────────────────────────────────

class InsightRequest(BaseModel):
    count: int
    vibe: str
    music: str
    alerts: List[str] = []
    avg_occupancy: int = 0
    dominant_vibe: str = ""
    timestamp: str = ""


@app.post("/api/v1/ai/insights")
def get_ai_insights(req: InsightRequest):

    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY not set"
        )

    prompt = f"""
You are VibeSense AI, an intelligent retail analytics assistant.

CURRENT STORE DATA:
- Live Occupancy: {req.count}
- Store Vibe: {req.vibe}
- Ambient Music: {req.music}
- Active Alerts: {', '.join(req.alerts) if req.alerts else 'None'}
- Session Avg Occupancy: {req.avg_occupancy}
- Dominant Vibe: {req.dominant_vibe or req.vibe}
- Time: {req.timestamp}

Provide:

1. Situation Summary
2. Staff Recommendation
3. Revenue Opportunity
4. Music & Ambiance
5. 30-Min Forecast
"""

    try:

        message = ai_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return {
            "insight":
                message.content[0].text
        }

    except anthropic.AuthenticationError:
        raise HTTPException(
            status_code=401,
            detail="Invalid API Key"
        )

    except anthropic.RateLimitError:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded"
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"AI service error: {str(e)}"
        )

@app.get("/stores/{store_id}/metrics")
def get_store_metrics(store_id: str):

    store_events = [
        e for e in events_db
        if e["store_id"] == store_id
    ]

    unique_visitors = len(
        set(e["visitor_id"] for e in store_events)
    )

    entry_events = [
        e for e in store_events
        if e["event_type"] == "ENTRY"
    ]

    exit_events = [
        e for e in store_events
        if e["event_type"] == "EXIT"
    ]

    zone_dwell_events = [
        e for e in store_events
        if e["event_type"] == "ZONE_DWELL"
    ]

    avg_dwell = 0

    if zone_dwell_events:
        avg_dwell = sum(
            e["dwell_ms"]
            for e in zone_dwell_events
        ) / len(zone_dwell_events)

    return {
        "store_id": store_id,
        "unique_visitors": unique_visitors,
        "entries": len(entry_events),
        "exits": len(exit_events),
        "avg_dwell_ms": avg_dwell,
        "current_occupancy": store_metrics["current_count"],
        "store_vibe": store_metrics["vibe"],
        "alerts": store_metrics["realtime_alerts"]
    }


@app.get("/stores/{store_id}/funnel")
def get_funnel(store_id: str):

    store_events = [
        e for e in events_db
        if e["store_id"] == store_id
    ]

    entries = len([
        e for e in store_events
        if e["event_type"] == "ENTRY"
    ])

    zone_visits = len([
        e for e in store_events
        if e["event_type"] == "ZONE_ENTER"
    ])

    return {
        "store_id": store_id,
        "entry": entries,
        "zone_visit": zone_visits,
        "billing": int(entries * 0.6),
        "purchase": int(entries * 0.4)
    }


@app.get("/stores/{store_id}/anomalies")
def get_anomalies(store_id: str):

    return {
        "store_id": store_id,
        "anomaly_detected":
            store_metrics["system_telemetry"]["anomaly_flag"],

        "alerts":
            store_metrics["realtime_alerts"],

        "severity":
            "HIGH"
            if store_metrics["system_telemetry"]["anomaly_flag"]
            else "NORMAL"
    }
# ── Entry Point ──────────────────────────────────────────────────────

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 10000)
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )