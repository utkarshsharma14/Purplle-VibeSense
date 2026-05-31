# VibeSense AI — Store Intelligence System
> **Purplle Tech Challenge 2026 · Round 2**

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=python"/>
  <img src="https://img.shields.io/badge/FastAPI-0.110-green?style=for-the-badge&logo=fastapi"/>
  <img src="https://img.shields.io/badge/YOLOv8-Ultralytics-red?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Deployed-Render-purple?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Dashboard-Live-brightgreen?style=for-the-badge"/>
</p>

**Live Demo →** [purplle-vibesense.onrender.com](https://purplle-vibesense.onrender.com)

---

## 🧠 Problem Statement

Modern retail stores generate continuous CCTV footage but extract almost no intelligence from it. Store managers make decisions based on gut feeling — when to call more staff, which zone is underperforming, when the store is overcrowded.

**VibeSense AI** converts raw CCTV footage into a real-time store intelligence layer that answers:
- How many people are in the store right now?
- Which zones are hot vs cold?
- What is the current store "vibe" — and what music should play?
- Are there any anomalies that need immediate attention?

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CCTV / store.mp4                     │
└──────────────────────┬──────────────────────────────────────┘
                       │ Frame stream
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   AI Detection Pipeline                      │
│                                                             │
│   ┌─────────────┐    ┌──────────────┐    ┌──────────────┐  │
│   │  YOLOv8n    │───▶│  ByteTrack   │───▶│ Vibe Engine  │  │
│   │  Detection  │    │  Re-ID +     │    │ Occupancy +  │  │
│   │  ~30ms/frame│    │  Tracking    │    │ Zone mapping │  │
│   └─────────────┘    └──────────────┘    └──────┬───────┘  │
└──────────────────────────────────────────────────┼──────────┘
                                                   │
                       ┌───────────────────────────▼──────────┐
                       │         Event Bus (in-memory)         │
                       │  PERSON_ENTERED · ZONE_DWELL_EXCEEDED │
                       │  ANOMALY_DETECTED · VIBE_CHANGED      │
                       └───────────────────────────┬──────────┘
                                                   │
              ┌────────────────────────────────────▼──────────┐
              │               FastAPI Backend                   │
              │                                                │
              │  GET  /api/v1/store/vibe    (real-time state) │
              │  GET  /api/v1/store/events  (event stream)    │
              │  GET  /api/v1/store/zones   (zone analytics)  │
              │  POST /api/v1/store/config  (thresholds)      │
              └────────────────────────────────────┬──────────┘
                                                   │
              ┌────────────────────────────────────▼──────────┐
              │           Live Dashboard (HTML/JS)              │
              │  Occupancy · Vibe · Zones · Alerts · Export   │
              └────────────────────────────────────────────────┘
```

---

## 🔬 Technical Decisions & Trade-offs

### 1. Detection Model — YOLOv8n

**Why YOLOv8n over alternatives:**

| Model | Latency | Accuracy | Size | Decision |
|-------|---------|----------|------|----------|
| YOLOv8n | ~28ms | mAP 37.3 | 6.3MB | ✅ **Chosen** |
| YOLOv8s | ~45ms | mAP 44.9 | 22MB | Too slow for real-time |
| Faster R-CNN | ~120ms | mAP 46.2 | 140MB | Not suitable for streaming |
| MobileNet-SSD | ~20ms | mAP 23.1 | 6.9MB | Accuracy too low |

**Trade-off accepted:** YOLOv8n sacrifices ~7 mAP points vs YOLOv8s for a 40% latency improvement — critical for real-time retail analytics where sub-100ms response is expected.

---

### 2. Tracking — ByteTrack (Re-ID)

Without tracking, the same person walking through the frame gets counted multiple times — inflating occupancy counts by 3-5x in a typical retail store.

**ByteTrack** assigns persistent IDs across frames using IoU-based matching + Kalman filter prediction. This gives us:
- Unique visitor count (not raw detection count)
- Dwell time per person per zone
- Entry/exit events per individual

**Why not DeepSORT?** DeepSORT requires a separate Re-ID network (extra 50-80ms latency). ByteTrack achieves comparable tracking accuracy using only motion cues — no extra model needed.

---

### 3. Vibe Engine — Rule-based + Weighted Scoring

The "store vibe" is computed as a weighted composite:

```python
vibe_score = (
    occupancy_ratio * 0.40 +      # How full is the store?
    zone_activity_score * 0.35 +  # Which zones are active?
    dwell_time_score * 0.25       # Are people lingering or rushing?
)
```

**Why not ML classification for vibe?**
No labeled training data exists for "store vibe." A rule-based weighted system is:
- Explainable to business stakeholders
- Tunable without retraining
- Immediately deployable

This is a deliberate trade-off: **explainability over complexity.**

---

### 4. Event Architecture — In-Memory Bus (Production: Kafka)

Current implementation uses a Python `deque` as an in-memory event bus. Each detection frame emits structured events:

```json
{
  "event_type": "ZONE_DWELL_EXCEEDED",
  "timestamp": "2026-05-31T14:23:01Z",
  "zone_id": "cosmetics",
  "person_id": "track_042",
  "dwell_seconds": 187,
  "threshold_seconds": 120,
  "severity": "INFO"
}
```

**Production path:** Replace `deque` with **Apache Kafka** topic `store.events`. Each consumer (dashboard, alerting, analytics) subscribes independently. This design already separates producers from consumers — migrating to Kafka requires only changing the publish/subscribe layer.

**Why not Kafka now?** Render free tier doesn't support persistent services. The architecture is Kafka-ready; the implementation is constrained by deployment environment.

---

### 5. API Design — FastAPI over Flask/Django

| Criterion | FastAPI | Flask | Django |
|-----------|---------|-------|--------|
| Async support | ✅ Native | ⚠️ Via extensions | ⚠️ Via channels |
| Auto docs (OpenAPI) | ✅ Built-in | ❌ | ❌ |
| Pydantic validation | ✅ Built-in | ❌ | ❌ |
| Performance | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ |

FastAPI's native async support is critical — the detection pipeline runs in a background thread while the API serves requests concurrently without blocking.

---

## 📊 Data Integration — Brigade Road Store Data

The system integrates real footfall data from `Brigade_Bangalore_10_April_26.csv` to:
- Calibrate occupancy thresholds based on historical peak hours
- Validate vibe classification against known busy periods
- Generate realistic peak-hour simulation in the dashboard

Store zone layout is derived from `Brigade Road - Store layout.xlsx`, mapping physical zones (Checkout, Cosmetics, Aisle 3, Skincare Corner, Entrance) to detection regions in the video frame.

---

## 🚨 Anomaly Detection Logic

```
CRITICAL  → occupancy > 120% of store capacity threshold
WARNING   → single zone dwell > 3 minutes (potential queue)
INFO      → occupancy drop > 40% in under 5 minutes (unusual exit event)
```

Anomaly events are:
1. Logged to the event bus with full context
2. Surfaced immediately on the dashboard
3. Triggerable as browser push notifications
4. Exportable in CSV/JSON/HTML reports

---

## 🎵 Ambient Music Intelligence

| Vibe | Trigger | Music Profile |
|------|---------|---------------|
| Cozy & Premium | Occupancy < 40% capacity | Soft acoustic, BPM 60-80 |
| Moderate & Buzzing | Occupancy 40-75% capacity | Lo-fi indie, BPM 80-100 |
| Energetic & Crowded | Occupancy > 75% capacity | Upbeat synth-pop, BPM 100-130 |

Music transitions are smoothed with a 30-second hysteresis to prevent rapid switching on the boundary.

---

## 🗂️ Project Structure

```
Purplle-VibeSense/
├── main.py              # FastAPI app, routes, startup
├── core_ai.py           # YOLOv8 detection + ByteTrack pipeline
├── vibe_engine.py       # Vibe scoring, music mapping, shared metrics
├── make_video.py        # Video preprocessing utilities
├── test_run.py          # Pipeline test runner
├── templates/
│   └── index.html       # Full dashboard (2000+ lines, zero dependencies*)
├── store.mp4            # CCTV footage (not committed)
├── yolov8n.pt           # Detection model (not committed)
└── requirements.txt
```
*Dashboard uses Chart.js via CDN only — no build step required.

---

## 🚀 Local Setup

```bash
# Clone
git clone https://github.com/utkarshsharma14/Purplle-VibeSense.git
cd Purplle-VibeSense

# Install
pip install -r requirements.txt

# Run (make sure store.mp4 is in root)
python main.py

# Visit
open http://localhost:10000
```

---

## 📡 API Reference

### `GET /api/v1/store/vibe`
Returns current real-time store state.

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

### `GET /api/v1/store/zones` *(planned)*
Per-zone occupancy, dwell time, and heat index.

### `GET /api/v1/store/events` *(planned)*
Server-Sent Events stream of real-time store events.

---

## ⚠️ Known Limitations & Next Steps

| Limitation | Root Cause | Production Fix |
|------------|------------|----------------|
| Simulated zone data | No camera-zone calibration | Homography mapping from store layout |
| In-memory event bus | Render free tier | Apache Kafka |
| Single camera | One video file | Multi-camera with zone stitching |
| No Re-ID across cameras | ByteTrack is per-stream | Cross-camera Re-ID model |
| Free tier cold starts | Render spins down inactive services | Paid tier / Railway |

---

## 🏆 What Makes This Different

1. **End-to-end pipeline** — raw video in, business intelligence out
2. **Production-aware design** — every component has a documented production upgrade path
3. **Business-oriented output** — not just counts, but actionable retail intelligence
4. **Zero-dependency frontend** — the entire dashboard is a single HTML file, deployable anywhere
5. **Honest trade-off documentation** — limitations are documented, not hidden

---

## 👤 Author

**Utkarsh Sharma**
Purplle Tech Challenge 2026 — Round 2
Built with 🔥 and too much coffee.
