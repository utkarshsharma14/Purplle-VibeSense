# DESIGN.md — VibeSense AI Architecture

## Overview

VibeSense AI is a real-time store intelligence system built for the Purplle Tech Challenge 2026.
It processes raw CCTV footage through a computer vision pipeline, emits structured behavioural
events, computes live retail analytics, and surfaces anomalies and AI-powered recommendations
through a REST API and live dashboard.

The system is designed around one north star metric: **offline store conversion rate** —
the ratio of unique visitors who completed a purchase to total unique visitors in a session window.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     store.mp4 / CCTV Feed                   │
└──────────────────────┬──────────────────────────────────────┘
                       │ Frame stream (OpenCV)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                core_ai.py — StoreMonitor                    │
│                                                             │
│   YOLOv8n detection (~28ms/frame)                           │
│   → ByteTrack re-ID + tracking                              │
│   → Zone mapper (entry/exit direction, zone assignment)     │
│   → Event emitter (ENTRY, EXIT, ZONE_ENTER, ZONE_DWELL...)  │
└──────────────────────┬──────────────────────────────────────┘
                       │ Structured events → events_db
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              event_store.py — In-Memory Event Store         │
│                                                             │
│   events_db: list — single shared reference                 │
│   add_event_from_model() — unified ingest path              │
│   Timezone-aware timestamps (datetime.now(timezone.utc))    │
└──────────────────────┬──────────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌─────────────────────┐   ┌─────────────────────────────────┐
│   vibe_engine.py    │   │         main.py — FastAPI       │
│                     │   │                                 │
│  store_metrics dict │   │  POST /events/ingest            │
│  Occupancy scoring  │   │  GET  /stores/{id}/metrics      │
│  Vibe classification│   │  GET  /stores/{id}/funnel       │
│  Music mapping      │   │  GET  /stores/{id}/heatmap      │
│  Alert generation   │   │  GET  /stores/{id}/anomalies    │
│  Anomaly flags      │   │  GET  /stores/{id}/zones        │
└─────────────────────┘   │  GET  /health                   │
                          │  POST /api/v1/ai/insights       │
                          └──────────────┬──────────────────┘
                                         │
                          ┌──────────────▼──────────────────┐
                          │  templates/index.html           │
                          │  Live dashboard — Chart.js CDN  │
                          │  KPIs, heatmap, alerts, export  │
                          └─────────────────────────────────┘
```

---

## Component Breakdown

### StoreMonitor (`core_ai.py`)

The detection pipeline runs as a **daemon thread** launched at startup. It reads frames from
`store.mp4` (or a live RTSP/webcam feed) using OpenCV, runs YOLOv8n inference, and passes
detections to ByteTrack for multi-object tracking with persistent visitor IDs.

Key decisions:
- **YOLOv8n** chosen over YOLOv8s for 40% lower latency at the cost of 7 mAP points.
  At 15fps retail CCTV, latency matters more than marginal accuracy gains.
- **ByteTrack** over DeepSORT — no separate Re-ID network needed, comparable accuracy,
  zero extra inference cost.
- **Daemon thread** design means the pipeline never blocks the FastAPI event loop.
  Trade-off: shared mutable state. Mitigation: `store_metrics` dict is read-heavy,
  written only by the pipeline thread.

### VibeEngine (`vibe_engine.py`)

Computes store vibe using a weighted rule-based formula:

```python
vibe_score = (
    occupancy_ratio  * 0.40 +   # How full is the store?
    zone_activity    * 0.35 +   # Which zones are active?
    dwell_time_score * 0.25     # Are customers lingering?
)
```

Vibe maps to ambient music with 30-second hysteresis to prevent boundary flickering.
No ML model used for vibe — deliberate choice explained in CHOICES.md.

### Event Store (`event_store.py`)

A module-level Python list (`events_db`) shared by reference between the detection pipeline
and the FastAPI handlers. Both import the same object, so mutations from one are immediately
visible to the other. The `add_event_from_model()` function provides a single ingest entry
point — the API endpoint routes through it rather than calling `events_db.append()` directly.

Critical fix applied during development: timestamps are generated with `datetime.now(timezone.utc)`
not `datetime.utcnow()`. The latter produces naive datetimes that cause `TypeError` when
compared against timezone-aware datetimes in `_within_minutes()`. This would have silently broken
all anomaly detection (dead zone, queue spike) without any visible error.

### Intelligence API (`main.py`)

FastAPI application with 10 endpoints. Key design patterns:

- **Idempotency**: `seen_events` set deduplicates by `event_id` before storing. Safe to call
  `POST /events/ingest` twice with the same payload.
- **Staff exclusion**: Every analytics query filters `not e.get("is_staff", False)` before
  computing metrics. Staff events are stored but never counted as customer visits.
- **Re-entry deduplication**: The funnel endpoint uses a session dict keyed by `visitor_id`.
  A `REENTRY` event hits a `pass` block — same session, not a new ENTRY count.
- **Store isolation**: All queries filter by `store_id` first. Events for STORE_A never
  appear in STORE_B metrics.
- **Zero-traffic safety**: All metric endpoints return valid zero-state (empty lists, 0 counts,
  0.0 rates) when no events exist. No null returns, no crashes.

### Live Dashboard (`templates/index.html`)

Single self-contained HTML file (~2000 lines). Chart.js via CDN. Polls the API every 3 seconds.
Features: KPI cards, occupancy trend chart, vibe history, zone heatmap, live alerts, multi-source
camera stream (webcam, MP4, IP cam, WebRTC), CSV/JSON/HTML export, push notification toggles.

---

## Data Flow — ENTRY to Conversion Rate

```
1. Frame arrives from store.mp4
2. YOLOv8n detects person bounding box
3. ByteTrack assigns persistent track_id → visitor_id = "VIS_{track_id}"
4. Zone mapper determines: is this the entry threshold? inbound direction?
5. ENTRY event emitted → events_db via add_event_from_model()
6. Visitor moves to COSMETICS zone → ZONE_ENTER event
7. Visitor stays 30s → ZONE_DWELL event
8. Visitor enters billing area → BILLING_QUEUE_JOIN event
9. POS transaction within 5-min window → visitor counted as converted
10. GET /stores/{id}/metrics computes:
    conversion_rate = len(billing_visitors) / len(entry_visitors)
