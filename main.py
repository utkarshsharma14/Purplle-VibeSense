import threading
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core_ai import StoreMonitor
from vibe_engine import store_metrics

app = FastAPI(title="VibeSense AI - Analytics API Portal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def run_ai_pipeline():
    monitor = StoreMonitor("store.mp4")
    monitor.start_monitoring()

@app.on_event("startup")
def startup_event():
    threading.Thread(target=run_ai_pipeline, daemon=True).start()

@app.get("/")
def read_root():
    return {"status": "healthy", "service": "VibeSense Analytics Engine Core"}

@app.get("/api/v1/store/vibe")
def get_store_vibe():
    return {
        "current_occupancy": store_metrics["current_count"],
        "store_vibe": store_metrics["vibe"],
        "ambient_music": store_metrics["ambient_music"],
        "realtime_alerts": store_metrics["realtime_alerts"][-5:]
    }