# VibeSense AI — Store Intelligence System
> **Purplle Tech Challenge 2026 · Round 2**

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9+-blue?style=for-the-badge&logo=python"/>
  <img src="https://img.shields.io/badge/FastAPI-latest-green?style=for-the-badge&logo=fastapi"/>
  <img src="https://img.shields.io/badge/YOLOv8n-Ultralytics-red?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/OpenCV-4.x-blue?style=for-the-badge&logo=opencv"/>
  <img src="https://img.shields.io/badge/Deployed-Render-purple?style=for-the-badge"/>
</p>

**Live Demo →** [purplle-vibesense.onrender.com](https://purplle-vibesense.onrender.com)

---

## 🧠 Problem Statement

Modern retail stores generate continuous CCTV footage but extract almost no intelligence from it. Store managers make decisions based on gut feeling — when to call more staff, which zone is underperforming, when the store is overcrowded.

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

> **Note:** `store.mp4` and `yolov8n.pt` are not committed to the repository per challenge rules. The detection pipeline auto-downloads `yolov8n.pt` on first run via Ultralytics.

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
├── main.py             # FastAPI app + background thread orchestration
│                       # Routes: dashboard serve, vibe API, AI insights
│
├── make_video.py       # Video preprocessing utilities
│                       # Handles: resolution normalisation, frame rate
│
├── test_run.py         # Pipeline test runner
│                       # Validates detection pipeline end-to-end
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

**Trade-off:** YOLOv8n loses ~7 mAP vs YOLOv8s but gains 40% latency reduction — critical for real-time retail analytics.

### 2. Tracking — ByteTrack over DeepSORT

ByteTrack uses IoU-based matching + Kalman filter prediction with **no extra Re-ID network**. DeepSORT requires a separate appearance model (+50-80ms). ByteTrack gives comparable tracking accuracy with zero added inference cost — a deliberate production trade-off.

### 3. Concurrency — Background Thread + Shared Dict

The detection pipeline runs as a daemon thread. `store_metrics` is a shared Python dict updated by the pipeline and read by FastAPI handlers. For production scale: replace with Redis pub/sub. Current design is intentionally simple and observable.

### 4. Vibe Engine — Rule-based Weighted Scoring

```python
vibe_score = (
    occupancy_ratio    * 0.40 +   # Store fullness
    zone_activity      * 0.35 +   # Which zones are active
    dwell_time_score   * 0.25     # Lingering vs rushing
)
```

No ML model for vibe — deliberate choice. No labeled training data exists for "store vibe." Rule-based is explainable, tunable, and immediately deployable.

### 5. Frontend — Single HTML File

The entire dashboard (`templates/index.html`) is a single self-contained file with zero build step. Chart.js loaded via CDN. This means: deployable anywhere, zero Node.js dependency, instant iteration. Trade-off: harder to maintain at scale.

---

## 📡 API Reference

### `GET /api/v1/store/vibe`
Real-time store state.

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

### `POST /api/v1/ai/insights`
AI-powered store recommendations (requires `ANTHROPIC_API_KEY` env var).

```json
{
  "count": 7,
  "vibe": "Cozy & Premium",
  "music": "Soft acoustic melodies playing.",
  "alerts": [],
  "avg_occupancy": 5,
  "dominant_vibe": "Cozy & Premium",
  "timestamp": "14:22:10"
}
```

---

## 🚨 Anomaly Detection

| Anomaly | Trigger | Severity |
|---------|---------|----------|
| Capacity exceeded | Occupancy > store threshold | CRITICAL |
| Zone dwell spike | Single zone dwell > 3 min | WARNING |
| Traffic drop | >40% occupancy drop in 5 min | INFO |

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
| In-memory metrics | Simplicity | Redis pub/sub |
| Single camera | One video source | Multi-camera + cross-camera Re-ID |
| No persistent storage | Render free tier | PostgreSQL + event log |
| Cold start delay | Render free tier | Paid tier / Railway |

---

## 👤 Author

**Utkarsh Sharma** — Purplle Tech Challenge 2026, Round 2