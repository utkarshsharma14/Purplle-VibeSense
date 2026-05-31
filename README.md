# VibeSense AI — Store Intelligence System
> **Purplle Tech Challenge 2026 · Round 2**

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue?style=for-the-badge&logo=python"/>
  <img src="https://img.shields.io/badge/FastAPI-latest-green?style=for-the-badge&logo=fastapi"/>
  <img src="https://img.shields.io/badge/YOLOv8n-Ultralytics-red?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/OpenCV-4.x-blue?style=for-the-badge&logo=opencv"/>
  <img src="https://img.shields.io/badge/Deployed-Render-purple?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Tests-33%20passing-brightgreen?style=for-the-badge&logo=pytest"/>
</p>

**Live Demo →** [purplle-vibesense.onrender.com](https://purplle-vibesense.onrender.com)  
**API Docs →** [purplle-vibesense.onrender.com/docs](https://purplle-vibesense.onrender.com/docs)

---

## 🧠 Problem Statement

Modern retail stores generate continuous CCTV footage but extract almost no intelligence from it.
Store managers make decisions based on gut feeling — when to call more staff, which zone is
underperforming, when the store is overcrowded.

**VibeSense AI** converts raw CCTV footage into a real-time store intelligence layer that answers:

- How many unique customers are in the store right now?
- Which zones have the highest dwell time and foot traffic?
- What is the current store "vibe" — and what ambient music should play?
- Are there any operational anomalies that need immediate attention?

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     store.mp4 / CCTV Feed                   │
└──────────────────────┬──────────────────────────────────────┘
                       │ Frame stream (OpenCV)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                core_ai.py — Detection Pipeline              │
│                                                             │
│   ┌─────────────┐    ┌──────────────┐    ┌──────────────┐   │
│   │  YOLOv8n    │───▶│  ByteTrack   │───▶│ Zone Mapper  │   │
│   │  Detection  │    │  Re-ID +     │    │ Entry/Exit   │   │
│   │  ~28ms/frame│    │  Tracking    │    │ Direction    │   │
│   └─────────────┘    └──────────────┘    └──────┬───────┘   │
└──────────────────────────────────────────────────┼──────────┘
                                                   │
                  ┌────────────────────────────────▼─────────┐
                  │      vibe_engine.py — Shared Metrics     │
                  │  store_metrics dict (thread-safe)        │
                  │  current_count · vibe · music · alerts   │
                  └────────────────────────────────┬─────────┘
                                                   │
              ┌────────────────────────────────────▼─────────┐
              │          main.py — FastAPI Backend           │
              │                                              │
              │  GET  /                    → Dashboard       │
              │  GET  /api/v1/store/vibe   → Live metrics    │
              │  POST /api/v1/ai/insights  → AI analysis     │
              │  POST /events/ingest       → Event pipeline  │
              │  GET  /stores/{id}/...     → Analytics API   │
              └────────────────────────────────────┬─────────┘
                                                   │
              ┌────────────────────────────────────▼─────────┐
              │     templates/index.html — Live Dashboard    │
              │  KPIs · Charts · Heatmap · Alerts · Export   │
              └──────────────────────────────────────────────┘
```

---

## 🚀 Setup — 5 Commands

```bash
# 1. Clone
git clone https://github.com/utkarshsharma14/Purplle-VibeSense.git
cd Purplle-VibeSense

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your CCTV footage (not committed — see note below)
# Place store.mp4 in the repo root

# 4. Run
python main.py

# 5. Open dashboard
open http://localhost:10000
```

> **Note:** `store.mp4` and `yolov8n.pt` are not committed to the repository per challenge rules.
> The detection pipeline auto-downloads `yolov8n.pt` on first run via Ultralytics.

---

## 🗂️ Project Structure

```
Purplle-VibeSense/
├── core_ai.py          # YOLOv8 detection + ByteTrack tracking pipeline
│                       # Handles: occupancy counting, zone detection,
│                       # entry/exit direction, dwell time tracking
│
├── vibe_engine.py      # Vibe scoring engine + shared metrics registry
│                       # Computes: store vibe, ambient music mapping,
│                       # anomaly detection, alert generation
│
├── event_store.py      # Shared in-memory event store (events_db)
│                       # Single source of truth for all ingested events
│                       # Timezone-aware timestamps throughout
│
├── main.py             # FastAPI app + background thread orchestration
│                       # Routes: dashboard, vibe API, analytics, AI insights
│
├── models.py           # Pydantic event schema with validation
│
├── make_video.py       # Video preprocessing utilities
│                       # Handles: resolution normalisation, frame rate
│
├── test_main.py        # Full pytest suite — 33 tests across 9 endpoints
│                       # Covers: idempotency, edge cases, anomaly detection,
│                       # funnel re-entry dedup, staff exclusion
│
├── templates/
│   └── index.html      # Full-stack live dashboard (single file, ~2000 lines)
│                       # Features: KPIs, charts, heatmap, alerts,
│                       # sound engine, live stream, CSV/JSON export
│
├── requirements.txt    # Python dependencies
├── store.mp4           # CCTV footage (NOT committed — add locally)
└── yolov8n.pt          # Detection model (NOT committed — auto-downloaded)
```

---

## 🔬 Technical Decisions & Trade-offs

### 1. Detection Model — YOLOv8n

| Model | Latency | mAP | Size | Decision |
|-------|---------|-----|------|----------|
| YOLOv8n | ~28ms | 37.3 | 6.3MB | ✅ Chosen |
| YOLOv8s | ~45ms | 44.9 | 22MB | Too slow for real-time |
| Faster R-CNN | ~120ms | 46.2 | 140MB | Not streaming-viable |
| MobileNet-SSD | ~20ms | 23.1 | 6.9MB | Accuracy insufficient |

**Trade-off:** YOLOv8n loses ~7 mAP vs YOLOv8s but gains 40% latency reduction — critical for
real-time retail analytics.

### 2. Tracking — ByteTrack over DeepSORT

ByteTrack uses IoU-based matching + Kalman filter prediction with **no extra Re-ID network**.
DeepSORT requires a separate appearance model (+50–80ms). ByteTrack gives comparable tracking
accuracy with zero added inference cost — a deliberate production trade-off.

### 3. Concurrency — Background Thread + Shared Dict

The detection pipeline runs as a daemon thread. `store_metrics` is a shared Python dict updated
by the pipeline and read by FastAPI handlers. For production scale: replace with Redis pub/sub.
Current design is intentionally simple and observable.

### 4. Vibe Engine — Rule-based Weighted Scoring

```python
vibe_score = (
    occupancy_ratio    * 0.40 +   # Store fullness
    zone_activity      * 0.35 +   # Which zones are active
    dwell_time_score   * 0.25     # Lingering vs rushing
)
```

No ML model for vibe — deliberate choice. No labeled training data exists for "store vibe."
Rule-based is explainable, tunable, and immediately deployable.

### 5. Frontend — Single HTML File

The entire dashboard (`templates/index.html`) is a single self-contained file with zero build
step. Chart.js loaded via CDN. Deployable anywhere, zero Node.js dependency, instant iteration.
Trade-off: harder to maintain at scale.

---

## 📡 API Reference

Full interactive docs at **[/docs](https://purplle-vibesense.onrender.com/docs)**

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Feed status, uptime, anomaly flag |
| `GET` | `/api/v1/store/vibe` | Live occupancy, vibe, music, alerts |
| `POST` | `/api/v1/ai/insights` | Claude-powered store recommendations |
| `POST` | `/events/ingest` | Idempotent event ingest (dedup by event_id) |
| `GET` | `/stores/{id}/metrics` | Unique visitors, conversion rate, dwell per zone |
| `GET` | `/stores/{id}/funnel` | Entry → Zone Visit → Billing Queue → Purchase |
| `GET` | `/stores/{id}/heatmap` | Zone traffic normalised 0–100 with confidence |
| `GET` | `/stores/{id}/anomalies` | Active anomalies with severity + suggested action |
| `GET` | `/stores/{id}/events` | Raw event log with limit pagination |
| `GET` | `/stores/{id}/zones` | Zone occupancy and avg dwell seconds |

### Example — `GET /api/v1/store/vibe`

```json
{
  "current_occupancy": 7,
  "store_vibe": "Cozy & Premium",
  "ambient_music": "Soft acoustic melodies playing.",
  "realtime_alerts": [
    "💡 Floor Alert: High linger-duration observed near aisle 3."
  ]
}
```

### Example — `POST /events/ingest`

```json
[
  {
    "event_id": "uuid-here",
    "store_id": "STORE_001",
    "camera_id": "CAM_ENTRY_01",
    "visitor_id": "VIS_abc123",
    "event_type": "ENTRY",
    "timestamp": "2026-05-31T10:00:00+00:00",
    "zone_id": null,
    "dwell_ms": 0,
    "is_staff": false,
    "confidence": 0.95,
    "metadata": {}
  }
]
```

Response:
```json
{
  "status": "success",
  "inserted": 1,
  "duplicates": 0,
  "errors": [],
  "total_events": 1
}
```

### Example — `GET /stores/{id}/anomalies`

```json
{
  "store_id": "STORE_001",
  "active_anomalies": [
    {
      "anomaly_type": "CONVERSION_DROP",
      "severity": "WARN",
      "description": "Conversion 8.3% below 25% baseline. 12 visitors, 1 reached billing.",
      "suggested_action": "Deploy floor staff to guide customers to billing.",
      "value": 0.0833
    }
  ],
  "checked_at": "2026-05-31T18:24:28+00:00"
}
```

---

## 🧪 Tests

```bash
pytest test_main.py -v
```

**33 tests · 9 endpoints · zero state leakage between tests**

| Class | Tests | What It Covers |
|-------|-------|----------------|
| `TestHealth` | 4 | Feed status transitions, response shape |
| `TestStoreVibe` | 2 | Live vibe fields |
| `TestIngest` | 5 | Idempotency, batch, accumulation |
| `TestMetrics` | 7 | Staff exclusion, zero traffic, dwell, store isolation |
| `TestFunnel` | 5 | Re-entry dedup, stage order, dropoff never negative |
| `TestHeatmap` | 4 | Normalisation, sort order, confidence flag |
| `TestAnomalies` | 5 | Conversion drop, dead zone, severity values |
| `TestStoreEvents` | 3 | Pagination, isolation |
| `TestZones` | 4 | Occupancy count, staff exclusion, dwell calc |
| `TestAIInsights` | 3 | Missing key → 500, bad shape → 422, live skip |

Key edge cases covered:
- **Idempotency** — same event_id sent twice → second call returns `inserted: 0, duplicates: 1`
- **Staff exclusion** — `is_staff=True` events never count as unique visitors
- **Re-entry dedup** — `REENTRY` event type never inflates funnel ENTRY count
- **Store isolation** — events for STORE_A never appear in STORE_B metrics
- **Zero traffic** — all endpoints return valid zero-state, never crash

---

## 🚨 Anomaly Detection

| Anomaly | Trigger | Severity |
|---------|---------|----------|
| `CAPACITY_EXCEEDED` | Occupancy > store threshold | CRITICAL |
| `BILLING_QUEUE_SPIKE` | Queue depth ≥ 8 in last 5 min | CRITICAL |
| `CONVERSION_DROP` | Conversion < 25% with 10+ visitors | WARN |
| `BILLING_QUEUE_SPIKE` | Queue depth 5–7 in last 5 min | WARN |
| `DEAD_ZONE` | Zone with no visits in last 30 min | INFO |

Each anomaly includes a `suggested_action` string for floor staff.

---

## 🎵 Ambient Music Intelligence

| Vibe | Occupancy | Music |
|------|-----------|-------|
| Cozy & Premium | < 40% capacity | Soft acoustic · BPM 60–80 |
| Moderate & Buzzing | 40–75% capacity | Lo-fi indie · BPM 80–100 |
| Energetic & Crowded | > 75% capacity | Upbeat synth-pop · BPM 100–130 |

Transitions use 30-second hysteresis to prevent boundary flickering.

---

## ⚠️ Known Limitations & Production Path

| Limitation | Root Cause | Production Fix |
|------------|------------|----------------|
| Simulated zone coordinates | No camera calibration | Homography mapping from store layout |
| In-memory event store | Simplicity | PostgreSQL + event log |
| In-memory metrics | Simplicity | Redis pub/sub |
| Single camera | One video source | Multi-camera + cross-camera Re-ID |
| Cold start delay | Render free tier | Paid tier / Railway |
| Naive timestamps in AI pipeline | `datetime.utcnow()` legacy | Fixed — `datetime.now(timezone.utc)` |

---

## 👤 Author

**Utkarsh Sharma** — Purplle Tech Challenge 2026, Round 2