```

---

## Concurrency Model

```
Main thread:   FastAPI (uvicorn) — handles all HTTP requests
Daemon thread: StoreMonitor — reads frames, runs inference, writes store_metrics
Shared state:  store_metrics dict + events_db list
```

For a production system with 40 stores: replace `store_metrics` with Redis pub/sub,
`events_db` with PostgreSQL + connection pool, and run the detection pipeline as a separate
containerised service per store with a message queue (Kafka/SQS) between pipeline and API.

---

## AI-Assisted Decisions

This section documents three specific places where AI shaped the design — including one where
I disagreed with the AI's suggestion.

### 1. Datetime Timezone Bug — AI Caught What I Missed

During development, `event_store.py` was using `datetime.utcnow()` to generate event
timestamps. I asked Claude to review the anomaly detection logic in `_within_minutes()`.
The AI identified that `datetime.utcnow()` returns a **naive datetime** (no tzinfo), while
`datetime.now(timezone.utc)` returns an **aware datetime** (+00:00). When these are compared,
Python raises `TypeError: can't compare offset-naive and offset-aware datetimes` — but only
at runtime during anomaly checks, not at ingest time. The bug would have silently broken all
time-window anomaly detection (DEAD_ZONE, BILLING_QUEUE_SPIKE) with no visible error at the
point of failure.

**I agreed with this completely.** One-line fix: `datetime.now(timezone.utc).isoformat()`.
I also added a defensive guard in `_within_minutes()` for any legacy naive timestamps:
```python
if dt.tzinfo is None:
    dt = dt.replace(tzinfo=timezone.utc)
```

### 2. ByteTrack vs DeepSORT — AI Confirmed My Instinct

I had initially planned to use DeepSORT because it was the most commonly referenced tracker
in retail CV examples. I asked Claude to compare ByteTrack and DeepSORT specifically for a
retail analytics use case where inference latency matters.

The AI confirmed what I had started to suspect: DeepSORT requires a separate appearance
embedding model (OSNet or similar), adding 50–80ms per frame. ByteTrack achieves comparable
tracking accuracy using only IoU-based matching + Kalman filter prediction with no Re-ID
network. For a 15fps CCTV feed where the same person is visible across consecutive frames,
ByteTrack's approach is sufficient and meaningfully faster.

**I agreed and switched to ByteTrack.** The AI's reasoning aligned with mine, and having the
trade-off clearly articulated helped me commit rather than second-guess the decision.

### 3. Rule-Based Vibe vs ML Classifier — I Overrode the AI

When designing vibe classification, I asked Claude whether to train a small classifier on
occupancy + zone features, or use a rule-based weighted formula. The AI initially suggested
a lightweight ML approach — a logistic regression or decision tree trained on synthetic
labels — arguing it would generalise better to edge cases.

**I disagreed and kept rule-based.** My reasoning: there is no ground-truth labeled dataset
for "store vibe." Any training labels would themselves be derived from the same rule-based
intuitions I was trying to replace — a synthetic training set would just encode the rules
with extra steps, adding model serialisation, versioning, and drift risk for no real accuracy
gain. The rule-based approach is explainable to store managers, immediately tunable without
retraining, and has no training pipeline dependency. The AI's suggestion was technically sound
but practically wrong for this context.

---

## Known Limitations

| Limitation | Root Cause | Production Fix |
|---|---|---|
| In-memory event store resets on restart | Render free tier, simplicity | PostgreSQL + event log |
| Single camera feed | One video source | Multi-camera + cross-camera Re-ID |
| Simulated zone coordinates | No camera calibration data | Homography mapping from store layout |
| No rate limiting on ingest endpoint | Prototype scope | API key auth + per-store rate limits |
| store_metrics not thread-safe under writes | GIL provides partial safety | Redis pub/sub |