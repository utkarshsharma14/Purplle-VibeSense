# DESIGN.md

## Architecture

Video Source
↓
StoreMonitor
↓
VibeEngine
↓
Store Metrics
↓
FastAPI API Layer
↓
Dashboard + AI Insights

## Components

### StoreMonitor

Responsible for continuously processing incoming video streams and forwarding frame information to the analytics engine.

### VibeEngine

Calculates occupancy, vibe classification, anomaly flags, alerts, and telemetry.

### Event Layer

Stores structured events such as ENTRY, EXIT, ZONE_ENTER, and ZONE_DWELL.

### API Layer

Provides endpoints for:

* Store Vibe
* Event Ingestion
* Health Checks
* Metrics
* Funnel Analytics
* Anomaly Detection

### Dashboard

Displays occupancy, vibe, alerts, and AI-generated recommendations in real time.

## Future Improvements

* Multi-camera support
* PostgreSQL persistence
* Kafka event streaming
* Real YOLO-based occupancy tracking
* Heatmap generation
* Queue analytics
