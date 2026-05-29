# VibeSense AI - Empathetic Retail Analytics Engine

VibeSense AI is a real-time computer vision and analytics pipeline designed to transform standard retail video feeds into live, actionable operational insights. By leveraging advanced object tracking and spatial analytics, the system maps customer dwell times, calculates real-time store congestion states ("Vibes"), and dispatches contextual alerts to floor staff to maximize engagement opportunities.

##  Key Features
- **Real-Time Automated Tracking:** Utilizes a state-optimized YOLOv8 tracking architecture to isolate shopper footprints while ignoring environmental noise.
- **Dynamic Store Vibe Engine:** Computes immediate customer volumes to classify overall store atmosphere and recommend ambient background adjustments.
- **Dwell Time Analytics:** Automatically flags high-intent customers who remain in localized zones (e.g., Cosmetics Section) for extended intervals, enabling timely assistant interventions.
- **Production-Ready API Gateway:** Exposes thread-safe, high-frequency internal application metrics via clean FastAPI endpoints.

##  System Architecture & Stack
- **Core Vision Layer:** Python 3.9+, OpenCV, Ultralytics YOLOv8
- **Backend API Layer:** FastAPI, Uvicorn Web Server
- **Concurrency Model:** Multi-threaded asynchronous daemon workers

##  Project Repository Directory Layout
```text
Purplle-VibeSense/
├── core_ai.py          # Vision capture pipeline & YOLO object tracking loops
├── vibe_engine.py      # Metric computation, state machine, & registry logic
├── main.py             # FastAPI framework setup & background execution pool
├── requirements.txt    # Application dependency manifests
└── store.mp4           # Target video source file asset